"""
Read-only integration tests against the real GitHub API. Nothing is created or changed.

Required env vars (loaded from .env):
    GITHUB_ACCESS_TOKEN     tests skip if unset

Optional env vars:
    GITHUB_BASE_URL         GitHub Enterprise Server API URL (default: https://api.github.com)
    GITHUB_TEST_READ_REPO   repo to read (default: aviz92/python-github-plus)

Run:
    uv run pytest -m integration tests/test_github_integration.py -v
"""

# pylint: disable=redefined-outer-name
import os

import pytest
from dotenv import load_dotenv
from github import GithubException

from python_github_plus import GitHubClient, GitHubPRStatus

load_dotenv()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("GITHUB_ACCESS_TOKEN"), reason="GITHUB_ACCESS_TOKEN is not set"),
]

READ_REPO = os.environ.get("GITHUB_TEST_READ_REPO", "aviz92/python-github-plus")


@pytest.fixture(scope="module")
def client() -> GitHubClient:
    github_client = GitHubClient(READ_REPO)
    github_client.is_connected(raise_if_not_connected=True)
    return github_client


def test_bad_token_is_reported_on_first_call() -> None:
    bad = GitHubClient(READ_REPO, access_token="not-a-real-token")  # no API call yet
    assert bad.is_connected() is False
    with pytest.raises(ValueError, match="authenticate"):
        bad.is_connected(raise_if_not_connected=True)


def test_repo_info(client: GitHubClient) -> None:
    info = client.project.get_info()
    assert info.full_name.lower() == READ_REPO.lower()
    assert info.default_branch


def test_fetch_content_from_default_branch(client: GitHubClient) -> None:
    assert client.file.fetch_content("README.md").strip()


def test_fetch_content_at_ref(client: GitHubClient) -> None:
    default_branch = client.project.get_info().default_branch
    assert client.file.fetch_content("README.md", ref=default_branch) == client.file.fetch_content("README.md")


def test_list_dir_and_directory_read(client: GitHubClient) -> None:
    entries = client.file.list_dir("")
    assert any(entry.path == "README.md" and entry.type == "file" for entry in entries)
    directory = next(entry.path for entry in entries if entry.type == "dir")
    with pytest.raises(ValueError, match="directory"):
        client.file.fetch_content(directory)


def test_missing_file_raises_github_exception(client: GitHubClient) -> None:
    with pytest.raises(GithubException) as err:
        client.file.fetch_content("this/file/does-not-exist.txt")
    assert err.value.status == 404


def test_branches(client: GitHubClient) -> None:
    default_branch = client.project.get_info().default_branch
    assert len(client.branch.list(limit=1)) == 1
    assert client.branch.get(default_branch).name == default_branch


def test_tags_respect_limit(client: GitHubClient) -> None:
    assert len(client.tag.list(limit=2)) <= 2


def test_workflows_and_runs(client: GitHubClient) -> None:
    if not (workflows := client.workflow.list()):
        pytest.skip(f"{READ_REPO} has no workflows")
    workflow = workflows[0]
    file_name = workflow.path.rsplit("/", 1)[-1]
    assert client.workflow.find(file_name).id == workflow.id
    assert client.workflow.find(workflow.id).id == workflow.id

    runs = client.workflow.list_runs(file_name, limit=2)
    assert len(runs) <= 2
    last = client.workflow.last_run_by_id(workflow.id)
    if runs:
        assert last is not None and last.id == runs[0].id
        assert client.workflow.get_run(last.id).id == last.id
        assert client.workflow.status(last.id)
    else:
        assert last is None


def test_unknown_workflow_lists_available(client: GitHubClient) -> None:
    with pytest.raises(ValueError, match="not found"):
        client.workflow.find("no-such-workflow.yml")


def test_pull_requests(client: GitHubClient) -> None:
    prs = client.pull_request.list(state="all", limit=3)
    assert len(prs) <= 3
    if not prs:
        pytest.skip(f"{READ_REPO} has no pull requests")
    pr = prs[0]
    assert client.pull_request.status(pr.number) in {status.value for status in GitHubPRStatus}
    files = client.pull_request.files(pr.number, limit=5)
    assert len(files) <= 5
    assert all(f.filename for f in files)


def test_for_repo_shares_connection(client: GitHubClient) -> None:
    other = client.for_repo("aviz92/python-jira-plus")
    assert other.github is client.github
    assert other.project.get_info().full_name == "aviz92/python-jira-plus"
