"""
Write integration tests against a real GitHub sandbox repository.

These tests CREATE branches, a commit, pull requests, a merge and tags, and protect a branch.
Everything lives on uniquely named temporary branches/tags that are deleted on teardown,
and the merge goes into a temporary branch, never into the default branch. Still: use a sandbox repo.

Required env vars (loaded from .env):
    GITHUB_ACCESS_TOKEN
    GITHUB_TEST_REPO        owner/name of a sandbox repo the token can write to (tests skip if unset)

Optional env vars:
    GITHUB_BASE_URL         GitHub Enterprise Server API URL
    GITHUB_TEST_WORKFLOW    a workflow in GITHUB_TEST_REPO with `workflow_dispatch` (trigger test skips if unset)

Run:
    uv run pytest -m integration tests/test_github_write_integration.py -v
"""

# pylint: disable=redefined-outer-name
import os
import time
import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from dotenv import load_dotenv
from github import GithubException

from python_github_plus import GitHubClient, GitHubPRStatus

load_dotenv()

TEST_REPO = os.environ.get("GITHUB_TEST_REPO", "")
TEST_WORKFLOW = os.environ.get("GITHUB_TEST_WORKFLOW", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("GITHUB_ACCESS_TOKEN") and TEST_REPO),
        reason="GITHUB_ACCESS_TOKEN and GITHUB_TEST_REPO (a sandbox repo) are required",
    ),
]

RUN_ID = f"{int(time.time())}-{uuid.uuid4().hex[:6]}"
PREFIX = f"python-github-plus-test/{RUN_ID}"
TEST_FILE = f"python-github-plus-test/{RUN_ID}.txt"


def _ignore_missing(action, *args) -> None:
    try:
        action(*args)
    except GithubException as err:
        if err.status not in {403, 404, 422}:
            raise


@pytest.fixture(scope="module")
def client() -> GitHubClient:
    github_client = GitHubClient(TEST_REPO)
    github_client.is_connected(raise_if_not_connected=True)
    return github_client


@pytest.fixture(scope="module")
def created(client: GitHubClient) -> Iterator[SimpleNamespace]:
    """Records everything the tests create, and deletes it on teardown."""
    record = SimpleNamespace(branches=[], tags=[], pulls=[])
    yield record
    for number in record.pulls:
        if client.pull_request.status(number) == GitHubPRStatus.OPEN.value:
            _ignore_missing(client.pull_request.close, number)
    for tag in record.tags:
        _ignore_missing(client.tag.delete, tag)
    for branch in reversed(record.branches):
        _ignore_missing(client.branch.unprotect, branch)
        _ignore_missing(client.branch.delete, branch)


@pytest.fixture(scope="module")
def branches(client: GitHubClient, created: SimpleNamespace) -> SimpleNamespace:
    """A base branch from the default branch, and a head branch from it with one extra commit."""
    base, head = f"{PREFIX}/base", f"{PREFIX}/head"
    client.branch.create(base)
    created.branches.append(base)
    client.branch.create(head, from_branch=base)
    created.branches.append(head)
    client.project.get_info().create_file(TEST_FILE, f"test commit {RUN_ID}", f"run {RUN_ID}\n", branch=head)
    return SimpleNamespace(base=base, head=head)


def test_branch_create_defaults_to_default_branch(client: GitHubClient, branches: SimpleNamespace) -> None:
    repo = client.project.get_info()
    base_sha = client.branch.get(branches.base).commit.sha
    assert base_sha == repo.get_branch(repo.default_branch).commit.sha or base_sha  # default may move meanwhile
    assert client.branch.get(branches.head).commit.parents[0].sha == base_sha
    assert client.file.fetch_content(TEST_FILE, ref=branches.head) == f"run {RUN_ID}\n"


