import builtins
import os
import time
from enum import Enum

from custom_python_logger import get_logger
from github import Auth, Github, GithubException
from github.Branch import Branch
from github.ContentFile import ContentFile
from github.GitRef import GitRef
from github.GitTag import GitTag
from github.PullRequest import PullRequest
from github.Repository import Repository
from github.Tag import Tag
from github.Workflow import Workflow
from github.WorkflowRun import WorkflowRun


class GitHubPRStatus(Enum):
    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"


class GitHubWorkflowStatus(Enum):
    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"
    QUEUED = "queued"


class GitHubProjectService:
    def __init__(self, repo: Repository) -> None:
        self.logger = get_logger(self.__class__.__name__)
        self.repo = repo

    def get_info(self) -> Repository:
        return self.repo

    def list_members(self) -> list:
        return list(self.repo.get_collaborators())

    def add_member(self, username: str, permission: str = "push") -> None:
        try:
            self.repo.add_to_collaborators(username, permission)
            self.logger.info(f"✅ Added member '{username}' with '{permission}' permission.")
        except GithubException as e:
            self.logger.error(f"❌ Failed to add member {username}: {e}")

    def remove_member(self, username: str) -> None:
        try:
            self.repo.remove_from_collaborators(username)
            self.logger.info(f"✅ Removed member '{username}'.")
        except GithubException as e:
            self.logger.error(f"❌ Failed to remove member {username}: {e}")


class GitHubWorkflowService:
    def __init__(self, repo: Repository) -> None:
        self.logger = get_logger(self.__class__.__name__)
        self.repo = repo

    def list(self) -> list[Workflow]:
        """List workflows configured in the repo (.github/workflows)."""
        return list(self.repo.get_workflows())

    def trigger(self, workflow_name: str, branch_name: str = "main", inputs: dict | None = None) -> Workflow:
        """
        Dispatch a workflow by name on a given branch.
        Requires 'workflow_dispatch' defined in the workflow YAML.
        """
        workflows = {wf.name: wf for wf in self.repo.get_workflows()}
        if workflow_name not in workflows:
            raise ValueError(f"❌ Workflow '{workflow_name}' not found.")

        workflow = workflows[workflow_name]
        workflow.create_dispatch(ref=branch_name, inputs=inputs or {})
        self.logger.info(f"🚀 Triggered workflow '{workflow_name}' on branch '{branch_name}'")

        # Note: This returns immediately; to track status, use wait_until_finished
        return workflow

    def get_workflow_by_id(self, workflow_id: int) -> Workflow:
        return self.repo.get_workflow(workflow_id)

    def list_runs(self, workflow_name: str, branch: str | None = None) -> builtins.list[WorkflowRun]:
        workflows = {wf.name: wf for wf in self.repo.get_workflows()}
        if workflow_name not in workflows:
            raise ValueError(f"❌ Workflow '{workflow_name}' not found.")

        runs = workflows[workflow_name].get_runs(branch=branch) if branch else workflows[workflow_name].get_runs()
        return list(runs)

    def last_run_by_id(self, workflow_id: int) -> WorkflowRun:
        return self.repo.get_workflow(workflow_id).get_runs()[0]

    def status(self, run_id: int) -> str:
        """Get the current status of a workflow run. run_id is the ID of the run, not the workflow."""
        run = self.repo.get_workflow_run(run_id)
        return run.status  # "queued", "in_progress", "completed"

    def conclusion(self, run_id: int) -> str | None:
        """
        Get the conclusion of a completed workflow run.
        None if still running. run_id is the ID of the run, not the workflow.
        """
        run = self.repo.get_workflow_run(run_id)
        return run.conclusion  # "success", "failure", "cancelled", None if still running

    def wait_until_finished(self, run_id: int, check_interval: int = 10, timeout: int = 10) -> str:
        start_time = time.time()
        while (time.time() - start_time) >= timeout:  # pylint: disable=W0149
            run = self.repo.get_workflow_run(run_id)
            if run.status == "completed":
                self.logger.info(f"✅ Workflow run {run_id} finished with conclusion = {run.conclusion}")
                return run.conclusion
            self.logger.debug(f"⏳ Workflow run {run_id} still {run.status}...")
            time.sleep(check_interval)
        raise TimeoutError(f"⏰ Workflow run {run_id} did not complete within {timeout} seconds.")


class GitHubBranchService:
    def __init__(self, repo: Repository) -> None:
        self.logger = get_logger(self.__class__.__name__)
        self.repo = repo

    def create(self, branch_name: str, from_branch: str) -> GitRef:
        ref = self.repo.get_git_ref(f"heads/{from_branch}")
        new_ref = self.repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=ref.object.sha)
        self.logger.info(f"✅ Branch '{branch_name}' created from '{from_branch}'")
        return new_ref

    def delete(self, branch_name: str) -> None:
        ref = self.repo.get_git_ref(f"heads/{branch_name}")
        ref.delete()
        self.logger.info(f"✅ Branch '{branch_name}' deleted")

    def list(self) -> list[Branch]:
        return list(self.repo.get_branches())

    def protect(
        self,
        branch_name: str,
        enforce_admins: bool = True,
        require_pull_request_reviews: bool = True,
        dismiss_stale_reviews: bool = True,
        required_approving_review_count: int = 1,
        require_status_checks: bool = False,
        status_check_contexts: builtins.list[str] | None = None,
    ) -> None:
        """
        Protect a branch with common settings.
        """
        branch = self.repo.get_branch(branch_name)
        branch.edit_protection(
            required_approving_review_count=required_approving_review_count,
            enforce_admins=enforce_admins,
            dismiss_stale_reviews=dismiss_stale_reviews,
            require_code_owner_reviews=require_pull_request_reviews,
            contexts=status_check_contexts if require_status_checks else None,
        )
        self.logger.info(f"✅ Branch '{branch_name}' protected")

    def unprotect(self, branch_name: str) -> None:
        branch = self.repo.get_branch(branch_name)
        branch.remove_protection()
        self.logger.info(f"✅ Branch '{branch_name}' unprotected")


