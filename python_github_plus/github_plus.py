import base64
import builtins
import os
import time
from collections.abc import Iterable
from enum import Enum
from itertools import islice
from typing import TypeVar, get_args

from custom_python_logger import get_logger
from dotenv import load_dotenv
from github import Auth, Github
from github.Branch import Branch
from github.ContentFile import ContentFile
from github.File import File
from github.GithubObject import NotSet
from github.GitRef import GitRef
from github.GitTag import GitTag
from github.NamedUser import NamedUser
from github.PullRequest import PullRequest
from github.Repository import Repository
from github.Tag import Tag
from github.Workflow import Workflow
from github.WorkflowRun import WorkflowRun

from python_github_plus.consts import DEFAULT_BASE_URL, LOGGER_NAME, MergeMethod, PRState

T = TypeVar("T")


class GitHubPRStatus(Enum):
    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"


class GitHubWorkflowStatus(Enum):
    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"
    QUEUED = "queued"


def _take(items: Iterable[T], limit: int | None = None) -> list[T]:
    """Materialize at most `limit` items. PyGithub fetches pages lazily, so a limit stops paging early."""
    if limit is None:
        return list(items)
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}")
    return list(islice(items, limit))


def _delete_ref(repo: Repository, ref: str) -> None:
    """
    Delete a git ref. A lazy GitRef carries the read URL (`git/ref/...`), but DELETE lives at `git/refs/...`,
    so fetch it first: that sets the canonical URL, and a missing ref raises 404 here.
    """
    git_ref = repo.get_git_ref(ref)
    git_ref.complete()
    git_ref.delete()


class _RepoService:
    def __init__(self, repo: Repository) -> None:
        self.logger = get_logger(LOGGER_NAME)
        self.repo = repo

    def _ref_or_default(self, ref: str | None) -> str:
        return ref or self.repo.default_branch


class GitHubProjectService(_RepoService):
    def get_info(self) -> Repository:
        return self.repo

    def list_members(self, limit: int | None = None) -> list[NamedUser]:
        return _take(self.repo.get_collaborators(), limit)

    def add_member(self, username: str, permission: str = "push") -> None:
        self.repo.add_to_collaborators(username, permission)
        self.logger.info(f"✅ Added member '{username}' with '{permission}' permission.")

    def remove_member(self, username: str) -> None:
        self.repo.remove_from_collaborators(username)
        self.logger.info(f"✅ Removed member '{username}'.")


