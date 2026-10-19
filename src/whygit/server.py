"""MCP server front end (stdio). Three read-only tools over the same engine as the CLI."""

from __future__ import annotations

import os
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import __version__, engine
from .engine import PathNotFound

INSTRUCTIONS = (
    "whygit explains the state of a local Git repository in plain English and suggests fixes. "
    "It only reads; it never changes the repository and never runs the commands it suggests. "
    "Use diagnose_repo when something seems wrong, explain_git_error when you have git or GitHub error text, "
    "and explain_state for a neutral summary. Ahead/behind counts are as of the last fetch; it does not contact GitHub."
)

mcp = MCPServer("whygit", instructions=INSTRUCTIONS, version=__version__)

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

PathArg = Annotated[
    str,
    Field(
        description="Repository folder (or any folder inside it). Relative paths resolve against the server's working directory; ~ is allowed."
    ),
]


def _missing(path: str) -> ToolError:
    return ToolError(
        f"The folder '{path}' does not exist (relative paths resolve against the server's working directory, "
        f"{os.getcwd()}). Pass the absolute path of the repository root, the folder that contains .git."
    )


@mcp.tool(title="Diagnose a Git repository", annotations=READ_ONLY)
def diagnose_repo(path: PathArg = ".") -> dict[str, Any]:
    """Use when a repository seems stuck or broken: lists every problem found (conflicts, rebase in progress, detached HEAD, diverged branch, large or secret files...), most urgent first, each with a plain explanation and the commands for the user to run."""
    try:
        return engine.diagnose(path)
    except PathNotFound:
        raise _missing(path) from None


@mcp.tool(title="Explain a Git error message", annotations=READ_ONLY)
def explain_git_error(
    error_text: Annotated[
        str, Field(description="The error output from git or GitHub, pasted verbatim.", min_length=1, max_length=50000)
    ],
    path: Annotated[
        str | None, Field(description="Optional repository folder; when given, the explanation uses its current state.")
    ] = None,
) -> dict[str, Any]:
    """Use when a git command printed an error (push rejected, authentication failed, unrelated histories, merge conflict...): says what it means and the fix. Pass path to tailor the fix to the repository."""
    try:
        return engine.explain_error(error_text, path)
    except PathNotFound:
        raise _missing(path or "") from None


@mcp.tool(title="Summarise a Git repository's state", annotations=READ_ONLY)
def explain_state(path: PathArg = ".") -> dict[str, Any]:
    """Use for a neutral plain-English summary of a repository: branch, upstream and ahead/behind (as of the last fetch), remotes, staged/changed/untracked files, and any operation in progress."""
    try:
        return engine.explain_state(path)
    except PathNotFound:
        raise _missing(path) from None


def main() -> None:
    mcp.run()
