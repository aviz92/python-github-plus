# Changelog

## 2.0.0

### Breaking changes
- Errors are raised instead of logged and swallowed: `project.add_member` and `project.remove_member`
  raise `GithubException`; `workflow.trigger` raises when GitHub rejects the dispatch (it used to report success).
- Calls that defaulted to `"main"` now default to the repository's actual default branch:
  `branch.create(from_branch)`, `tag.create(from_branch)`, `pull_request.create(target)`, `workflow.trigger(branch_name)`,
  and `file.get` / `file.fetch_content(ref)`.
- `GitHubClient()` makes no API calls: the token and repository are checked on first use.
  Call `is_connected(raise_if_not_connected=True)` to fail fast. A malformed `repo_full_name` raises `ValueError` immediately.
- A missing token raises `ValueError` (it was a bare `AssertionError` from PyGithub).
- `workflow.trigger` returns the created `WorkflowRun` (or `None` when GitHub does not report it) instead of the `Workflow`.
- `pull_request.merge` returns the merge commit sha and raises `ValueError` when GitHub did not merge.
- `workflow.last_run_by_id` returns `None` for a workflow that never ran (it raised `IndexError`).
- `workflow.wait_until_finished` defaults to `timeout=600` (was 10 seconds).
- `branch.protect`: code owner review is now its own `require_code_owner_reviews` option (default `False`).
  `require_pull_request_reviews` used to be sent as code owner review.
- `.env` is no longer loaded on import, only when the token or base URL is not passed to `GitHubClient`.
- `pytest`, `pre-commit`, `setuptools` and `wheel` moved from runtime dependencies to the `dev` dependency group.
  Requires `pygithub>=2.10.0`.

### Added
- `GitHubClient(base_url=...)` / `GITHUB_BASE_URL` for GitHub Enterprise Server.
- `GitHubClient.for_repo(repo_full_name)`: a client for another repository over the same connection.
  The client's `Github` instance is created with `lazy=True`, so every repo shares one requester.
  A `github` instance you pass in is used as is (create it with `lazy=True` for call-free construction).
- `limit` on `branch.list`, `tag.list`, `project.list_members` and `workflow.list_runs`; paging stops once it is reached.
- `pull_request.list(state, base, head, limit)` and `pull_request.files(number, limit)`.
- `pull_request.create(body=..., draft=...)`; `pull_request.merge(merge_method, commit_title, commit_message)`.
- `pull_request.assign` accepts a list of users.
- `workflow.find(name_or_file_or_id)` and `workflow.get_run(run_id)`.
- `branch.get(branch_name)`; `branch.protect(strict_status_checks=...)`.
- `file.list_dir(path, ref)`.
- Tests: mocked unit tests, read-only integration tests against a real repo, and write integration tests
  against a sandbox repo (`pytest -m integration`; see `env.template` for `GITHUB_TEST_REPO`).

### Fixed
- `workflow.wait_until_finished` never polled and always raised `TimeoutError` (inverted loop condition).
- `tag.create_from_sha` / `tag.create` ignored the commit sha and sent `"main"` as the tag object, which GitHub rejects.
- `branch.protect(require_pull_request_reviews=False)` still required one approving review.
- Workflows can be found by file name (`ci.yml`), path or id, not only by exact display name.
- `file.fetch_content` on a directory raised `AttributeError`; it now raises `ValueError` pointing to `list_dir`.
- `file.fetch_content` reads files over 1 MB through the git blob API.
- README: `github_client.workflows` → `workflow`, `member.username` → `member.login`, and the GitLab-style
  access level in `add_member`; `env.template` named `GITLAB_ACCESS_TOKEN`.
