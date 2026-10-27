![PyPI version](https://img.shields.io/pypi/v/python-github-plus)
![Python](https://img.shields.io/badge/python->=3.12-blue)
![Development Status](https://img.shields.io/badge/status-stable-green)
![Maintenance](https://img.shields.io/maintenance/yes/2026)
![PyPI](https://img.shields.io/pypi/dm/python-github-plus)
![License](https://img.shields.io/pypi/l/python-github-plus)

---

# Python GitHub Plus
An enhanced Python client for GitHub built on [PyGithub](https://github.com/PyGithub/PyGithub): one object per repository,
grouped services, sensible defaults and errors you can act on.

---

## Features
- ✅ **Service-based architecture**: `project`, `branch`, `pull_request`, `workflow`, `tag`, `file`
- ✅ **Lazy connection**: creating a client makes no API calls; one connection serves many repositories (`for_repo`)
- ✅ **GitHub.com and GitHub Enterprise Server** (`base_url`)
- ✅ **Errors are raised, not logged and swallowed**: `GithubException` from the API, `ValueError` for bad input
- ✅ **Default branch aware**: branch, tag, PR, workflow and file calls default to the repo's real default branch
- ✅ **Bounded listing**: every list method takes `limit` and stops paging once it is reached
- ✅ **Pull requests**: list, create (body, draft), files, assign, comment, approve, merge (merge/squash/rebase), close
- ✅ **Workflows**: find by name, file name or id, trigger and get the run back, wait for completion
- ✅ **Branches and tags**: create, delete, list, protect / unprotect
- ✅ **Files**: read text files (including files over 1 MB) and list directories

---

## Installation
```bash
pip install python-github-plus
```

---

## Configuration
Pass the token directly, or set environment variables. A `.env` file is loaded only when an argument is missing.

```bash
GITHUB_ACCESS_TOKEN=your_github_access_token
GITHUB_BASE_URL=https://github.example.com/api/v3  # optional, GitHub Enterprise Server only
```

---

## Examples

### Basic Setup and Connection
```python
from python_github_plus import GitHubClient

github_client = GitHubClient(
    repo_full_name="your-repo-owner/your-repo-name",
    access_token="your_access_token",  # or GITHUB_ACCESS_TOKEN
    # base_url="https://github.example.com/api/v3",  # GitHub Enterprise Server
)

# Creating the client makes no API calls; check the token explicitly if you want to fail fast
github_client.is_connected(raise_if_not_connected=True)

# Another repository over the same connection
other_repo = github_client.for_repo("your-repo-owner/another-repo")

# Services
github_client.project
github_client.branch
github_client.pull_request
github_client.workflow
github_client.tag
github_client.file
```

### Branch Management
```python
# Create a branch from the default branch (or pass from_branch="develop")
branch_ref = github_client.branch.create(branch_name="feature/new-feature")
print(f"Created branch: {branch_ref.ref}")

# List the first 50 branches
for branch in github_client.branch.list(limit=50):
    print(f"Branch: {branch.name}")

# Protect a branch: 2 approvals, code owners, required CI check
github_client.branch.protect(
    "main",
    required_approving_review_count=2,
    require_code_owner_reviews=True,
    require_status_checks=True,
    status_check_contexts=["CI"],
)

# Delete a branch
github_client.branch.delete("feature/old-feature")
```

### Pull Request Management
```python
# Open a draft PR into the default branch
pr = github_client.pull_request.create(
    title="Add new feature",
    from_branch="feature/new-feature",
    body="What changed and why",
    draft=True,
)
print(f"Created PR: #{pr.number}")

# List open PRs into main, and the files a PR changes
for open_pr in github_client.pull_request.list(state="open", base="main", limit=20):
    print(f"#{open_pr.number} {open_pr.title}")
for changed in github_client.pull_request.files(pr.number):
    print(f"{changed.status}: {changed.filename} (+{changed.additions}/-{changed.deletions})")

github_client.pull_request.assign(pr.number, ["username"])
github_client.pull_request.add_comment(pr.number, "Great work!")
github_client.pull_request.approve(pr.number)

# Merge; raises ValueError if GitHub did not merge it
merge_sha = github_client.pull_request.merge(pr.number, merge_method="squash")
```

### Workflow Operations
```python
# Find a workflow by display name, file name or id, and trigger it on the default branch
run = github_client.workflow.trigger("ci.yml", inputs={"debug": "true"})

# github.com returns the new run; on servers that don't, take the newest run instead
if run is None:
    run = github_client.workflow.list_runs("ci.yml", limit=1)[0]

print(f"Run {run.id}: {github_client.workflow.status(run.id)}")

# Poll until the run completes (raises TimeoutError after `timeout` seconds)
conclusion = github_client.workflow.wait_until_finished(run_id=run.id, check_interval=30, timeout=3600)
print(f"Workflow run finished: {conclusion}")
```

### File Operations
```python
# Read a file from the default branch (or pass ref="v1.0.0")
content = github_client.file.fetch_content("README.md")
print(content[:100])

# List a directory
for entry in github_client.file.list_dir("python_github_plus"):
    print(f"{entry.type}: {entry.path}")
```

### Tag Management
```python
# Annotated tag on the head of the default branch, or on a specific commit
tag = github_client.tag.create(tag_name="v1.0.0", message="Release version 1.0.0")
github_client.tag.create_from_sha(tag_name="v1.0.1", sha="abc123...", message="Hotfix")

for repo_tag in github_client.tag.list(limit=10):
    print(f"Tag: {repo_tag.name}")

github_client.tag.delete("v0.9.0")
```

### Project Management
```python
project_info = github_client.project.get_info()
print(f"Project: {project_info.full_name} (default branch: {project_info.default_branch})")

for member in github_client.project.list_members(limit=100):
    print(f"Member: {member.login}")

github_client.project.add_member("newuser", permission="push")  # pull, triage, push, maintain or admin
github_client.project.remove_member("olduser")
```

---

## Upgrading from 1.x
See [CHANGELOG.md](CHANGELOG.md). In short: errors now raise, defaults follow the repo's default branch,
`workflow.trigger` returns the run, and `pull_request.merge` returns the merge commit sha.

---

## 🤝 Contributing
If you have a helpful tool, pattern, or improvement to suggest:
Fork the repo <br>
Create a new branch <br>
Submit a pull request <br>
I welcome additions that promote clean, productive, and maintainable development. <br>

---

## 🙏 Thanks
Thanks for exploring this repository! <br>
Happy coding! <br>