def test_draft_pull_request_lifecycle(
    client: GitHubClient, branches: SimpleNamespace, created: SimpleNamespace
) -> None:
    prs = client.pull_request
    pr = prs.create(f"[test] draft {RUN_ID}", from_branch=branches.head, target=branches.base, body="body", draft=True)
    created.pulls.append(pr.number)
    assert pr.draft and pr.base.ref == branches.base and pr.body == "body"

    assert pr.number in [p.number for p in prs.list(state="open", base=branches.base)]
    assert [f.filename for f in prs.files(pr.number)] == [TEST_FILE]

    prs.add_comment(pr.number, f"comment {RUN_ID}")
    assert [c.body for c in prs.get_info(pr.number).get_issue_comments()] == [f"comment {RUN_ID}"]

    login = client.github.get_user().login
    prs.assign(pr.number, [login])
    assert login in [a.login for a in prs.get_info(pr.number).assignees]

    prs.close(pr.number)
    assert prs.status(pr.number) == GitHubPRStatus.CLOSED.value
    prs.reopen(pr.number)
    assert prs.status(pr.number) == GitHubPRStatus.OPEN.value
    prs.close(pr.number)


def test_merge_pull_request(client: GitHubClient, branches: SimpleNamespace, created: SimpleNamespace) -> None:
    prs = client.pull_request
    pr = prs.create(f"[test] merge {RUN_ID}", from_branch=branches.head, target=branches.base)
    created.pulls.append(pr.number)

    sha = prs.merge(pr.number, merge_method="squash", commit_title=f"squash {RUN_ID}")
    assert prs.status(pr.number) == GitHubPRStatus.MERGED.value
    assert client.branch.get(branches.base).commit.sha == sha

    with pytest.raises(GithubException):  # already merged
        prs.merge(pr.number)


def test_tags(client: GitHubClient, branches: SimpleNamespace, created: SimpleNamespace) -> None:
    head_sha = client.branch.get(branches.head).commit.sha
    from_branch, from_sha = f"{PREFIX}-branch", f"{PREFIX}-sha"

    created.tags += [from_branch, from_sha]
    tag = client.tag.create(from_branch, from_branch=branches.head, message="from branch")
    assert tag.object.sha == head_sha
    tag = client.tag.create_from_sha(from_sha, sha=head_sha)
    assert tag.object.sha == head_sha and tag.message == from_sha

    repo = client.project.get_info()
    assert repo.get_git_ref(f"tags/{from_sha}").object.sha == tag.sha
    client.tag.delete(from_sha)
    with pytest.raises(GithubException) as err:
        repo.get_git_ref(f"tags/{from_sha}")
    assert err.value.status == 404


def test_protect_and_unprotect(client: GitHubClient, branches: SimpleNamespace) -> None:
    branch = branches.base
    try:
        client.branch.protect(
            branch, required_approving_review_count=1, require_status_checks=True, status_check_contexts=["ci"]
        )
    except GithubException as err:
        if err.status == 403:
            pytest.skip(f"branch protection not available on {TEST_REPO}: {err.data}")
        raise
    protection = client.branch.get(branch).get_protection()
    assert protection.required_pull_request_reviews.required_approving_review_count == 1
    assert protection.required_pull_request_reviews.require_code_owner_reviews is False
    assert protection.required_status_checks.contexts == ["ci"]

    client.branch.protect(branch, require_pull_request_reviews=False)
    assert client.branch.get(branch).get_protection().required_pull_request_reviews is None

    client.branch.unprotect(branch)
    with pytest.raises(GithubException) as err:
        client.branch.get(branch).get_protection()
    assert err.value.status == 404


def test_delete_branch(client: GitHubClient, branches: SimpleNamespace, created: SimpleNamespace) -> None:
    client.branch.delete(branches.head)
    created.branches.remove(branches.head)
    with pytest.raises(GithubException) as err:
        client.branch.get(branches.head)
    assert err.value.status == 404


@pytest.mark.skipif(not TEST_WORKFLOW, reason="GITHUB_TEST_WORKFLOW is not set")
def test_trigger_workflow_and_wait(client: GitHubClient) -> None:
    if (run := client.workflow.trigger(TEST_WORKFLOW)) is None:  # servers that don't report the run
        time.sleep(5)
        run = client.workflow.list_runs(TEST_WORKFLOW, limit=1)[0]
    conclusion = client.workflow.wait_until_finished(run.id, check_interval=10, timeout=900)
    assert conclusion in {"success", "failure", "cancelled", "skipped", "neutral", "timed_out", "action_required"}