class GitHubWorkflowService(_RepoService):
    def list(self) -> list[Workflow]:
        """List workflows configured in the repo (.github/workflows)."""
        return list(self.repo.get_workflows())

    def find(self, workflow: str | int) -> Workflow:
        """Find a workflow by display name, file name (`ci.yml`), path or id. Names fall back to case-insensitive."""
        key = str(workflow)
        workflows = self.list()
        matchers = (
            lambda wf: wf.name == key,
            lambda wf: key in {wf.path, os.path.basename(wf.path)},
            lambda wf: str(wf.id) == key,
            lambda wf: wf.name.casefold() == key.casefold(),
        )
        for matches in matchers:
            found = [wf for wf in workflows if matches(wf)]
            if len(found) == 1:
                return found[0]
            if len(found) > 1:
                raise ValueError(f"❌ Workflow '{key}' is ambiguous: {[wf.path for wf in found]}")
        available = [f"{wf.name} ({os.path.basename(wf.path)})" for wf in workflows]
        raise ValueError(f"❌ Workflow '{key}' not found. Available: {available}")

    def trigger(
        self, workflow_name: str | int, branch_name: str | None = None, inputs: dict | None = None
    ) -> WorkflowRun | None:
        """
        Dispatch a workflow on a branch (the repo's default branch if not given).
        Requires 'workflow_dispatch' in the workflow YAML. Raises GithubException if GitHub rejects the dispatch.

        Returns the created run when GitHub reports it (github.com does); otherwise None,
        and the run can be found with list_runs.
        """
        workflow = self.find(workflow_name)
        branch_name = self._ref_or_default(branch_name)
        result = workflow.create_dispatch(ref=branch_name, inputs=inputs or {}, throw=True, return_run_details=True)
        self.logger.info(f"🚀 Triggered workflow '{workflow.name}' on branch '{branch_name}'")
        return result if isinstance(result, WorkflowRun) else None

    def get_workflow_by_id(self, workflow_id: int) -> Workflow:
        return self.repo.get_workflow(workflow_id)

    def list_runs(
        self, workflow_name: str | int, branch: str | None = None, limit: int | None = None
    ) -> builtins.list[WorkflowRun]:
        """Runs of a workflow, newest first."""
        workflow = self.find(workflow_name)
        runs = workflow.get_runs(branch=branch) if branch else workflow.get_runs()
        return _take(runs, limit)

    def get_run(self, run_id: int) -> WorkflowRun:
        return self.repo.get_workflow_run(run_id)

    def last_run_by_id(self, workflow_id: int) -> WorkflowRun | None:
        """The newest run of a workflow, or None if it never ran."""
        return next(iter(self.repo.get_workflow(workflow_id).get_runs()), None)

    def status(self, run_id: int) -> str:
        """Get the current status of a workflow run. run_id is the ID of the run, not the workflow."""
        return self.get_run(run_id).status  # "queued", "in_progress", "completed"

    def conclusion(self, run_id: int) -> str | None:
        """
        Get the conclusion of a completed workflow run.
        None if still running. run_id is the ID of the run, not the workflow.
        """
        return self.get_run(run_id).conclusion  # "success", "failure", "cancelled", None if still running

    def wait_until_finished(self, run_id: int, check_interval: float = 10, timeout: float = 600) -> str | None:
        """Poll a run until it completes and return its conclusion. Raises TimeoutError after `timeout` seconds."""
        if check_interval < 0 or timeout < 0:
            raise ValueError("check_interval and timeout must not be negative")
        deadline = time.monotonic() + timeout
        while True:  # pylint: disable=W0149
            run = self.get_run(run_id)
            if run.status == GitHubWorkflowStatus.COMPLETED.value:
                self.logger.info(f"✅ Workflow run {run_id} finished with conclusion = {run.conclusion}")
                return run.conclusion
            if (remaining := deadline - time.monotonic()) <= 0:
                raise TimeoutError(f"⏰ Workflow run {run_id} did not complete within {timeout} seconds.")
            self.logger.debug(f"⏳ Workflow run {run_id} still {run.status}...")
            time.sleep(min(check_interval, remaining))


class GitHubBranchService(_RepoService):
    def get(self, branch_name: str) -> Branch:
        return self.repo.get_branch(branch_name)

    def create(self, branch_name: str, from_branch: str | None = None) -> GitRef:
        """Create a branch from another branch (the repo's default branch if not given)."""
        from_branch = self._ref_or_default(from_branch)
        ref = self.repo.get_git_ref(f"heads/{from_branch}")
        new_ref = self.repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=ref.object.sha)
        self.logger.info(f"✅ Branch '{branch_name}' created from '{from_branch}'")
        return new_ref

    def delete(self, branch_name: str) -> None:
        _delete_ref(self.repo, f"heads/{branch_name}")
        self.logger.info(f"✅ Branch '{branch_name}' deleted")

    def list(self, limit: int | None = None) -> list[Branch]:
        return _take(self.repo.get_branches(), limit)

    def protect(
        self,
        branch_name: str,
        enforce_admins: bool = True,
        require_pull_request_reviews: bool = True,
        dismiss_stale_reviews: bool = True,
        required_approving_review_count: int = 1,
        require_code_owner_reviews: bool = False,
        require_status_checks: bool = False,
        status_check_contexts: builtins.list[str] | None = None,
        strict_status_checks: bool = False,
    ) -> None:
        """
        Protect a branch with common settings.
        Review settings apply only when `require_pull_request_reviews` is True,
        status check settings only when `require_status_checks` is True.
        """
        kwargs: dict = {"enforce_admins": enforce_admins}
        if require_pull_request_reviews:
            kwargs |= {
                "dismiss_stale_reviews": dismiss_stale_reviews,
                "required_approving_review_count": required_approving_review_count,
                "require_code_owner_reviews": require_code_owner_reviews,
            }
        if require_status_checks:
            kwargs |= {"contexts": status_check_contexts or [], "strict": strict_status_checks}
        self.get(branch_name).edit_protection(**kwargs)
        self.logger.info(f"✅ Branch '{branch_name}' protected")

    def unprotect(self, branch_name: str) -> None:
        self.get(branch_name).remove_protection()
        self.logger.info(f"✅ Branch '{branch_name}' unprotected")


