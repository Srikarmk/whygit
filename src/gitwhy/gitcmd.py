"""The only place gitwhy starts a process. Every git call goes through run_git,
which accepts read-only subcommands and refuses everything else."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Subcommands that only read. Some need their arguments checked as well,
# because the same subcommand can also write (config, remote, symbolic-ref...).
ALLOWED_SUBCOMMANDS = frozenset(
    {
        "status",
        "rev-parse",
        "symbolic-ref",
        "for-each-ref",
        "rev-list",
        "config",
        "ls-files",
        "ls-tree",
        "diff",
        "log",
        "remote",
        "worktree",
        "cat-file",
        "show-ref",
        "merge-base",
        "version",
    }
)

_CONFIG_READ_MODES = {"--get", "--get-all", "--get-regexp", "--list", "-l"}
_CONFIG_OK_FLAGS = _CONFIG_READ_MODES | {
    "--local",
    "--global",
    "--system",
    "--show-origin",
    "--show-scope",
    "--null",
    "-z",
    "--name-only",
    "--includes",
    "--no-includes",
    "--bool",
    "--int",
    "--path",
}
_FORBIDDEN_ANYWHERE = ("--output", "--ext-diff", "--exec", "--upload-pack", "--receive-pack")

TIMEOUT_SECONDS = 20


class GitRefused(Exception):
    """Raised when a caller asks run_git for something that is not read-only."""


class GitNotFound(Exception):
    """Raised when no git executable can be started."""


@dataclass
class GitResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def check_allowed(args: tuple[str, ...]) -> None:
    if not args:
        raise GitRefused("no git subcommand given")
    sub, rest = args[0], args[1:]
    if sub.startswith("-"):
        raise GitRefused(f"global git options are not accepted: {sub}")
    if sub not in ALLOWED_SUBCOMMANDS:
        raise GitRefused(f"'git {sub}' is not on the read-only allowlist")
    for a in rest:
        if a.split("=", 1)[0] in _FORBIDDEN_ANYWHERE:
            raise GitRefused(f"option {a} is not allowed")
    if sub == "config":
        flags = [a for a in rest if a.startswith("-")]
        if not any(f in _CONFIG_READ_MODES for f in flags):
            raise GitRefused("git config is only allowed with --get, --get-all, --get-regexp or --list")
        for f in flags:
            if f.split("=", 1)[0] not in _CONFIG_OK_FLAGS and not f.startswith("--type="):
                raise GitRefused(f"git config option {f} is not allowed")
    elif sub == "remote":
        if list(rest) not in ([], ["-v"], ["--verbose"]):
            raise GitRefused("git remote is only allowed as 'git remote' or 'git remote -v'")
    elif sub == "worktree":
        if not rest or rest[0] != "list" or any(a not in ("--porcelain", "-z", "list") for a in rest):
            raise GitRefused("git worktree is only allowed as 'git worktree list'")
    elif sub == "symbolic-ref":
        positional = [a for a in rest if not a.startswith("-")]
        bad = [a for a in rest if a.startswith("-") and a not in ("-q", "--quiet", "--short")]
        if len(positional) > 1 or bad:
            raise GitRefused("git symbolic-ref is only allowed to read a ref")
    elif sub == "cat-file":
        if any(a in ("--filters", "--textconv") for a in rest):
            raise GitRefused("cat-file filters are not allowed")


def _env() -> dict[str, str]:
    env = dict(os.environ)
    # Never let an ambient repository setting redirect us somewhere else.
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE"):
        env.pop(k, None)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_PAGER"] = "cat"
    env["LC_ALL"] = "C"
    env["LANGUAGE"] = "C"
    return env


# Global options added to every call: no pager, and no fsmonitor hook, so a
# repository's own config cannot make gitwhy run another program.
_GLOBAL_OPTS = ("--no-pager", "-c", "core.fsmonitor=false", "-c", "core.quotePath=false")


def run_git(cwd: str | Path, *args: str, input_text: str | None = None, timeout: float = TIMEOUT_SECONDS) -> GitResult:
    check_allowed(tuple(args))
    args = tuple(args)
    if args[0] in ("diff", "log"):
        # No external diff programs or text conversion filters.
        args = (args[0], "--no-ext-diff", "--no-textconv", *args[1:])
    cmd = ["git", *_GLOBAL_OPTS, *args]
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=_env(),
            input=input_text.encode("utf-8") if input_text is not None else None,
            stdin=None if input_text is not None else subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            check=False,
            **kwargs,
        )
    except FileNotFoundError as exc:
        raise GitNotFound(str(exc)) from exc
    except subprocess.TimeoutExpired:
        return GitResult(tuple(args), 124, "", "timed out")
    return GitResult(
        tuple(args),
        proc.returncode,
        proc.stdout.decode("utf-8", errors="replace"),
        proc.stderr.decode("utf-8", errors="replace"),
    )


# Redaction of credentials in URLs and well-known token formats.
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/@\s'\"]+@")
_TOKENS = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_\-]{20,})\b")


def redact(text: str) -> str:
    if not text:
        return text
    text = _URL_USERINFO.sub(r"\1***@", text)
    return _TOKENS.sub("***", text)


def redact_obj(obj):
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, list):
        return [redact_obj(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(redact_obj(x) for x in obj)
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    return obj
