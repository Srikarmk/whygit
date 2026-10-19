"""The engine must never change a repository."""

import ast
import hashlib
import os
import subprocess
from pathlib import Path

import pytest
from scenarios import SCENARIOS

from gitwhy import engine
from gitwhy.gitcmd import GitRefused, check_allowed, run_git

SRC = Path(__file__).resolve().parent.parent / "src" / "gitwhy"


def snapshot(root: Path) -> dict:
    """Every file under root: size, mtime, and a content hash (sampled for big files)."""
    snap = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for d in dirnames:
            p = Path(dirpath, d)
            snap[p.relative_to(root).as_posix() + "/"] = p.stat().st_mtime_ns
        for name in filenames:
            p = Path(dirpath, name)
            st = p.stat()
            if st.st_size <= 4 * 1024 * 1024:
                digest = hashlib.sha256(p.read_bytes()).hexdigest()
            else:
                with open(p, "rb") as fh:
                    digest = hashlib.sha256(fh.read(65536)).hexdigest()
            snap[p.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns, digest)
    return snap


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_diagnosing_changes_nothing(build, sandbox, name):
    path = build(name)
    before = snapshot(sandbox.root)
    engine.diagnose(path)
    engine.explain_state(path)
    engine.explain_error("error: failed to push some refs to 'origin'", path)
    engine.explain_error("something gitwhy has never seen", path)
    after = snapshot(sandbox.root)
    assert before == after


def test_stale_index_would_be_rewritten_by_plain_status(build, sandbox):
    """Control: shows the snapshot can see an index refresh, so the test above means something."""
    repo = build("clean")
    before = snapshot(repo)
    engine.diagnose(repo)
    assert snapshot(repo) == before
    sandbox.git(repo, "status")
    assert snapshot(repo)[".git/index"] != before[".git/index"]


@pytest.mark.parametrize(
    "args",
    [
        ("commit", "-m", "x"),
        ("push",),
        ("fetch",),
        ("pull",),
        ("reset", "--hard"),
        ("checkout", "--", "."),
        ("clean", "-fd"),
        ("add", "."),
        ("stash",),
        ("gc",),
        ("merge", "--abort"),
        ("update-ref", "-d", "HEAD"),
        ("config", "user.name", "x"),
        ("config", "--unset", "user.name"),
        ("config", "--add", "x.y", "z"),
        ("config", "--global", "user.name", "x"),
        ("remote", "add", "origin", "x"),
        ("remote", "set-url", "origin", "x"),
        ("remote", "prune", "origin"),
        ("remote", "update"),
        ("worktree", "add", "x"),
        ("worktree", "prune"),
        ("symbolic-ref", "HEAD", "refs/heads/x"),
        ("symbolic-ref", "-d", "HEAD"),
        ("diff", "--output=x.txt"),
        ("log", "--output", "x.txt"),
        ("-c", "core.editor=x", "status"),
        ("--git-dir=/tmp/x", "status"),
        (),
    ],
)
def test_allowlist_refuses_mutating_commands(args, tmp_path):
    with pytest.raises(GitRefused):
        check_allowed(args)
    with pytest.raises(GitRefused):
        run_git(tmp_path, *args)


def test_allowlist_accepts_reads():
    for args in (
        ("status", "--porcelain=v2"),
        ("config", "--get", "user.name"),
        ("remote", "-v"),
        ("worktree", "list", "--porcelain"),
        ("symbolic-ref", "-q", "HEAD"),
        ("rev-list", "--count", "HEAD"),
    ):
        check_allowed(args)


def test_optional_locks_disabled(sandbox, tmp_path):
    from gitwhy.gitcmd import _env

    assert _env()["GIT_OPTIONAL_LOCKS"] == "0"


SPAWNERS = {
    "system",
    "popen",
    "spawnl",
    "spawnv",
    "spawnve",
    "spawnlp",
    "execv",
    "execve",
    "execvp",
    "startfile",
    "posix_spawn",
}
WRITERS = {
    "write_text",
    "write_bytes",
    "unlink",
    "rmtree",
    "mkdir",
    "makedirs",
    "touch",
    "rmdir",
    "chmod",
    "symlink_to",
    "truncate",
    "copyfile",
    "copytree",
    "move",
}
OS_WRITERS = {"remove", "rename", "replace", "utime", "link", "symlink"}


def _modules():
    for p in sorted(SRC.glob("*.py")):
        yield p, ast.parse(p.read_text(), filename=str(p))


def test_only_run_git_starts_processes():
    offenders = []
    calls_in_gitcmd = []
    for path, tree in _modules():
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] + (
                    [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
                )
                if (
                    any(n and n.split(".")[0] in ("subprocess", "pty", "multiprocessing") for n in names)
                    and path.name != "gitcmd.py"
                ):
                    offenders.append(f"{path.name}:{node.lineno} imports a process module")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                base = node.func.value
                base_name = base.id if isinstance(base, ast.Name) else ""
                if base_name == "subprocess":
                    calls_in_gitcmd.append((path.name, node.lineno))
                if base_name in ("os", "asyncio") and (
                    node.func.attr in SPAWNERS or node.func.attr.startswith("create_subprocess")
                ):
                    offenders.append(f"{path.name}:{node.lineno} os.{node.func.attr}")
    assert not offenders, offenders
    assert [c[0] for c in calls_in_gitcmd] == ["gitcmd.py"], calls_in_gitcmd
    # And that single call lives inside run_git.
    tree = ast.parse((SRC / "gitcmd.py").read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_git")
    inside = [
        n.lineno
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and getattr(n.func.value, "id", "") == "subprocess"
    ]
    assert inside == [calls_in_gitcmd[0][1]]


def test_source_never_writes_files():
    offenders = []
    for path, tree in _modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                base = getattr(getattr(f, "value", None), "id", "")
                if isinstance(f, ast.Attribute) and (
                    f.attr in WRITERS or (base in ("os", "shutil") and f.attr in OS_WRITERS)
                ):
                    offenders.append(f"{path.name}:{node.lineno} .{f.attr}()")
                if isinstance(f, ast.Name) and f.id == "open":
                    mode = (
                        node.args[1]
                        if len(node.args) > 1
                        else next((k.value for k in node.keywords if k.arg == "mode"), None)
                    )
                    if mode is not None and not (isinstance(mode, ast.Constant) and set(str(mode.value)) <= set("rbt")):
                        offenders.append(f"{path.name}:{node.lineno} open() with mode {ast.dump(mode)}")
    assert not offenders, offenders


def test_suggested_commands_are_never_run(build, monkeypatch):
    """Every git call made while diagnosing every scenario is on the allowlist."""
    import gitwhy.gitcmd as g

    seen = []
    real = subprocess.run

    def spy(cmd, *a, **kw):
        seen.append(cmd)
        return real(cmd, *a, **kw)

    path = build("merge_conflict")
    monkeypatch.setattr(g.subprocess, "run", spy)
    engine.diagnose(path)
    engine.explain_state(path)
    assert seen
    for cmd in seen:
        assert cmd[0] == "git"
        sub = next(c for c in cmd[1:] if not c.startswith("-") and "=" not in c)
        assert sub in g.ALLOWED_SUBCOMMANDS, cmd
