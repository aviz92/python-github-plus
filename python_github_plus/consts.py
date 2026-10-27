from typing import Literal

LOGGER_NAME = "python_github_plus"

DEFAULT_BASE_URL = "https://api.github.com"
MergeMethod = Literal["merge", "squash", "rebase"]
PRState = Literal["open", "closed", "all"]