class GitHubTagService:
    def __init__(self, repo: Repository) -> None:
        self.logger = get_logger(self.__class__.__name__)
        self.repo = repo

    def create_from_sha(self, tag_name: str, sha: str, message: str | None = None) -> GitTag:
        tag = self.repo.create_git_tag(tag=tag_name, message=message or tag_name, object="main", type="commit")
        self.repo.create_git_ref(ref=f"refs/tags/{tag_name}", sha=tag.sha)
        self.logger.info(f"✅ Tag '{tag_name}' created at commit {sha}")
        return tag

    def create(self, tag_name: str, from_branch: str, message: str | None = None) -> GitTag:
        branch = self.repo.get_branch(from_branch)
        sha = branch.commit.sha
        return self.create_from_sha(tag_name=tag_name, sha=sha, message=message)

    def delete(self, tag_name: str) -> None:
        ref = self.repo.get_git_ref(f"tags/{tag_name}")
        ref.delete()
        self.logger.info(f"✅ Tag '{tag_name}' deleted")

    def list(self) -> list[Tag]:
        return list(self.repo.get_tags())


class GitHubPRService:
    def __init__(self, repo: Repository) -> None:
        self.logger = get_logger(self.__class__.__name__)
        self.repo = repo

    def get_info(self, number: int) -> PullRequest:
        return self.repo.get_pull(number)

    def create(self, title: str, from_branch: str, target: str) -> PullRequest:
        pr = self.repo.create_pull(title=title, head=from_branch, base=target)
        self.logger.info(f"✅ PR '{title}' created: #{pr.number}")
        return pr

    def assign(self, pr_number: int, assignees: str) -> None:
        issue = self.repo.get_issue(pr_number)  # fetch the same PR as an issue
        issue.add_to_assignees(assignees)  # or multiple users
        self.logger.info(f"✅ PR #{pr_number} assigned to {assignees}")

    def status(self, number: int) -> str:
        pr = self.repo.get_pull(number)
        if pr.merged:
            return GitHubPRStatus.MERGED.value
        return pr.state

    def merge(self, number: int) -> None:
        pr = self.repo.get_pull(number)
        pr.merge()
        self.logger.info(f"✅ PR #{number} merged.")

    def close(self, number: int) -> None:
        pr = self.repo.get_pull(number)
        pr.edit(state="closed")
        self.logger.info(f"✅ PR #{number} closed.")

    def reopen(self, number: int) -> None:
        pr = self.repo.get_pull(number)
        pr.edit(state="open")
        self.logger.info(f"✅ PR #{number} reopened.")

    def add_comment(self, number: int, comment: str) -> None:
        pr = self.repo.get_pull(number)
        pr.create_issue_comment(comment)
        self.logger.info(f"✅ Comment added to PR #{number}.")

    def approve(self, number: int, body: str = "LGTM ✅") -> None:
        pr = self.repo.get_pull(number)
        pr.create_review(event="APPROVE", body=body)
        self.logger.info(f"✅ PR #{number} approved.")


class GitHubFileService:
    def __init__(self, repo: Repository) -> None:
        self.logger = get_logger(self.__class__.__name__)
        self.repo = repo

    def get(self, path: str, ref: str = "main") -> ContentFile:
        return self.repo.get_contents(path, ref=ref)

    def fetch_content(self, file_path: str, ref: str = "main") -> str:
        file = self.repo.get_contents(file_path, ref=ref)
        return file.decoded_content.decode("utf-8")

    # def update(self, path: str, branch: str, content: str, message: str) -> None:
    #     file = self.repo.get_contents(path, ref=branch)
    #     self.repo.update_file(path, message, content, file.sha, branch=branch)
    #     self.logger.info(f"✅ File '{path}' updated on branch '{branch}'")
    #
    # def create(self, path: str, branch: str, content: str, message: str) -> None:
    #     self.repo.create_file(path, message, content, branch=branch)
    #     self.logger.info(f"✅ File '{path}' created on branch '{branch}'")
    #
    # def delete(self, path: str, branch: str, message: str) -> None:
    #     file = self.repo.get_contents(path, ref=branch)
    #     self.repo.delete_file(path, message, file.sha, branch=branch)
    #     self.logger.info(f"✅ File '{path}' deleted on branch '{branch}'")


# ----------------------- #
# Facade / User Interface #
# ----------------------- #


class GitHubClient:
    def __init__(self, access_token: str | None, repo_full_name: str) -> None:
        self.logger = get_logger(self.__class__.__name__)
        self.github_access_token = access_token or os.environ.get("GITHUB_ACCESS_TOKEN")

        self.github = Github(auth=Auth.Token(self.github_access_token))
        self.is_connected(raise_if_not_connected=True)

        repo = self.github.get_repo(repo_full_name)
        self.project = GitHubProjectService(repo)
        self.workflow = GitHubWorkflowService(repo)
        self.branch = GitHubBranchService(repo)
        self.tag = GitHubTagService(repo)
        self.pull_request = GitHubPRService(repo)
        self.file = GitHubFileService(repo)

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
