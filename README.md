# Python GitHub Plus
An enhanced Python client for GitHub that extends the functionality of the official `pygithub` package, providing better error handling, merge request management, branch operations, and more.

---

## Features
- ✅ Simplified connection to GitHub instances
- ✅ Robust error handling with comprehensive logging
- ✅ **Service-based architecture** for organized functionality
- ✅ **Project management** (members, info, etc.)
- ✅ **Branch operations** (create, delete, protect, list, etc.)
- ✅ **Pull Request management** (create, merge, approve, assign, comment, etc.)
- ✅ **Workflow operations** (trigger, monitor, wait for completion, etc.)
- ✅ **Tag management** (create, delete, list, etc.)
- ✅ **File operations** (read, create, update, delete, etc.)

---

## Installation
```bash
pip install python-github-plus
```

---

## Configuration
The package uses environment variables for authentication and configuration:

```bash
# Required environment variables
GitHub_ACCESS_TOKEN=your_github_access_token
GitHub_URL=https://github.com  # Your GitHub instance URL (default: github.com)
```

## Examples

### Basic Setup and Connection
```python
from python_github_plus import GitHubClient

# Initialize GitLab client with service-based architecture
github_client = GitHubClient(
    access_token="your_access_token",  # Note: parameter name changed
    repo_full_name="your-repo-owner/your-repo-name",
)

# Access different services
project_service = github_client.project
branch_service = github_client.branch
pr_service = github_client.pull_request
workflows_service = github_client.workflows
tag_service = github_client.tag
file_service = github_client.file
```

### Branch Management
```python
from python_github_plus import GitHubClient

github_client = GitHubClient(
    access_token="your_access_token",  # Note: parameter name changed
    repo_full_name="your-repo-owner/your-repo-name",
)

# Create a new branch
branch = github_client.branch.create(
    branch_name="feature/new-feature",
    from_branch="main"
)
print(f"Created branch: {branch.ref}")

# List branches
branches = github_client.branch.list()
for branch in branches:
    print(f"Branch: {branch.name}")

# Protect a branch
github_client.branch.protect("main")

# Delete a branch
github_client.branch.delete("feature/old-feature")
```

### Pull Request Management
```python
from python_github_plus import GitHubClient

github_client = GitHubClient(
    access_token="your_access_token",  # Note: parameter name changed
    repo_full_name="your-repo-owner/your-repo-name",
)

# Create a pull request
pr = github_client.pull_request.create(
    title="Add new feature",
    from_branch="feature/new-feature",
    target="main"
)
print(f"Created PR: !{pr.number}")

# Assign PR to a user
github_client.pull_request.assign(pr.number, "username")

# Add a comment
github_client.pull_request.add_comment(pr.number, "Great work!")

# Approve the PR
github_client.pull_request.approve(pr.number)

# Merge the PR
github_client.pull_request.merge(pr.number)
```

### Workflow Operations

```python
import time
from python_github_plus import GitHubClient

github_client = GitHubClient(
    access_token="your_access_token",  # Note: parameter name changed
    repo_full_name="your-repo-owner/your-repo-name",
)

# Trigger a workflows
workflows = github_client.workflow.trigger(
    workflow_name="CI",
    branch_name="main",
)
print(f"Workflow triggered: {workflows.id}")

time.sleep(5)  # wait a bit for the workflow to register
run_id = github_client.workflow.last_run_by_id(workflow_id=workflows.id)

# Check workflow run status
status = github_client.workflow.status(run_id=run_id.id)
print(f"Workflow run status: {status}")

# Wait for workflows completion
final_status = github_client.workflow.wait_until_finished(
    run_id=run_id.id,
    check_interval=30,
    timeout=3600
)
print(f"Workflow run completed with status: {final_status}")
```

### File Operations
```python
from python_github_plus import GitHubClient

github_client = GitHubClient(
    access_token="your_access_token",  # Note: parameter name changed
    repo_full_name="your-repo-owner/your-repo-name",
)

# Read file content
file_content = github_client.file.fetch_content(
    file_path="README.md",
    ref="main"
)
print(f"File content: {file_content[:100]}...")
```

### Tag Management
```python
from python_github_plus import GitHubClient

github_client = GitHubClient(
    access_token="your_access_token",  # Note: parameter name changed
    repo_full_name="your-repo-owner/your-repo-name",
)

# Create a tag
tag = github_client.tag.create(
    tag_name="v1.0.0",
    from_branch="main",
    message="Release version 1.0.0"
)
print(f"Created tag: {tag.name}")

# List tags
tags = github_client.tag.list()
for tag in tags:
    print(f"Tag: {tag.name}")

# Delete a tag
github_client.tag.delete("v0.9.0")
```

### Project Management
```python
from python_github_plus import GitHubClient

github_client = GitHubClient(
    access_token="your_access_token",  # Note: parameter name changed
    repo_full_name="your-repo-owner/your-repo-name",
)

# Get project information
project_info = github_client.project.get_info()
print(f"Project: {project_info.name}")
print(f"Description: {project_info.description}")

# List project members
members = github_client.project.list_members()
for member in members:
    print(f"Member: {member.username}")

# Add a member
github_client.project.add_member("newuser", 30)  # 30 = Developer access level

# Remove a member
github_client.project.remove_member("olduser")
```

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
