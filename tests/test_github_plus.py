"""Unit tests against a mocked PyGithub repository. One test per fixed bug, plus the new methods."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from github import GithubException
from github.GithubObject import NotSet
from github.WorkflowRun import WorkflowRun

from python_github_plus import GitHubClient
from python_github_plus.github_plus import (
    GitHubBranchService,
    GitHubFileService,
    GitHubProjectService,
    GitHubPRService,
    GitHubTagService,
    GitHubWorkflowService,
    take,
)


@pytest.fixture(name="repo")
def fixture_repo() -> MagicMock:
    return MagicMock(default_branch="master")


def make_workflow(wf_id: int, name: str, path: str) -> MagicMock:
    workflow = MagicMock(id=wf_id, path=path)
    workflow.name = name  # `name` is a MagicMock constructor argument, so set it afterwards
    return workflow


@pytest.fixture(name="workflows")
def fixture_workflows(repo: MagicMock) -> list[MagicMock]:
    workflows = [
        make_workflow(1, "CI", ".github/workflows/ci.yml"),
        make_workflow(2, "Release", ".github/workflows/release.yml"),
    ]
    repo.get_workflows.return_value = workflows
    return workflows


# ---------- take / limits ----------


def test_take_stops_early_without_materializing_everything() -> None:
    consumed = []

    def items():
        for i in range(10_000):
            consumed.append(i)
            yield i

    assert take(items(), 3) == [0, 1, 2]
    assert len(consumed) == 3


def test_take_rejects_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        take([1, 2], 0)


def test_list_methods_respect_limit(repo: MagicMock) -> None:
    repo.get_branches.return_value = iter(range(5000))
    repo.get_tags.return_value = iter(range(5000))
    repo.get_collaborators.return_value = iter(range(5000))
    assert len(GitHubBranchService(repo).list(limit=10)) == 10
    assert len(GitHubTagService(repo).list(limit=10)) == 10
    assert len(GitHubProjectService(repo).list_members(limit=10)) == 10


# ---------- workflows ----------


def test_wait_until_finished_returns_conclusion_of_completed_run(repo: MagicMock) -> None:
    repo.get_workflow_run.return_value = SimpleNamespace(status="completed", conclusion="success")
    assert GitHubWorkflowService(repo).wait_until_finished(1, check_interval=0, timeout=60) == "success"
    assert repo.get_workflow_run.call_count == 1


def test_wait_until_finished_polls_until_completed(repo: MagicMock) -> None:
    repo.get_workflow_run.side_effect = [
        SimpleNamespace(status="queued", conclusion=None),
        SimpleNamespace(status="in_progress", conclusion=None),
        SimpleNamespace(status="completed", conclusion="failure"),
    ]
    assert GitHubWorkflowService(repo).wait_until_finished(1, check_interval=0, timeout=60) == "failure"
    assert repo.get_workflow_run.call_count == 3


def test_wait_until_finished_times_out(repo: MagicMock) -> None:
    repo.get_workflow_run.return_value = SimpleNamespace(status="in_progress", conclusion=None)
    with pytest.raises(TimeoutError):
        GitHubWorkflowService(repo).wait_until_finished(1, check_interval=0, timeout=0)
    assert repo.get_workflow_run.call_count == 1  # checked once before giving up


@pytest.mark.parametrize("key", ["CI", "ci.yml", ".github/workflows/ci.yml", 1, "ci"])
def test_find_workflow_by_name_file_path_id_or_casefolded_name(
    repo: MagicMock, workflows: list[MagicMock], key: str | int
) -> None:
    assert GitHubWorkflowService(repo).find(key) is workflows[0]


@pytest.mark.usefixtures("workflows")
def test_find_workflow_not_found_lists_available(repo: MagicMock) -> None:
    with pytest.raises(ValueError, match=r"not found.*CI \(ci.yml\)"):
        GitHubWorkflowService(repo).find("deploy")


def test_find_workflow_ambiguous(repo: MagicMock) -> None:
    repo.get_workflows.return_value = [
        make_workflow(1, "Build", ".github/workflows/a.yml"),
        make_workflow(2, "build", ".github/workflows/b.yml"),
    ]
    with pytest.raises(ValueError, match="ambiguous"):
        GitHubWorkflowService(repo).find("BUILD")


def test_trigger_uses_default_branch_raises_on_failure_and_returns_run(
    repo: MagicMock, workflows: list[MagicMock]
) -> None:
    run = MagicMock(spec=WorkflowRun)
    workflows[0].create_dispatch.return_value = run
    assert GitHubWorkflowService(repo).trigger("ci.yml") is run
    workflows[0].create_dispatch.assert_called_once_with(ref="master", inputs={}, throw=True, return_run_details=True)


def test_trigger_returns_none_when_github_reports_no_run(repo: MagicMock, workflows: list[MagicMock]) -> None:
    workflows[0].create_dispatch.return_value = True  # GitHub Enterprise without run details
    assert GitHubWorkflowService(repo).trigger("CI", branch_name="dev") is None


def test_last_run_by_id_without_runs_returns_none(repo: MagicMock) -> None:
    repo.get_workflow.return_value.get_runs.return_value = []
    assert GitHubWorkflowService(repo).last_run_by_id(1) is None


def test_list_runs_respects_limit_and_branch(repo: MagicMock, workflows: list[MagicMock]) -> None:
    workflows[0].get_runs.return_value = iter(range(5000))
    assert len(GitHubWorkflowService(repo).list_runs("CI", branch="main", limit=5)) == 5
    workflows[0].get_runs.assert_called_once_with(branch="main")


# ---------- tags and branches ----------


def test_tag_create_from_sha_tags_the_given_commit(repo: MagicMock) -> None:
    repo.create_git_tag.return_value = MagicMock(sha="tag-object-sha")
    GitHubTagService(repo).create_from_sha("v1.0.0", sha="abc123")
    repo.create_git_tag.assert_called_once_with(tag="v1.0.0", message="v1.0.0", object="abc123", type="commit")
    repo.create_git_ref.assert_called_once_with(ref="refs/tags/v1.0.0", sha="tag-object-sha")


def test_tag_create_defaults_to_default_branch_head(repo: MagicMock) -> None:
    repo.get_branch.return_value.commit.sha = "head-sha"
    GitHubTagService(repo).create("v1.0.0")
    repo.get_branch.assert_called_once_with("master")
    assert repo.create_git_tag.call_args.kwargs["object"] == "head-sha"


def test_branch_create_defaults_to_default_branch(repo: MagicMock) -> None:
    GitHubBranchService(repo).create("feature/x")
    repo.get_git_ref.assert_called_once_with("heads/master")


def test_protect_maps_review_settings_correctly(repo: MagicMock) -> None:
    GitHubBranchService(repo).protect("main", require_code_owner_reviews=True, required_approving_review_count=2)
    repo.get_branch.return_value.edit_protection.assert_called_once_with(
        enforce_admins=True,
        dismiss_stale_reviews=True,
        required_approving_review_count=2,
        require_code_owner_reviews=True,
    )


def test_protect_without_reviews_sends_no_review_settings(repo: MagicMock) -> None:
    GitHubBranchService(repo).protect(
        "main", require_pull_request_reviews=False, require_status_checks=True, status_check_contexts=["ci"]
    )
    repo.get_branch.return_value.edit_protection.assert_called_once_with(
        enforce_admins=True, contexts=["ci"], strict=False
    )


# ---------- errors are raised, not swallowed ----------


@pytest.mark.parametrize("method", ["add_member", "remove_member"])
def test_member_errors_propagate(repo: MagicMock, method: str) -> None:
    error = GithubException(404, {"message": "Not Found"}, None)
    repo.add_to_collaborators.side_effect = error
    repo.remove_from_collaborators.side_effect = error
    with pytest.raises(GithubException):
        getattr(GitHubProjectService(repo), method)("nobody")


# ---------- pull requests ----------


def test_pr_create_with_body_draft_and_default_target(repo: MagicMock) -> None:
    GitHubPRService(repo).create("Title", "feature/x", body="Why", draft=True)
    repo.create_pull.assert_called_once_with(title="Title", head="feature/x", base="master", body="Why", draft=True)


def test_pr_list_passes_filters_and_limit(repo: MagicMock) -> None:
    repo.get_pulls.return_value = iter(range(100))
    assert len(GitHubPRService(repo).list(state="closed", base="main", limit=7)) == 7
    repo.get_pulls.assert_called_once_with(state="closed", base="main", head=NotSet)


def test_pr_files(repo: MagicMock) -> None:
    repo.get_pull.return_value.get_files.return_value = iter(["a.py", "b.py", "c.py"])
    assert GitHubPRService(repo).files(5, limit=2) == ["a.py", "b.py"]


def test_pr_merge_returns_sha(repo: MagicMock) -> None:
    repo.get_pull.return_value.merge.return_value = SimpleNamespace(merged=True, sha="merge-sha", message="ok")
    assert GitHubPRService(repo).merge(5, merge_method="squash") == "merge-sha"
    repo.get_pull.return_value.merge.assert_called_once_with(
        merge_method="squash", commit_title=NotSet, commit_message=NotSet
    )


def test_pr_merge_raises_when_not_merged(repo: MagicMock) -> None:
    repo.get_pull.return_value.merge.return_value = SimpleNamespace(merged=False, sha=None, message="conflict")
    with pytest.raises(ValueError, match="conflict"):
        GitHubPRService(repo).merge(5)


def test_pr_merge_rejects_unknown_method(repo: MagicMock) -> None:
    with pytest.raises(ValueError, match="merge_method"):
        GitHubPRService(repo).merge(5, merge_method="fast-forward")  # type: ignore[arg-type]


def test_pr_assign_accepts_list(repo: MagicMock) -> None:
    GitHubPRService(repo).assign(5, ["a", "b"])
    repo.get_issue.return_value.add_to_assignees.assert_called_once_with("a", "b")


# ---------- files ----------


def test_fetch_content_uses_default_branch_when_ref_not_given(repo: MagicMock) -> None:
    repo.get_contents.return_value = MagicMock(encoding="base64", decoded_content=b"hello")
    assert GitHubFileService(repo).fetch_content("README.md") == "hello"
    repo.get_contents.assert_called_once_with("README.md", ref=NotSet)


def test_fetch_content_on_directory_raises_value_error(repo: MagicMock) -> None:
    repo.get_contents.return_value = [MagicMock(), MagicMock()]
    with pytest.raises(ValueError, match="directory"):
        GitHubFileService(repo).fetch_content("src")


def test_fetch_content_large_file_reads_blob(repo: MagicMock) -> None:
    repo.get_contents.return_value = MagicMock(encoding="none", sha="blob-sha")
    repo.get_git_blob.return_value = MagicMock(content="aGVsbG8=")  # "hello"
    assert GitHubFileService(repo).fetch_content("big.json", ref="dev") == "hello"
    repo.get_git_blob.assert_called_once_with("blob-sha")


def test_list_dir_on_file_raises(repo: MagicMock) -> None:
    repo.get_contents.return_value = MagicMock()
    with pytest.raises(ValueError, match="not a directory"):
        GitHubFileService(repo).list_dir("README.md")


# ---------- client ----------


def test_client_without_token_raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACCESS_TOKEN", raising=False)
    with patch("python_github_plus.github_plus.load_dotenv"), pytest.raises(ValueError, match="GITHUB_ACCESS_TOKEN"):
        GitHubClient("owner/repo")


@pytest.mark.parametrize("name", ["repo", "owner/", "/repo", "a/b/c"])
def test_client_rejects_bad_repo_name(name: str) -> None:
    with pytest.raises(ValueError, match="owner/name"):
        GitHubClient(name, access_token="t")


def test_client_makes_no_api_calls_and_shares_connection() -> None:
    with patch("python_github_plus.github_plus.Github") as github_cls:
        client = GitHubClient("owner/a", access_token="t")
        other = client.for_repo("owner/b")
    github = github_cls.return_value
    assert github_cls.call_count == 1
    assert other.github is github
    github.get_user.assert_not_called()
    assert github.get_repo.call_args_list[0].args == ("owner/a",)
    assert all(call.kwargs == {"lazy": True} for call in github.get_repo.call_args_list)


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        (None, "https://api.github.com"),
        ("github.example.com/api/v3", "https://github.example.com/api/v3"),
        ("https://github.example.com/api/v3/", "https://github.example.com/api/v3"),
    ],
)
def test_client_base_url(monkeypatch: pytest.MonkeyPatch, base_url: str | None, expected: str) -> None:
    monkeypatch.delenv("GITHUB_BASE_URL", raising=False)
    with (
        patch("python_github_plus.github_plus.Github") as github_cls,
        patch("python_github_plus.github_plus.load_dotenv"),
    ):
        GitHubClient("owner/a", access_token="t", base_url=base_url)
    assert github_cls.call_args.kwargs["base_url"] == expected


def test_import_does_not_load_dotenv() -> None:
    import importlib  # pylint: disable=import-outside-toplevel

    import python_github_plus  # pylint: disable=import-outside-toplevel

    with patch("dotenv.load_dotenv") as load:
        importlib.reload(python_github_plus)
    load.assert_not_called()
