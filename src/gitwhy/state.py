"""Collects a read-only snapshot of a repository's state."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from .gitcmd import GitNotFound, redact, run_git

MB = 1024 * 1024
GITHUB_HARD_LIMIT = 100 * MB
GITHUB_WARN_LIMIT = 50 * MB
NOTEBOOK_WARN_SIZE = 1 * MB


class PathNotFound(Exception):
    pass


@dataclass
class Entry:
    path: str
    xy: str  # two status letters: index then worktree, e.g. "M." or "UU"
    kind: str  # "changed", "renamed", "unmerged", "untracked"
    mode_index: str = ""
    orig_path: str = ""

    @property
    def staged(self) -> bool:
        return self.kind in ("changed", "renamed") and self.xy[0] != "."

    @property
    def unstaged(self) -> bool:
        return self.kind in ("changed", "renamed") and self.xy[1] != "."


@dataclass
class BigFile:
    path: str
    size: int
    where: str  # "staged" or "unpushed"


@dataclass
class RepoState:
    path: Path
    home: Path
    git_available: bool = True
    git_version: str = ""
    is_repo: bool = False
    not_repo_reason: str = ""  # "not_found", "dubious", "inside_git_dir", "bare", "other"
    error_text: str = ""
    toplevel: Path | None = None
    git_dir: Path | None = None
    common_dir: Path | None = None
    branch: str | None = None
    head_oid: str | None = None
    unborn: bool = False
    detached: bool = False
    upstream: str | None = None
    upstream_gone: bool = False
    ahead: int | None = None
    behind: int | None = None
    last_fetch: float | None = None
    remotes: dict[str, str] = field(default_factory=dict)
    local_branches: list[str] = field(default_factory=list)
    remote_branches: list[str] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)
    in_progress: list[str] = field(default_factory=list)
    rebase_head_name: str = ""
    rebase_onto: str = ""
    rebase_step: str = ""
    rebase_edit_stop: bool = False
    leftover_markers: list[str] = field(default_factory=list)
    user_name: str | None = None
    user_email: str | None = None
    index_lock: bool = False
    orphan_commits: int = 0
    nested_repos: list[str] = field(default_factory=list)
    unregistered_gitlinks: list[str] = field(default_factory=list)
    outer_repo: Path | None = None
    big_files: list[BigFile] = field(default_factory=list)
    sensitive: list[BigFile] = field(default_factory=list)
    big_notebooks: list[BigFile] = field(default_factory=list)
    last_commit: str = ""
    stash_count: int = 0
    gitmodules: set[str] = field(default_factory=set)

    @property
    def unmerged(self) -> list[Entry]:
        return [e for e in self.entries if e.kind == "unmerged"]

    @property
    def staged(self) -> list[Entry]:
        return [e for e in self.entries if e.staged]

    @property
    def unstaged(self) -> list[Entry]:
        return [e for e in self.entries if e.unstaged]

    @property
    def untracked(self) -> list[Entry]:
        return [e for e in self.entries if e.kind == "untracked"]

    @property
    def home_is_repo_root(self) -> bool:
        return self.toplevel is not None and same_path(self.toplevel, self.home)

    def fetch_note(self) -> str:
        if self.last_fetch is None:
            return "This is as of when you cloned or last fetched. Run `git fetch` to check GitHub again."
        return f"This is as of your last fetch ({ago(self.last_fetch)}). Run `git fetch` to check GitHub again."


def same_path(a: Path, b: Path) -> bool:
    try:
        return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))
    except OSError:
        return False


def is_under(child: Path, parent: Path) -> bool:
    try:
        c = os.path.normcase(str(child.resolve()))
        p = os.path.normcase(str(parent.resolve()))
    except OSError:
        return False
    return c == p or c.startswith(p.rstrip(os.sep) + os.sep)


def ago(ts: float) -> str:
    secs = max(0, int(time.time() - ts))
    if secs < 90:
        return "just now"
    mins = secs // 60
    if mins < 90:
        return f"{mins} minutes ago"
    hours = mins // 60
    if hours < 36:
        return f"{hours} hours ago"
    return f"{hours // 24} days ago"


def resolve_path(path: str | os.PathLike | None, base: Path | None = None) -> Path:
    raw = str(path) if path not in (None, "") else "."
    p = Path(os.path.expanduser(raw))
    if not p.is_absolute():
        p = (base or Path.cwd()) / p
    try:
        p = p.resolve()
    except OSError:
        pass
    if not p.exists():
        raise PathNotFound(str(p))
    if p.is_file():
        p = p.parent
    return p


def _lines0(text: str) -> list[str]:
    return [t for t in text.split("\0") if t]


def collect(path: str | os.PathLike | None = None, deep: bool = True) -> RepoState:
    p = resolve_path(path)
    st = RepoState(path=p, home=Path.home())
    try:
        v = run_git(p, "version")
    except GitNotFound:
        st.git_available = False
        return st
    st.git_version = v.stdout.strip()

    r = run_git(p, "rev-parse", "--is-inside-git-dir", "--is-bare-repository", "--git-dir", "--git-common-dir")
    if not r.ok:
        st.error_text = redact(r.stderr.strip())
        low = r.stderr.lower()
        if "dubious ownership" in low:
            st.not_repo_reason = "dubious"
        elif "not a git repository" in low:
            st.not_repo_reason = "not_found"
        else:
            st.not_repo_reason = "other"
        return st
    inside_git_dir, is_bare, git_dir, common_dir = (r.stdout.splitlines() + ["", "", "", ""])[:4]
    st.git_dir = (p / git_dir).resolve()
    st.common_dir = (p / common_dir).resolve()
    if is_bare == "true":
        st.not_repo_reason = "bare"
        return st
    if inside_git_dir == "true":
        st.not_repo_reason = "inside_git_dir"
        return st
    top = run_git(p, "rev-parse", "--show-toplevel")
    if not top.ok:
        st.not_repo_reason = "other"
        st.error_text = redact(top.stderr.strip())
        return st
    st.is_repo = True
    st.toplevel = Path(top.stdout.strip()).resolve()
    _read_status(st)
    _read_markers(st)
    _read_config(st)
    _read_refs(st)
    if deep:
        _read_outer_repo(st)
        _read_nested(st)
        _read_blobs(st)
        _read_extras(st)
    return st


def _read_status(st: RepoState) -> None:
    # Listing untracked files in a whole home folder can take minutes; skip it there.
    untracked = "no" if st.home_is_repo_root else "normal"
    r = run_git(st.toplevel, "status", "--porcelain=v2", "--branch", "-z", f"--untracked-files={untracked}")
    if not r.ok:
        st.error_text = redact(r.stderr.strip())
        return
    fields = r.stdout.split("\0")
    i = 0
    ab_seen = False
    while i < len(fields):
        line = fields[i]
        i += 1
        if not line:
            continue
        if line.startswith("# "):
            key, _, val = line[2:].partition(" ")
            if key == "branch.oid":
                st.unborn = val == "(initial)"
                st.head_oid = None if st.unborn else val
            elif key == "branch.head":
                st.detached = val == "(detached)"
                st.branch = None if st.detached else val
            elif key == "branch.upstream":
                st.upstream = val
            elif key == "branch.ab":
                ab_seen = True
                a, b = val.split()
                st.ahead, st.behind = int(a), abs(int(b))
            continue
        tag = line[0]
        if tag == "1":
            parts = line.split(" ", 8)
            st.entries.append(Entry(parts[8], parts[1], "changed", mode_index=parts[4]))
        elif tag == "2":
            parts = line.split(" ", 9)
            orig = fields[i] if i < len(fields) else ""
            i += 1
            st.entries.append(Entry(parts[9], parts[1], "renamed", mode_index=parts[4], orig_path=orig))
        elif tag == "u":
            parts = line.split(" ", 10)
            st.entries.append(Entry(parts[10], parts[1], "unmerged"))
        elif tag == "?":
            st.entries.append(Entry(line[2:], "??", "untracked"))
    if st.upstream and not ab_seen:
        st.upstream_gone = True


def _read_markers(st: RepoState) -> None:
    g = st.git_dir
    if g is None:
        return
    rm, ra = g / "rebase-merge", g / "rebase-apply"
    if rm.is_dir():
        st.in_progress.append("rebase")
        st.rebase_head_name = _read_text(rm / "head-name").replace("refs/heads/", "")
        st.rebase_onto = _read_text(rm / "onto")[:9]
        n, e = _read_text(rm / "msgnum"), _read_text(rm / "end")
        st.rebase_step = f"{n} of {e}" if n and e else ""
        st.rebase_edit_stop = (rm / "amend").exists()
    elif ra.is_dir():
        if (ra / "applying").exists():
            st.in_progress.append("am")
        else:
            st.in_progress.append("rebase")
            st.rebase_head_name = _read_text(ra / "head-name").replace("refs/heads/", "")
            n, e = _read_text(ra / "next"), _read_text(ra / "last")
            st.rebase_step = f"{n} of {e}" if n and e else ""
    if (g / "MERGE_HEAD").exists():
        st.in_progress.append("merge")
    if (g / "CHERRY_PICK_HEAD").exists():
        st.in_progress.append("cherry-pick")
    if (g / "REVERT_HEAD").exists():
        st.in_progress.append("revert")
    if (g / "BISECT_LOG").exists() or (g / "BISECT_START").exists():
        st.in_progress.append("bisect")
    st.index_lock = (g / "index.lock").exists()
    if st.in_progress and not st.unmerged:
        r = run_git(st.toplevel, "diff", "--cached", "--check")
        for line in r.stdout.splitlines():
            if "leftover conflict marker" in line:
                st.leftover_markers.append(line.split(":", 1)[0])
        st.leftover_markers = sorted(set(st.leftover_markers))
    fh = (st.common_dir or g) / "FETCH_HEAD"
    try:
        st.last_fetch = fh.stat().st_mtime
    except OSError:
        st.last_fetch = None


def _read_text(p: Path) -> str:
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _read_config(st: RepoState) -> None:
    n = run_git(st.toplevel, "config", "--get", "user.name")
    e = run_git(st.toplevel, "config", "--get", "user.email")
    st.user_name = n.stdout.strip() or None
    st.user_email = e.stdout.strip() or None
    r = run_git(st.toplevel, "config", "--get-regexp", r"^remote\..*\.url$")
    for line in r.stdout.splitlines():
        key, _, url = line.partition(" ")
        name = key[len("remote.") : -len(".url")]
        st.remotes[name] = redact(url.strip())


def _read_refs(st: RepoState) -> None:
    r = run_git(st.toplevel, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes")
    for ref in r.stdout.splitlines():
        if ref.startswith("refs/heads/"):
            st.local_branches.append(ref[len("refs/heads/") :])
        elif ref.startswith("refs/remotes/") and not ref.endswith("/HEAD"):
            st.remote_branches.append(ref[len("refs/remotes/") :])
    if st.detached and st.head_oid:
        c = run_git(st.toplevel, "rev-list", "--count", "HEAD", "--not", "--branches", "--remotes", "--tags")
        if c.ok and c.stdout.strip().isdigit():
            st.orphan_commits = int(c.stdout.strip())


def _read_outer_repo(st: RepoState) -> None:
    parent = st.toplevel.parent
    if parent == st.toplevel:
        return
    r = run_git(parent, "rev-parse", "--show-toplevel")
    if r.ok and r.stdout.strip():
        st.outer_repo = Path(r.stdout.strip()).resolve()


_SKIP_DIRS = {"node_modules", ".venv", "venv", "env", "__pycache__", ".ipynb_checkpoints", ".tox", ".mypy_cache"}


def _read_nested(st: RepoState) -> None:
    top = st.toplevel
    gm = top / ".gitmodules"
    if gm.exists():
        for line in _read_text(gm).splitlines():
            k, _, v = line.strip().partition("=")
            if k.strip() == "path":
                st.gitmodules.add(v.strip())
    # Folders git sees as untracked that hold their own repository.
    budget = [3000]
    for e in st.untracked:
        if e.path.endswith("/"):
            d = top / e.path.rstrip("/")
            st.nested_repos.extend(_find_git_dirs(d, top, 3, budget))
    # Embedded repositories already added without .gitmodules.
    r = run_git(top, "ls-files", "-s", "-z")
    for rec in _lines0(r.stdout):
        meta, _, path = rec.partition("\t")
        if meta.startswith("160000") and path not in st.gitmodules:
            st.unregistered_gitlinks.append(path)
    for e in st.staged:
        if e.mode_index == "160000" and e.path not in st.gitmodules and e.path not in st.unregistered_gitlinks:
            st.unregistered_gitlinks.append(e.path)


def _find_git_dirs(d: Path, top: Path, depth: int, budget: list[int]) -> list[str]:
    found: list[str] = []
    if budget[0] <= 0 or depth < 0:
        return found
    if (d / ".git").exists():
        return [d.relative_to(top).as_posix()]
    try:
        children = list(os.scandir(d))
    except OSError:
        return found
    for c in children:
        budget[0] -= 1
        if budget[0] <= 0:
            break
        if c.is_dir(follow_symlinks=False) and c.name not in _SKIP_DIRS and not c.name.startswith("."):
            found.extend(_find_git_dirs(Path(c.path), top, depth - 1, budget))
    return found


SENSITIVE_NAMES = {
    ".env",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "credentials.json",
    "kaggle.json",
    ".netrc",
    "_netrc",
    ".pypirc",
    "secrets.toml",
}
SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore", ".jks")
SAFE_ENV_SUFFIXES = (".example", ".sample", ".template", ".dist")


def is_sensitive(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    if name in SENSITIVE_NAMES:
        return True
    if name.startswith(".env.") and not name.endswith(SAFE_ENV_SUFFIXES):
        return True
    if name.endswith(SENSITIVE_SUFFIXES):
        return True
    if name.endswith(".json") and (
        name.startswith("client_secret") or "service-account" in name or "service_account" in name
    ):
        return True
    return False


def _read_blobs(st: RepoState) -> None:
    top = st.toplevel
    staged: list[tuple[str, str]] = []  # (oid, path)
    r = run_git(top, "diff", "--cached", "--raw", "-z", "--no-abbrev", "--no-renames", "--diff-filter=AM")
    if r.ok:
        parts = _lines0(r.stdout)
        for i in range(0, len(parts) - 1, 2):
            meta, path = parts[i], parts[i + 1]
            cols = meta.split()
            if len(cols) >= 4 and cols[1] != "160000":
                staged.append((cols[3], path))
    unpushed: list[tuple[str, str]] = []
    if st.head_oid:
        r = run_git(top, "rev-list", "--objects", "HEAD", "--not", "--remotes", timeout=30)
        if r.ok:
            for line in r.stdout.splitlines():
                oid, _, path = line.partition(" ")
                if path:
                    unpushed.append((oid, path))
    sizes = _object_sizes(top, [o for o, _ in staged] + [o for o, _ in unpushed])
    seen: set[tuple[str, str]] = set()
    for where, items in (("staged", staged), ("unpushed", unpushed)):
        for oid, path in items:
            typ, size = sizes.get(oid, ("", 0))
            if where == "unpushed" and typ != "blob":
                continue
            if size >= GITHUB_WARN_LIMIT and (path, "big") not in seen:
                seen.add((path, "big"))
                st.big_files.append(BigFile(path, size, where))
            if is_sensitive(path) and (path, "sens") not in seen:
                seen.add((path, "sens"))
                st.sensitive.append(BigFile(path, size, where))
            if where == "staged" and path.lower().endswith(".ipynb") and size >= NOTEBOOK_WARN_SIZE:
                st.big_notebooks.append(BigFile(path, size, where))


def _object_sizes(top: Path, oids: list[str]) -> dict[str, tuple[str, int]]:
    if not oids:
        return {}
    out: dict[str, tuple[str, int]] = {}
    r = run_git(
        top,
        "cat-file",
        "--batch-check=%(objectname) %(objecttype) %(objectsize)",
        input_text="\n".join(oids) + "\n",
        timeout=30,
    )
    for line in r.stdout.splitlines():
        cols = line.split()
        if len(cols) == 3 and cols[2].isdigit():
            out[cols[0]] = (cols[1], int(cols[2]))
    return out


def _read_extras(st: RepoState) -> None:
    if st.head_oid:
        r = run_git(st.toplevel, "log", "-n", "1", "--format=%h %s (%cr)")
        st.last_commit = r.stdout.strip()
    r = run_git(st.toplevel, "rev-list", "--walk-reflogs", "--count", "refs/stash")
    if r.ok and r.stdout.strip().isdigit():
        st.stash_count = int(r.stdout.strip())