class GitHubTagService(_RepoService):
    def create_from_sha(self, tag_name: str, sha: str, message: str | None = None) -> GitTag:
        """Create an annotated tag pointing at a commit."""
        tag = self.repo.create_git_tag(tag=tag_name, message=message or tag_name, object=sha, type="commit")
        self.repo.create_git_ref(ref=f"refs/tags/{tag_name}", sha=tag.sha)
        self.logger.info(f"✅ Tag '{tag_name}' created at commit {sha}")
        return tag

    def create(self, tag_name: str, from_branch: str | None = None, message: str | None = None) -> GitTag:
        """Tag the head of a branch (the repo's default branch if not given)."""
        sha = self.repo.get_branch(self._ref_or_default(from_branch)).commit.sha
        return self.create_from_sha(tag_name=tag_name, sha=sha, message=message)

    def delete(self, tag_name: str) -> None:
        _delete_ref(self.repo, f"tags/{tag_name}")
        self.logger.info(f"✅ Tag '{tag_name}' deleted")

    def list(self, limit: int | None = None) -> list[Tag]:
        return _take(self.repo.get_tags(), limit)


class GitHubPRService(_RepoService):
    def get_info(self, number: int) -> PullRequest:
        return self.repo.get_pull(number)

    def list(
        self,
        state: PRState = "open",
        base: str | None = None,
        head: str | None = None,
        limit: int | None = None,
    ) -> list[PullRequest]:
        """Pull requests, newest first. `head` is `owner:branch`, as the GitHub API expects."""
        pulls = self.repo.get_pulls(state=state, base=base or NotSet, head=head or NotSet)
        return _take(pulls, limit)

    def files(self, number: int, limit: int | None = None) -> builtins.list[File]:
        """Files changed by a pull request, with their patches."""
        return _take(self.repo.get_pull(number).get_files(), limit)

    def create(
        self, title: str, from_branch: str, target: str | None = None, body: str = "", draft: bool = False
    ) -> PullRequest:
        """Open a pull request into `target` (the repo's default branch if not given)."""
        pr = self.repo.create_pull(
            title=title, head=from_branch, base=self._ref_or_default(target), body=body, draft=draft
        )
        self.logger.info(f"✅ PR '{title}' created: #{pr.number}")
        return pr

    def assign(self, pr_number: int, assignees: str | builtins.list[str]) -> None:
        names = [assignees] if isinstance(assignees, str) else assignees
        self.repo.get_issue(pr_number).add_to_assignees(*names)  # a PR is also an issue
        self.logger.info(f"✅ PR #{pr_number} assigned to {names}")

    def status(self, number: int) -> str:
        pr = self.repo.get_pull(number)
        if pr.merged:
            return GitHubPRStatus.MERGED.value
        return pr.state

    def merge(
        self,
        number: int,
        merge_method: MergeMethod = "merge",
        commit_title: str | None = None,
        commit_message: str | None = None,
    ) -> str:
        """Merge a pull request and return the merge commit sha. Raises ValueError if GitHub did not merge it."""
        if merge_method not in get_args(MergeMethod):
            raise ValueError(f"merge_method must be one of {get_args(MergeMethod)}, got '{merge_method}'")
        result = self.repo.get_pull(number).merge(
            merge_method=merge_method, commit_title=commit_title or NotSet, commit_message=commit_message or NotSet
        )
        if not result.merged:
            raise ValueError(f"❌ PR #{number} was not merged: {result.message}")
        self.logger.info(f"✅ PR #{number} merged ({merge_method}).")
        return result.sha

    def close(self, number: int) -> None:
        self.repo.get_pull(number).edit(state="closed")
        self.logger.info(f"✅ PR #{number} closed.")

    def reopen(self, number: int) -> None:
        self.repo.get_pull(number).edit(state="open")
        self.logger.info(f"✅ PR #{number} reopened.")

    def add_comment(self, number: int, comment: str) -> None:
        self.repo.get_pull(number).create_issue_comment(comment)
        self.logger.info(f"✅ Comment added to PR #{number}.")

    def approve(self, number: int, body: str = "LGTM ✅") -> None:
        self.repo.get_pull(number).create_review(event="APPROVE", body=body)
        self.logger.info(f"✅ PR #{number} approved.")


