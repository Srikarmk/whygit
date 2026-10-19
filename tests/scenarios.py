"""Builds real repository states in a temporary folder with the real git binary.

Each builder takes a Sandbox and returns the folder to diagnose."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

MB = 1024 * 1024


class Sandbox:
    def __init__(self, root: Path):
        self.root = root
        self.home = root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.gitconfig = root / "gitconfig"
        self.gitconfig.write_text(
            "[init]\n\tdefaultBranch = main\n"
            "[commit]\n\tgpgsign = false\n"
            "[core]\n\tautocrlf = false\n"
            "[advice]\n\tdetachedHead = true\n"
            '[protocol "file"]\n\tallow = always\n'
        )

    # environment applied by the pytest fixture
    def env(self) -> dict[str, str]:
        return {
            "HOME": str(self.home),
            "USERPROFILE": str(self.home),
            "GIT_CONFIG_GLOBAL": str(self.gitconfig),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CEILING_DIRECTORIES": str(self.root),
            "GIT_EDITOR": "true",
            "GIT_SEQUENCE_EDITOR": "true",
            "GIT_MERGE_AUTOEDIT": "no",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
            "LANGUAGE": "C",
        }

    def git(self, cwd: Path, *args: str, check: bool = True, env: dict | None = None) -> subprocess.CompletedProcess:
        e = dict(os.environ)
        e.update(self.env())
        if env:
            e.update(env)
        p = subprocess.run(["git", *args], cwd=str(cwd), env=e, capture_output=True, text=True)
        if check and p.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed in {cwd}:\n{p.stdout}\n{p.stderr}")
        return p

    def out(self, cwd: Path, *args: str, **kw) -> str:
        """Run git expecting failure or noise; return stdout+stderr as a user would see it."""
        p = self.git(cwd, *args, check=False, **kw)
        return p.stdout + p.stderr

    def init(self, path: Path, identity: bool = True) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        self.git(path, "init", "-q")
        if identity:
            self.ident(path)
        return path

    def ident(self, path: Path) -> None:
        self.git(path, "config", "user.name", "Test Student")
        self.git(path, "config", "user.email", "student@example.com")

    def write(self, repo: Path, files: dict[str, str | bytes]) -> None:
        for name, content in files.items():
            f = repo / name
            f.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                f.write_bytes(content)
            else:
                f.write_text(content)

    def commit(self, repo: Path, files: dict[str, str | bytes], msg: str = "change") -> None:
        self.write(repo, files)
        self.git(repo, "add", *files.keys())
        self.git(repo, "commit", "-q", "-m", msg)

    def bare(self, name: str = "remote.git") -> Path:
        p = self.root / name
        self.git(self.root, "init", "-q", "--bare", str(p))
        return p

    def clone(self, remote: Path, name: str) -> Path:
        dest = self.home / name
        self.git(self.root, "clone", "-q", str(remote), str(dest))
        self.ident(dest)
        return dest

    def published(self, name: str = "proj") -> tuple[Path, Path]:
        """A repository with one commit pushed to a local bare remote, upstream set."""
        remote = self.bare(f"{name}-remote.git")
        repo = self.init(self.home / name)
        self.commit(repo, {"analysis.py": "print('hello')\n"}, "first")
        self.git(repo, "remote", "add", "origin", str(remote))
        self.git(repo, "push", "-q", "-u", "origin", "main")
        return repo, remote


def conflict_pair(
    sb: Sandbox, repo: Path, name: str = "analysis.py", ours: str = "ours\n", theirs: str = "theirs\n"
) -> None:
    sb.commit(repo, {name: "base\n"}, "base")
    sb.git(repo, "switch", "-q", "-c", "other")
    sb.commit(repo, {name: theirs}, "theirs")
    sb.git(repo, "switch", "-q", "main")
    sb.commit(repo, {name: ours}, "ours")


def notebook(cells: list[str], extra: str = "") -> str:
    nb = {
        "cells": [
            {"cell_type": "code", "metadata": {}, "source": [c], "outputs": [], "execution_count": None} for c in cells
        ],
        "metadata": {"note": extra},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    return json.dumps(nb, indent=1) + "\n"


# ---------------------------------------------------------------- scenarios


def clean(sb: Sandbox) -> Path:
    repo, _ = sb.published()
    # Make the index stale on purpose so a normal `git status` would rewrite it.
    f = repo / "analysis.py"
    st = f.stat()
    os.utime(f, (st.st_atime + 5, st.st_mtime + 5))
    return repo


def not_repo(sb: Sandbox) -> Path:
    d = sb.home / "Documents" / "notes"
    d.mkdir(parents=True)
    return d


def parent_of_clone(sb: Sandbox) -> Path:
    course = sb.home / "ds3500"
    sb.init(course / "hw1")
    return course


def at_home(sb: Sandbox) -> Path:
    return sb.home


def home_repo(sb: Sandbox) -> Path:
    sb.init(sb.home)
    d = sb.home / "Documents" / "ds3500"
    d.mkdir(parents=True)
    (d / "hw.py").write_text("x = 1\n")
    return d


def home_repo_outer(sb: Sandbox) -> Path:
    sb.init(sb.home)
    repo = sb.init(sb.home / "projects" / "hw2")
    sb.commit(repo, {"a.py": "a = 1\n"})
    return repo


def inside_git_dir(sb: Sandbox) -> Path:
    repo = sb.init(sb.home / "proj")
    return repo / ".git"


def bare_repo(sb: Sandbox) -> Path:
    return sb.bare("server.git")


def unborn(sb: Sandbox) -> Path:
    repo = sb.init(sb.home / "fresh")
    (repo / "README.md").write_text("hi\n")
    return repo


def merge_conflict(sb: Sandbox) -> Path:
    repo = sb.init(sb.home / "proj")
    conflict_pair(sb, repo)
    sb.git(repo, "merge", "other", check=False)
    return repo


def merge_resolved(sb: Sandbox) -> Path:
    repo = merge_conflict(sb)
    (repo / "analysis.py").write_text("both\n")
    sb.git(repo, "add", "analysis.py")
    return repo


def merge_resolved_markers(sb: Sandbox) -> Path:
    repo = merge_conflict(sb)
    sb.git(repo, "add", "analysis.py")  # still has markers
    return repo


def notebook_conflict(sb: Sandbox) -> Path:
    repo = sb.init(sb.home / "proj")
    conflict_pair(sb, repo, "eda.ipynb", notebook(["df.head()"], "ours"), notebook(["df.describe()"], "theirs"))
    sb.git(repo, "merge", "other", check=False)
    return repo


def rebase_conflict(sb: Sandbox) -> Path:
    repo = sb.init(sb.home / "proj")
    conflict_pair(sb, repo)
    sb.git(repo, "switch", "-q", "other")
    sb.git(repo, "rebase", "main", check=False)
    return repo


def rebase_edit(sb: Sandbox) -> Path:
    repo = sb.init(sb.home / "proj")
    for i in range(3):
        sb.commit(repo, {"f.txt": "line\n" * (i + 1)}, f"c{i}")
    sb.git(repo, "rebase", "-i", "HEAD~2", env={"GIT_SEQUENCE_EDITOR": "sed -i.bak 1s/^pick/edit/"})
    return repo


def cherry_pick_conflict(sb: Sandbox) -> Path:
    repo = sb.init(sb.home / "proj")
    conflict_pair(sb, repo)
    sb.git(repo, "cherry-pick", "other", check=False)
    return repo


def revert_conflict(sb: Sandbox) -> Path:
    repo = sb.init(sb.home / "proj")
    sb.commit(repo, {"f.txt": "a\n"}, "a")
    sb.commit(repo, {"f.txt": "b\n"}, "b")
    sb.commit(repo, {"f.txt": "c\n"}, "c")
    sb.git(repo, "revert", "--no-edit", "HEAD~1", check=False)
    return repo


def bisect(sb: Sandbox) -> Path:
    repo = sb.init(sb.home / "proj")
    for i in range(4):
        sb.commit(repo, {"f.txt": f"{i}\n"}, f"c{i}")
    sb.git(repo, "bisect", "start")
    sb.git(repo, "bisect", "bad")
    sb.git(repo, "bisect", "good", "HEAD~3")
    return repo


def am_conflict(sb: Sandbox) -> Path:
    repo = sb.init(sb.home / "proj")
    sb.commit(repo, {"f.txt": "a\n"}, "a")
    sb.commit(repo, {"f.txt": "b\n"}, "b")
    patches = sb.root / "patches"
    sb.git(repo, "format-patch", "-q", "-1", "HEAD", "-o", str(patches))
    sb.git(repo, "reset", "-q", "--hard", "HEAD~1")
    sb.commit(repo, {"f.txt": "zzz\n"}, "z")
    patch = sorted(patches.iterdir())[0]
    sb.git(repo, "am", str(patch), check=False)
    return repo


def detached_clean(sb: Sandbox) -> Path:
    repo = sb.init(sb.home / "proj")
    sb.commit(repo, {"f.txt": "a\n"}, "a")
    sb.commit(repo, {"f.txt": "b\n"}, "b")
    sb.git(repo, "checkout", "-q", "HEAD~1")
    return repo


def detached_orphans(sb: Sandbox) -> Path:
    repo = sb.init(sb.home / "proj")
    sb.commit(repo, {"f.txt": "a\n"}, "a")
    sb.git(repo, "checkout", "-q", "--detach")
    sb.commit(repo, {"f.txt": "lost work\n"}, "work on no branch")
    return repo


def _two_clones(sb: Sandbox) -> tuple[Path, Path, Path]:
    repo, remote = sb.published("proj")
    other = sb.clone(remote, "proj-laptop")
    return repo, other, remote


def behind(sb: Sandbox) -> Path:
    repo, other, _ = _two_clones(sb)
    sb.commit(other, {"analysis.py": "print('v2')\n"}, "v2")
    sb.git(other, "push", "-q")
    sb.git(repo, "fetch", "-q")
    return repo


def ahead(sb: Sandbox) -> Path:
    repo, _ = sb.published()
    sb.commit(repo, {"new.py": "x = 1\n"}, "local")
    return repo


def diverged(sb: Sandbox) -> Path:
    repo, other, _ = _two_clones(sb)
    sb.commit(other, {"other.py": "y = 2\n"}, "from laptop")
    sb.git(other, "push", "-q")
    sb.commit(repo, {"mine.py": "z = 3\n"}, "mine")
    sb.git(repo, "fetch", "-q")
    return repo


def no_upstream(sb: Sandbox) -> Path:
    repo, _ = sb.published()
    sb.git(repo, "switch", "-q", "-c", "feature")
    sb.commit(repo, {"feature.py": "f = 1\n"}, "feature")
    return repo


def no_remote(sb: Sandbox) -> Path:
    repo = sb.init(sb.home / "local-only")
    sb.commit(repo, {"a.py": "a = 1\n"})
    return repo


def upstream_gone(sb: Sandbox) -> Path:
    repo, other, _ = _two_clones(sb)
    sb.git(repo, "switch", "-q", "-c", "feature")
    sb.commit(repo, {"feature.py": "f = 1\n"}, "feature")
    sb.git(repo, "push", "-q", "-u", "origin", "feature")
    sb.git(other, "push", "-q", "origin", "--delete", "feature")
    sb.git(repo, "fetch", "-q", "--prune")
    return repo


def nested_untracked(sb: Sandbox) -> Path:
    repo = sb.init(sb.home / "proj")
    sb.commit(repo, {"a.py": "a = 1\n"})
    inner = sb.init(repo / "starter-code")
    sb.commit(inner, {"main.py": "pass\n"})
    return repo


def nested_gitlink(sb: Sandbox) -> Path:
    repo = nested_untracked(sb)
    sb.git(repo, "add", "starter-code")
    return repo


def nested_outer(sb: Sandbox) -> Path:
    outer = sb.init(sb.home / "course")
    sb.commit(outer, {"syllabus.md": "x\n"})
    inner = sb.init(outer / "hw3")
    sb.commit(inner, {"hw.py": "x\n"})
    return inner


def large_staged(sb: Sandbox) -> Path:
    repo, _ = sb.published()
    with open(repo / "big.csv", "wb") as fh:
        fh.truncate(101 * MB)
    with open(repo / "medium.csv", "wb") as fh:
        fh.truncate(60 * MB)
    sb.git(repo, "add", "big.csv", "medium.csv")
    return repo


def large_unpushed(sb: Sandbox) -> Path:
    repo, _ = sb.published()
    with open(repo / "data.parquet", "wb") as fh:
        fh.truncate(55 * MB)
    sb.git(repo, "add", "data.parquet")
    sb.git(repo, "commit", "-q", "-m", "add data")
    return repo


def secret_staged(sb: Sandbox) -> Path:
    repo, _ = sb.published()
    sb.write(repo, {".env": "API_KEY=abc\n", ".env.example": "API_KEY=\n", "keys/id_rsa": "-----BEGIN-----\n"})
    sb.git(repo, "add", ".env", ".env.example", "keys/id_rsa")
    return repo


def secret_unpushed(sb: Sandbox) -> Path:
    repo, _ = sb.published()
    sb.commit(repo, {"kaggle.json": '{"username":"x","key":"y"}\n'}, "add kaggle")
    return repo


def notebook_outputs(sb: Sandbox) -> Path:
    repo, _ = sb.published()
    sb.write(repo, {"eda.ipynb": notebook(["df"], "x" * (1200 * 1024))})
    sb.git(repo, "add", "eda.ipynb")
    return repo


def missing_identity(sb: Sandbox) -> Path:
    repo = sb.init(sb.home / "proj", identity=False)
    return repo


def index_lock(sb: Sandbox) -> Path:
    repo, _ = sb.published()
    (repo / ".git" / "index.lock").write_text("")
    return repo


def dubious(sb: Sandbox) -> Path:
    repo, _ = sb.published()
    return repo


# Scenario name -> (builder, rule ids that must fire, extra environment for gitwhy)
SCENARIOS: dict[str, tuple] = {
    "clean": (clean, set(), {}),
    "not_repo": (not_repo, {"not_a_repo"}, {}),
    "parent_of_clone": (parent_of_clone, {"not_a_repo"}, {}),
    "at_home": (at_home, {"not_a_repo"}, {}),
    "home_repo": (home_repo, {"home_repo"}, {}),
    "home_repo_outer": (home_repo_outer, {"home_repo"}, {}),
    "inside_git_dir": (inside_git_dir, {"inside_git_dir"}, {}),
    "bare_repo": (bare_repo, {"bare_repo"}, {}),
    "unborn": (unborn, {"unborn_branch"}, {}),
    "merge_conflict": (merge_conflict, {"merge_conflict"}, {}),
    "merge_resolved": (merge_resolved, {"merge_resolved"}, {}),
    "merge_resolved_markers": (merge_resolved_markers, {"merge_resolved"}, {}),
    "notebook_conflict": (notebook_conflict, {"merge_conflict", "notebook_conflict"}, {}),
    "rebase_conflict": (rebase_conflict, {"rebase_in_progress"}, {}),
    "rebase_edit": (rebase_edit, {"rebase_in_progress"}, {}),
    "cherry_pick_conflict": (cherry_pick_conflict, {"cherry_pick_in_progress"}, {}),
    "revert_conflict": (revert_conflict, {"revert_in_progress"}, {}),
    "bisect": (bisect, {"bisect_in_progress"}, {}),
    "am_conflict": (am_conflict, {"am_in_progress"}, {}),
    "detached_clean": (detached_clean, {"detached_head"}, {}),
    "detached_orphans": (detached_orphans, {"detached_head"}, {}),
    "behind": (behind, {"behind"}, {}),
    "ahead": (ahead, {"ahead"}, {}),
    "diverged": (diverged, {"diverged"}, {}),
    "no_upstream": (no_upstream, {"no_upstream"}, {}),
    "no_remote": (no_remote, {"no_remote"}, {}),
    "upstream_gone": (upstream_gone, {"upstream_gone"}, {}),
    "nested_untracked": (nested_untracked, {"nested_repo"}, {}),
    "nested_gitlink": (nested_gitlink, {"nested_repo"}, {}),
    "nested_outer": (nested_outer, {"nested_repo"}, {}),
    "large_staged": (large_staged, {"large_file_over_limit", "large_file_warning"}, {}),
    "large_unpushed": (large_unpushed, {"large_file_warning", "ahead"}, {}),
    "secret_staged": (secret_staged, {"secret_staged"}, {}),
    "secret_unpushed": (secret_unpushed, {"secret_staged", "ahead"}, {}),
    "notebook_outputs": (notebook_outputs, {"notebook_outputs"}, {}),
    "missing_identity": (missing_identity, {"missing_identity", "unborn_branch"}, {}),
    "index_lock": (index_lock, {"index_lock"}, {}),
    "dubious": (dubious, {"dubious_ownership"}, {"GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"}),
}
