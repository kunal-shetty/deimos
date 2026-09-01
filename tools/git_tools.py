import subprocess
from typing import List, Optional
from tools.base import BaseTool

class GitToolBase(BaseTool):
    """Base class for Git tools to share common execution logic."""

    def _run_git(self, args: List[str]) -> str:
        try:
            result = subprocess.run(
                ["git"] + args,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout if result.stdout else "Command executed successfully (no output)."
        except subprocess.CalledProcessError as e:
            return f"Git error: {e.stderr or e.stdout}"
        except FileNotFoundError:
            return "Error: 'git' command not found. Please ensure Git is installed."

class GitStatusTool(GitToolBase):
    """Get the current status of the git repository."""

    @property
    def name(self) -> str:
        return "git_status"

    @property
    def description(self) -> str:
        return "Show the current status of the git repository (staged, unstaged, and untracked files)."

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    def run(self, **kwargs) -> str:
        return self._run_git(["status", "--short"])

class GitAddTool(GitToolBase):
    """Stage files for commit."""

    @property
    def name(self) -> str:
        return "git_add"

    @property
    def description(self) -> str:
        return "Stage files for commit. Use '.' to stage all changes."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "string",
                    "description": "Space-separated list of paths to stage, or '.' for all"
                }
            },
            "required": ["paths"]
        }

    def run(self, paths: str) -> str:
        # Split paths by space to avoid shell injection if they were passed as a list
        # but since we use a list for subprocess.run, we just pass them.
        # However, git add usually takes paths as separate arguments.
        args = ["add"] + paths.split()
        return self._run_git(args)

class GitCommitTool(GitToolBase):
    """Commit staged changes."""

    @property
    def name(self) -> str:
        return "git_commit"

    @property
    def description(self) -> str:
        return "Commit staged changes with a descriptive message."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The commit message"
                }
            },
            "required": ["message"]
        }

    def run(self, message: str) -> str:
        return self._run_git(["commit", "-m", message])

class GitPushTool(GitToolBase):
    """Push commits to the remote repository."""

    @property
    def name(self) -> str:
        return "git_push"

    @property
    def description(self) -> str:
        return "Push local commits to the remote repository."

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    def run(self, **kwargs) -> str:
        return self._run_git(["push"])

class GitBranchTool(GitToolBase):
    """Create or switch git branches."""

    @property
    def name(self) -> str:
        return "git_branch"

    @property
    def description(self) -> str:
        return "Create a new branch, switch to an existing one, or list branches."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "switch", "list"],
                    "description": "Action to perform"
                },
                "branch_name": {
                    "type": "string",
                    "description": "The name of the branch"
                }
            },
            "required": ["action"]
        }

    def run(self, action: str, branch_name: Optional[str] = None) -> str:
        if action == "create":
            if not branch_name:
                return "Error: branch_name is required for 'create' action."
            return self._run_git(["checkout", "-b", branch_name])
        elif action == "switch":
            if not branch_name:
                return "Error: branch_name is required for 'switch' action."
            return self._run_git(["checkout", branch_name])
        elif action == "list":
            return self._run_git(["branch"])
        return "Error: Invalid action."

class GitHubPRTool(GitToolBase):
    """Manage GitHub Pull Requests using the gh CLI."""

    @property
    def name(self) -> str:
        return "github_pr"

    @property
    def description(self) -> str:
        return "Create, list, or merge GitHub pull requests using the 'gh' CLI."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "merge"],
                    "description": "Action to perform"
                },
                "title": {
                    "type": "string",
                    "description": "PR title (for create)"
                },
                "body": {
                    "type": "string",
                    "description": "PR body (for create)"
                },
                "pr_number": {
                    "type": "string",
                    "description": "PR number (for merge)"
                }
            },
            "required": ["action"]
        }

    def _run_gh(self, args: List[str]) -> str:
        try:
            result = subprocess.run(
                ["gh"] + args,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout if result.stdout else "Command executed successfully."
        except subprocess.CalledProcessError as e:
            return f"GitHub CLI error: {e.stderr or e.stdout}"
        except FileNotFoundError:
            return "Error: 'gh' (GitHub CLI) not found. Please install it to use PR features."

    def run(self, action: str, **kwargs) -> str:
        if action == "create":
            title = kwargs.get("title", "New PR")
            body = kwargs.get("body", "")
            return self._run_gh(["pr", "create", "--title", title, "--body", body])
        elif action == "list":
            return self._run_gh(["pr", "list"])
        elif action == "merge":
            pr_number = kwargs.get("pr_number")
            if not pr_number:
                return "Error: pr_number is required for 'merge' action."
            return self._run_gh(["pr", "merge", pr_number])
        return "Error: Invalid action."