class GitHubFileService(_RepoService):
    def get(self, path: str, ref: str | None = None) -> ContentFile | list[ContentFile]:
        """A file, or a directory listing. `ref` defaults to the repo's default branch."""
        return self.repo.get_contents(path, ref=ref or NotSet)

    def list_dir(self, path: str = "", ref: str | None = None) -> list[ContentFile]:
        contents = self.get(path, ref)
        if not isinstance(contents, list):
            raise ValueError(f"❌ '{path}' is a file, not a directory; use fetch_content")
        return contents

    def fetch_content(self, file_path: str, ref: str | None = None) -> str:
        """Text content of a file, decoded as UTF-8. Files over 1 MB are read through the git blob API."""
        file = self.get(file_path, ref)
        if isinstance(file, list):
            raise ValueError(f"❌ '{file_path}' is a directory; use list_dir")
        if file.encoding == "base64":
            return file.decoded_content.decode("utf-8")
        blob = self.repo.get_git_blob(file.sha)  # the contents API omits content for files over 1 MB
        return base64.b64decode(blob.content).decode("utf-8")


# ----------------------- #
# Facade / User Interface #
# ----------------------- #


class GitHubClient:
    """
    A client for one repository. Construction makes no API calls: the repo is fetched on first use.

    Use `for_repo` to work with more repositories over the same connection.
    A `github` instance passed in is used as is; create it with `lazy=True` to keep construction free of API calls.
    """

    def __init__(
        self,
        repo_full_name: str,
        access_token: str | None = None,
        base_url: str | None = None,
        github: Github | None = None,
    ) -> None:
        self.logger = get_logger(LOGGER_NAME)
        owner, _, name = repo_full_name.partition("/")
        if not owner or not name or "/" in name:
            raise ValueError(f"repo_full_name must be 'owner/name', got '{repo_full_name}'")

        self.repo_full_name = repo_full_name
        self.github = github or self._connect(access_token, base_url)

        repo = self.github.get_repo(repo_full_name)
        self.project = GitHubProjectService(repo)
        self.workflow = GitHubWorkflowService(repo)
        self.branch = GitHubBranchService(repo)
        self.tag = GitHubTagService(repo)
        self.pull_request = GitHubPRService(repo)
        self.file = GitHubFileService(repo)

    @staticmethod
    def _connect(access_token: str | None, base_url: str | None) -> Github:
        if not access_token or not base_url:
            load_dotenv()
        if not (token := access_token or os.environ.get("GITHUB_ACCESS_TOKEN")):
            raise ValueError("A GitHub token is required: pass access_token or set GITHUB_ACCESS_TOKEN")
        url = base_url or os.environ.get("GITHUB_BASE_URL") or DEFAULT_BASE_URL
        if "://" not in url:
            url = f"https://{url}"
        # lazy: objects (the repo included) are fetched on first use, and every repo shares this requester
        return Github(auth=Auth.Token(token), base_url=url.rstrip("/"), lazy=True)

    def for_repo(self, repo_full_name: str) -> "GitHubClient":
        """A client for another repository, sharing this client's connection."""
        return GitHubClient(repo_full_name, github=self.github)

    def is_connected(self, raise_if_not_connected: bool = False) -> bool:
        try:
            user = self.github.get_user().login
            self.logger.info(f"✅ Successfully connected to GitHub as {user}")
            return True
        except Exception as e:
            msg = f"❌ Failed to authenticate with GitHub: {e}"
            if raise_if_not_connected:
                raise ValueError(msg) from e
            self.logger.exception(msg)
            return False
