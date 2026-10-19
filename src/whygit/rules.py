"""Diagnosis rules. Each rule looks at a RepoState and returns a Finding or None."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .findings import BOOK, DOCS, Finding, FixOption, Step, q
from .state import GITHUB_HARD_LIMIT, MB, RepoState

Detect = Callable[[RepoState], "Finding | None"]


@dataclass
class Rule:
    id: str
    severity: str
    summary: str
    detect: Detect
    quiet: bool = False  # hidden when something more urgent is reported


RULES: list[Rule] = []


def rule(rule_id: str, severity: str, summary: str, quiet: bool = False):
    def deco(fn: Detect) -> Detect:
        RULES.append(Rule(rule_id, severity, summary, fn, quiet))
        return fn

    return deco


def rule_order() -> dict[str, int]:
    return {r.id: i for i, r in enumerate(RULES)}


def get_rule(rule_id: str) -> Rule:
    for r in RULES:
        if r.id == rule_id:
            return r
    raise KeyError(rule_id)


def _mb(n: int) -> str:
    return f"{n / MB:.1f} MB"


def _plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


def _paths(paths: list[str], limit: int = 6) -> str:
    shown = " ".join(q(p) for p in paths[:limit])
    return shown if len(paths) <= limit else shown + " ..."


def _branch_or(st: RepoState, fallback: str = "<branch>") -> str:
    return st.branch or fallback


# ---------------------------------------------------------------- environment


@rule("git_not_installed", "blocking", "Git itself is not installed or not on PATH")
def git_not_installed(st: RepoState):
    if st.git_available:
        return None
    return Finding(
        "git_not_installed",
        "blocking",
        "Git is not installed (or your terminal can't find it)",
        "whygit asks the `git` program about your repository, and no `git` command could be started. "
        "Install Git, then open a new terminal window so it is picked up.",
        fix=[
            FixOption(
                "Install Git",
                [
                    Step("On macOS, installs Apple's command line tools, which include Git", "xcode-select --install"),
                    Step("On Windows, download and run the installer from https://git-scm.com/downloads/win"),
                    Step("Checks that Git now works (open a new terminal first)", "git --version"),
                ],
            )
        ],
        learn_more=BOOK + "Getting-Started-Installing-Git",
    )


@rule("dubious_ownership", "blocking", "Git refuses a repository owned by another user")
def dubious_ownership(st: RepoState):
    if st.not_repo_reason != "dubious":
        return None
    return dubious_finding(str(st.path))


def dubious_finding(path: str) -> Finding:
    return Finding(
        "dubious_ownership",
        "blocking",
        "Git doesn't trust this folder because a different user account owns it",
        "As a safety check, Git refuses to work in a repository whose folder belongs to another user. "
        "This often happens with folders copied from a USB drive, a shared drive, OneDrive, or made with `sudo`.",
        fix=[
            FixOption(
                "If this is your project and you trust it",
                [
                    Step(
                        "Tells Git this one folder is safe to use (it changes only your own Git settings)",
                        f"git config --global --add safe.directory {q(path)}",
                    )
                ],
            ),
            FixOption(
                "Or make the folder yours again",
                [
                    Step(
                        "On macOS or Linux, gives your account ownership of the folder",
                        f"sudo chown -R $(whoami) {q(path)}",
                    )
                ],
            ),
        ],
        learn_more=DOCS + "git-config#Documentation/git-config.txt-safedirectory",
    )


@rule("not_a_repo", "blocking", "The folder is not inside a Git repository")
def not_a_repo(st: RepoState):
    if not st.git_available or st.not_repo_reason != "not_found":
        return None
    from .state import is_under, same_path

    kids = _child_repos(st)
    at_home = same_path(st.path, st.home)
    details = kids if len(kids) > 1 else []
    if at_home:
        expl = (
            "You're in your home folder, which is not a Git repository (that's normal and how it should be). "
            "Git commands only work inside a project folder that has been cloned or set up with `git init`."
        )
    elif is_under(st.path, st.home):
        expl = (
            "This folder isn't inside a Git repository, so Git has nothing to work with here. "
            "You are probably one folder too high or in the wrong place; move into your project folder first."
        )
    else:
        expl = "This folder isn't inside a Git repository, so Git has nothing to work with here."
    fixes: list[FixOption] = []
    if kids:
        if len(kids) == 1:
            step = Step(f"Moves into {kids[0]}", f"cd {q(kids[0])}")
        else:
            step = Step("Moves into one of the repositories listed above", "cd <folder>")
        fixes.append(FixOption("Move into the project folder", [step]))
    fixes.append(
        FixOption(
            "Or get the project from GitHub",
            [
                Step(
                    "Downloads the repository into a new folder and sets up the link to GitHub",
                    "git clone <repository-url>",
                )
            ],
        )
    )
    init_step = Step("Starts a brand-new repository in the current folder", "git init")
    if at_home:
        init_step.warning = "Don't run this in your home folder: it would make your whole home folder one repository."
        init_step.destructive = False
    fixes.append(FixOption("Or start a new repository here (only for a new project)", [init_step]))
    return Finding(
        "not_a_repo",
        "blocking",
        "This folder is not a Git repository",
        expl,
        fix=fixes,
        details=details,
        details_label="Repositories found just below this folder",
        learn_more=DOCS + "git-init",
    )


def _child_repos(st: RepoState) -> list[str]:
    import os

    found: list[str] = []
    try:
        for c in sorted(os.scandir(st.path), key=lambda d: d.name.lower()):
            if c.is_dir() and not c.name.startswith("."):
                if os.path.exists(os.path.join(c.path, ".git")):
                    found.append(c.name)
                elif len(found) < 5:
                    try:
                        for g in os.scandir(c.path):
                            if (
                                g.is_dir()
                                and not g.name.startswith(".")
                                and os.path.exists(os.path.join(g.path, ".git"))
                            ):
                                found.append(f"{c.name}/{g.name}")
                    except OSError:
                        pass
            if len(found) > 50:
                break
    except OSError:
        pass
    if len(found) > 8:
        more = f"{len(found) - 8}+" if len(found) > 50 else str(len(found) - 8)
        return found[:8] + [f"... and {more} more"]
    return found


@rule("inside_git_dir", "warning", "The current folder is the hidden .git folder itself")
def inside_git_dir(st: RepoState):
    if st.not_repo_reason != "inside_git_dir":
        return None
    return Finding(
        "inside_git_dir",
        "warning",
        "You're inside the hidden .git folder",
        "The .git folder is where Git keeps its own records; your project files are in the folder above it. "
        "Most commands won't work from in here.",
        fix=[FixOption("Go back up to the project", [Step("Moves up to the folder that contains .git", "cd ..")])],
        learn_more=DOCS + "gitrepository-layout",
    )


@rule("bare_repo", "info", "The folder is a bare repository (storage only, no working files)")
def bare_repo(st: RepoState):
    if st.not_repo_reason != "bare":
        return None
    return Finding(
        "bare_repo",
        "info",
        "This is a bare repository, not a working folder",
        "A bare repository holds only Git's history (like the copy on a server) and has no files to edit. "
        "To work on the project, clone it into a normal folder.",
        fix=[
            FixOption(
                "Make a working copy",
                [
                    Step(
                        "Creates a normal folder you can edit, linked to this one",
                        f"git clone {q(str(st.path))} my-project",
                    )
                ],
            )
        ],
        learn_more=DOCS + "git-clone",
    )


@rule("home_repo", "blocking", "The home directory itself is a Git repository")
def home_repo(st: RepoState):
    if not st.is_repo:
        return None
    from .state import same_path

    top_is_home = st.home_is_repo_root
    outer_is_home = st.outer_repo is not None and same_path(st.outer_repo, st.home)
    if not (top_is_home or outer_is_home):
        return None
    if top_is_home:
        sev = "blocking"
        expl = (
            "The repository you're in starts at your home folder, so Git treats everything in your home folder "
            "(documents, downloads, other projects) as part of one project. This almost always comes from running "
            "`git init` in the wrong place, and it can lead to private files being committed or pushed."
        )
    else:
        sev = "warning"
        expl = (
            "Your project is fine, but your home folder is also a Git repository, which usually comes from running "
            "`git init` in the wrong place. It makes other folders behave strangely and risks committing private files."
        )
    return Finding(
        "home_repo",
        sev,
        "Your home folder has been turned into a Git repository",
        expl,
        fix=[
            FixOption(
                "Check, then switch it off without deleting anything",
                [
                    Step(
                        "Shows any commits in the home-folder repository; 'does not have any commits yet' means it was an accident",
                        "git -C ~ log --oneline -n 5",
                    ),
                    Step(
                        "On macOS or Linux, renames the hidden .git folder so your home folder stops being a repository (you can rename it back)",
                        "mv ~/.git ~/git-home-backup",
                    ),
                    Step("On Windows PowerShell, does the same rename", "Rename-Item ~\\.git git-home-backup"),
                    Step("Once you're sure you didn't need it, you can delete the git-home-backup folder yourself."),
                ],
            )
        ],
        learn_more=DOCS + "git-init",
    )


@rule("index_lock", "warning", "An index.lock file is left in .git")
def index_lock(st: RepoState):
    if not st.is_repo or not st.index_lock:
        return None
    return index_lock_finding(str(st.git_dir / "index.lock") if st.git_dir else ".git/index.lock")


def index_lock_finding(lock_path: str) -> Finding:
    return Finding(
        "index_lock",
        "warning",
        "Git thinks another Git command is still running here",
        "Git creates a file called index.lock while it updates the staging area (the list of changes for the next commit), "
        "and deletes it when done. If the file is still there, either another Git program is running right now "
        "(an editor like VS Code, GitHub Desktop, or another terminal), or an earlier command crashed and left it behind.",
        fix=[
            FixOption(
                "Wait, then check",
                [
                    Step("Close or wait for other Git tools: VS Code, GitHub Desktop, other terminals running git."),
                    Step(
                        "On macOS or Linux, lists running git processes (no output apart from the grep line means none)",
                        "ps aux | grep -i git",
                    ),
                    Step("On Windows, open Task Manager and look for git.exe."),
                ],
            ),
            FixOption(
                "Only if no Git process is running",
                [
                    Step(
                        "Deletes the stale lock file (macOS/Linux; on Windows use: del "
                        + lock_path.replace("/", "\\")
                        + ")",
                        f"rm {q(lock_path)}",
                        destructive=True,
                        warning="Deleting the lock while Git is still running can corrupt the staging area. Check first.",
                    )
                ],
            ),
        ],
        learn_more=DOCS + "gitrepository-layout",
    )


# ---------------------------------------------------------------- operations in progress


CONFLICT_LABELS = {
    "UU": "both changed",
    "AA": "both added",
    "DD": "both deleted",
    "AU": "added by you",
    "UA": "added by them",
    "DU": "deleted by you, changed by them",
    "UD": "changed by you, deleted by them",
}


def _conflict_details(st: RepoState) -> list[str]:
    return [f"{e.path}  ({CONFLICT_LABELS.get(e.xy, e.xy)})" for e in st.unmerged]


def _edit_step() -> Step:
    return Step(
        "Open each file and find the blocks between <<<<<<< and >>>>>>>. The part above ======= is one version, "
        "the part below is the other. Keep what you want, and delete the three marker lines."
    )


def _notebook_note(st: RepoState) -> list[Step]:
    if any(e.path.lower().endswith(".ipynb") for e in st.unmerged):
        return [Step("For .ipynb notebooks, don't edit the markers by hand; see the notebook advice below.")]
    return []


def _deleted_note(st: RepoState) -> list[Step]:
    if any(e.xy in ("DU", "UD") for e in st.unmerged):
        return [
            Step(
                "For a file one side deleted: keep it with `git add <file>`, or accept the deletion with `git rm <file>`."
            )
        ]
    return []


@rule("merge_conflict", "blocking", "Merge stopped with conflicts")
def merge_conflict(st: RepoState):
    if "merge" not in st.in_progress or not st.unmerged:
        return None
    files = [e.path for e in st.unmerged]
    return Finding(
        "merge_conflict",
        "blocking",
        f"Merge in progress with conflicts in {_plural(len(files), 'file')}",
        "Git tried to combine two lines of work, but both changed the same part of these files, so it stopped "
        "and is waiting for you to choose what the result should be. Nothing is lost while you decide.",
        details=_conflict_details(st),
        details_label="Conflicted files",
        fix=[
            FixOption(
                "Finish the merge",
                [
                    _edit_step(),
                    *_notebook_note(st),
                    *_deleted_note(st),
                    Step("Marks the files as resolved", f"git add {_paths(files)}"),
                    Step("Records the merge and finishes it", "git commit --no-edit"),
                ],
            ),
            FixOption(
                "Or cancel the merge",
                [Step("Puts everything back the way it was before the merge started", "git merge --abort")],
            ),
        ],
        learn_more=DOCS + "git-merge#_how_to_resolve_conflicts",
    )


@rule("merge_resolved", "blocking", "Merge resolved but not yet committed")
def merge_resolved(st: RepoState):
    if "merge" not in st.in_progress or st.unmerged:
        return None
    steps = []
    note = ""
    if st.leftover_markers:
        note = "Some staged files still contain conflict markers (<<<<<<<): " + ", ".join(st.leftover_markers[:5])
        steps.append(
            Step(
                "Remove the leftover <<<<<<< / ======= / >>>>>>> lines from those files, then add them again",
                f"git add {_paths(st.leftover_markers)}",
            )
        )
    steps.append(Step("Records the merge and finishes it", "git commit --no-edit"))
    return Finding(
        "merge_resolved",
        "blocking",
        "Merge is waiting for you to commit it",
        "All conflicts are marked as resolved, but the merge isn't finished until you make the merge commit. "
        "Until then Git treats the merge as still in progress and many commands will refuse to run.",
        note=note,
        fix=[
            FixOption("Finish the merge", steps),
            FixOption(
                "Or cancel the merge",
                [Step("Throws away the merge result and goes back to before the merge", "git merge --abort")],
            ),
        ],
        learn_more=DOCS + "git-merge",
    )


@rule("rebase_in_progress", "blocking", "Rebase stopped partway (conflict, edit, or paused)")
def rebase_in_progress(st: RepoState):
    if "rebase" not in st.in_progress:
        return None
    where = f" (step {st.rebase_step})" if st.rebase_step else ""
    branch = f"branch '{st.rebase_head_name}'" if st.rebase_head_name else "your branch"
    abort = FixOption(
        "Or cancel the whole rebase",
        [Step(f"Puts {branch} back exactly as it was before the rebase started", "git rebase --abort")],
    )
    if st.unmerged:
        files = [e.path for e in st.unmerged]
        return Finding(
            "rebase_in_progress",
            "blocking",
            f"Rebase stopped on a conflict{where}",
            f"A rebase replays the commits of {branch} one at a time on top of another commit. One of them changed "
            "the same lines as the new base, so Git paused and is waiting for you to combine them. "
            "During a rebase, 'ours' means the base you're rebasing onto and 'theirs' means your own commit.",
            details=_conflict_details(st),
            details_label="Conflicted files",
            fix=[
                FixOption(
                    "Resolve and continue",
                    [
                        _edit_step(),
                        *_deleted_note(st),
                        Step("Marks the files as resolved", f"git add {_paths(files)}"),
                        Step("Continues replaying the remaining commits", "git rebase --continue"),
                    ],
                ),
                abort,
                FixOption(
                    "Or drop just this commit",
                    [
                        Step(
                            "Skips the commit that conflicted and carries on",
                            "git rebase --skip",
                            destructive=True,
                            warning="The changes in the skipped commit are left out of your branch.",
                        )
                    ],
                ),
            ],
            learn_more=DOCS + "git-rebase",
        )
    if st.rebase_edit_stop:
        return Finding(
            "rebase_in_progress",
            "blocking",
            f"Rebase paused so you can edit a commit{where}",
            f"You (or a script) asked the rebase of {branch} to stop at this commit so it could be changed. "
            "Git is waiting for you to make the change and then continue.",
            fix=[
                FixOption(
                    "Edit and continue",
                    [
                        Step("Make your changes to the files, then stage them", "git add <file>"),
                        Step("Folds the staged changes into the paused commit", "git commit --amend --no-edit"),
                        Step("Continues with the remaining commits", "git rebase --continue"),
                    ],
                ),
                abort,
            ],
            learn_more=DOCS + "git-rebase",
        )
    return Finding(
        "rebase_in_progress",
        "blocking",
        f"Rebase is paused{where}",
        f"A rebase of {branch} is still in progress: conflicts are resolved (or it was paused on purpose), "
        "but Git is waiting for you to continue it.",
        fix=[
            FixOption("Continue", [Step("Carries on replaying the remaining commits", "git rebase --continue")]),
            abort,
        ],
        learn_more=DOCS + "git-rebase",
    )


def _sequencer_finding(st: RepoState, op: str, verb: str, doc: str) -> Finding:
    if st.unmerged:
        files = [e.path for e in st.unmerged]
        return Finding(
            f"{op.replace('-', '_')}_in_progress",
            "blocking",
            f"{op.capitalize()} stopped on a conflict",
            f"You asked Git to {verb}, and it changes the same lines as your current work, so Git paused and is "
            "waiting for you to combine them.",
            details=_conflict_details(st),
            details_label="Conflicted files",
            fix=[
                FixOption(
                    "Resolve and continue",
                    [
                        _edit_step(),
                        Step("Marks the files as resolved", f"git add {_paths(files)}"),
                        Step(f"Finishes the {op}", f"git {op} --continue"),
                    ],
                ),
                FixOption("Or cancel it", [Step(f"Goes back to before the {op} started", f"git {op} --abort")]),
            ],
            learn_more=DOCS + doc,
        )
    return Finding(
        f"{op.replace('-', '_')}_in_progress",
        "blocking",
        f"{op.capitalize()} is in progress",
        f"A {op} (asking Git to {verb}) has started but isn't finished, so Git is waiting for you to continue or cancel it.",
        fix=[
            FixOption("Finish it", [Step(f"Finishes the {op}", f"git {op} --continue")]),
            FixOption("Or cancel it", [Step(f"Goes back to before the {op} started", f"git {op} --abort")]),
        ],
        learn_more=DOCS + doc,
    )


@rule("cherry_pick_in_progress", "blocking", "Cherry-pick in progress")
def cherry_pick_in_progress(st: RepoState):
    if "cherry-pick" not in st.in_progress:
        return None
    return _sequencer_finding(st, "cherry-pick", "copy a commit from another branch onto this one", "git-cherry-pick")


@rule("revert_in_progress", "blocking", "Revert in progress")
def revert_in_progress(st: RepoState):
    if "revert" not in st.in_progress:
        return None
    return _sequencer_finding(st, "revert", "undo an earlier commit with a new commit", "git-revert")


@rule("am_in_progress", "blocking", "Applying patches (git am) stopped")
def am_in_progress(st: RepoState):
    if "am" not in st.in_progress:
        return None
    return Finding(
        "am_in_progress",
        "blocking",
        "Applying a patch (git am) stopped partway",
        "Git was applying commits from patch files or emails and one of them didn't apply cleanly. "
        "It's waiting for you to fix it, skip it, or cancel.",
        details=[e.path for e in st.unmerged],
        details_label="Conflicted files",
        fix=[
            FixOption(
                "Fix and continue",
                [
                    Step("Fix the files, then stage them", "git add <file>"),
                    Step("Continues with the next patch", "git am --continue"),
                ],
            ),
            FixOption("Or cancel", [Step("Goes back to before git am started", "git am --abort")]),
            FixOption(
                "Or skip this patch",
                [
                    Step(
                        "Leaves this patch out",
                        "git am --skip",
                        destructive=True,
                        warning="The skipped patch's changes are not applied.",
                    )
                ],
            ),
        ],
        learn_more=DOCS + "git-am",
    )


@rule("bisect_in_progress", "warning", "A bisect session is active")
def bisect_in_progress(st: RepoState):
    if "bisect" not in st.in_progress:
        return None
    return Finding(
        "bisect_in_progress",
        "warning",
        "You're in the middle of a git bisect",
        "Bisect is a search through your history for the commit that introduced a bug, and it checks out old "
        "commits as it goes. Until you finish it, you are not on your branch.",
        fix=[
            FixOption(
                "Continue the search",
                [
                    Step("Test the code, then tell Git if this commit works", "git bisect good"),
                    Step("...or if it has the bug", "git bisect bad"),
                ],
            ),
            FixOption(
                "Or stop and go back to your branch",
                [Step("Ends the search and returns to where you started", "git bisect reset")],
            ),
        ],
        learn_more=DOCS + "git-bisect",
    )


@rule("notebook_conflict", "warning", "A Jupyter notebook has merge conflicts")
def notebook_conflict(st: RepoState):
    nbs = [e.path for e in st.unmerged if e.path.lower().endswith(".ipynb")]
    if not nbs:
        return None
    rebasing = "rebase" in st.in_progress
    mine, theirs = ("--theirs", "--ours") if rebasing else ("--ours", "--theirs")
    return Finding(
        "notebook_conflict",
        "warning",
        f"{_plural(len(nbs), 'notebook')} with conflicts",
        "A .ipynb file is really a large JSON text file with code, outputs and metadata mixed together, so the "
        "conflict markers land in the middle of JSON and Jupyter may refuse to open the file. It's usually easier "
        "to keep one whole version and then redo the other side's changes by hand.",
        details=nbs,
        details_label="Notebooks",
        fix=[
            FixOption(
                "Keep your version of each notebook",
                [
                    Step(
                        "Replaces the conflicted notebook with your version",
                        f"git restore {mine} {_paths(nbs)}",
                        destructive=True,
                        warning="Their changes to the notebook are dropped; copy anything you need from it first.",
                    ),
                    Step("Marks the notebook as resolved", f"git add {_paths(nbs)}"),
                ],
            ),
            FixOption(
                "Or keep their version",
                [
                    Step(
                        "Replaces the conflicted notebook with their version",
                        f"git restore {theirs} {_paths(nbs)}",
                        destructive=True,
                        warning="Your changes to the notebook are dropped; copy anything you need from it first.",
                    ),
                    Step("Marks the notebook as resolved", f"git add {_paths(nbs)}"),
                ],
            ),
            FixOption(
                "Or merge them properly with nbdime (optional tool)",
                [
                    Step("Installs nbdime, a notebook-aware diff and merge tool", "pip install nbdime"),
                    Step("Opens a side-by-side merge of the notebook in your browser", f"nbdime mergetool {q(nbs[0])}"),
                ],
            ),
        ],
        learn_more=DOCS + "git-merge#_how_to_resolve_conflicts",
    )


# ---------------------------------------------------------------- where HEAD is


@rule("detached_head", "warning", "HEAD is detached (not on a branch)")
def detached_head(st: RepoState):
    if not st.is_repo or not st.detached or {"rebase", "bisect", "am"} & set(st.in_progress):
        return None
    sha = (st.head_oid or "")[:7]
    if st.orphan_commits:
        expl = (
            f"You're on commit {sha} directly instead of on a branch (a 'detached HEAD'), and you have made "
            f"{_plural(st.orphan_commits, 'commit')} here that no branch points to. If you switch away now, "
            "those commits become very hard to find, so give them a branch first."
        )
        fix = [
            FixOption(
                "Keep your work on a new branch",
                [
                    Step(
                        "Creates a branch here so your commits are saved, and moves you onto it",
                        "git switch -c <new-branch-name>",
                    ),
                    Step(
                        "Later, to bring the work into main: switch to main and merge the new branch",
                        "git switch main && git merge <new-branch-name>",
                    ),
                ],
            )
        ]
    else:
        expl = (
            f"You're looking at commit {sha} directly instead of being on a branch (a 'detached HEAD'). "
            "That's fine for looking around, but new commits made here won't belong to any branch."
        )
        fix = [
            FixOption(
                "Go back to your branch",
                [
                    Step(
                        "Returns to the main branch",
                        f"git switch {'main' if 'main' in st.local_branches else (st.local_branches[0] if st.local_branches else 'main')}",
                    )
                ],
            ),
            FixOption(
                "Or start a branch here",
                [Step("Creates a new branch at this commit and moves onto it", "git switch -c <new-branch-name>")],
            ),
        ]
    return Finding(
        "detached_head",
        "warning",
        "You're not on a branch (detached HEAD)",
        expl,
        fix=fix,
        learn_more=DOCS + "git-checkout#_detached_head",
    )


@rule("unborn_branch", "info", "No commits yet")
def unborn_branch(st: RepoState):
    if not st.is_repo or not st.unborn or st.home_is_repo_root:
        return None
    b = _branch_or(st, "main")
    staged = bool(st.staged)
    return Finding(
        "unborn_branch",
        "info",
        "Nothing has been committed yet",
        f"This repository has no commits, so the branch '{b}' doesn't really exist yet and there is nothing to push. "
        "A commit is a saved snapshot of your files; make the first one to get started.",
        fix=[
            FixOption(
                "Make the first commit",
                (
                    []
                    if staged
                    else [
                        Step("Stages every file in this folder for the commit (check `git status` first)", "git add .")
                    ]
                )
                + [Step("Saves the snapshot with a message", 'git commit -m "First commit"')],
            )
        ],
        learn_more=DOCS + "git-commit",
    )


# ---------------------------------------------------------------- remote and upstream


@rule("diverged", "warning", "Branch and its upstream have both moved on")
def diverged(st: RepoState):
    if not st.ahead or not st.behind:
        return None
    return Finding(
        "diverged",
        "warning",
        f"Your branch and {st.upstream} have diverged",
        f"You have {_plural(st.ahead, 'commit')} that {st.upstream} doesn't, and it has {_plural(st.behind, 'commit')} "
        "you don't (someone pushed while you were working, or you committed on another computer). "
        "Git won't let you push until you combine them.",
        note=st.fetch_note(),
        fix=[
            FixOption(
                "Combine them with a merge (safest)",
                [
                    Step(
                        "Downloads their commits and merges them into yours; fix any conflicts it reports",
                        "git pull --no-rebase",
                    ),
                    Step("Uploads the combined result", "git push"),
                ],
            ),
            FixOption(
                "Or replay your commits on top of theirs",
                [
                    Step("Same as above but keeps history in a straight line", "git pull --rebase"),
                    Step("Uploads the result", "git push"),
                ],
            ),
            FixOption(
                "Only if their commits really should be thrown away",
                [
                    Step(
                        "Overwrites the remote branch with yours",
                        "git push --force-with-lease",
                        destructive=True,
                        warning="This deletes the other commits from GitHub for everyone. Don't do this on a shared branch.",
                    )
                ],
            ),
        ],
        learn_more=DOCS + "git-pull",
    )


@rule("behind", "info", "Branch is behind its upstream")
def behind(st: RepoState):
    if not st.behind or st.ahead:
        return None
    return Finding(
        "behind",
        "info",
        f"Your branch is {_plural(st.behind, 'commit')} behind {st.upstream}",
        f"{st.upstream} has new commits that you don't have yet. Pull them before you start new work to avoid conflicts later.",
        note=st.fetch_note(),
        fix=[FixOption("Update", [Step("Downloads and adds the new commits to your branch", "git pull")])],
        learn_more=DOCS + "git-pull",
    )


@rule("ahead", "info", "Branch has commits not pushed yet")
def ahead(st: RepoState):
    if not st.ahead or st.behind:
        return None
    held = any(b.where == "unpushed" for b in st.big_files + st.sensitive)
    return Finding(
        "ahead",
        "info",
        f"You have {_plural(st.ahead, 'commit')} not pushed to {st.upstream} yet",
        "These commits exist only on this computer. Push them to back them up and share them."
        + (" Sort out the file warnings above before you push." if held else ""),
        note=st.fetch_note(),
        fix=[FixOption("Upload", [Step(f"Sends your commits to {st.upstream}", "git push")])],
        learn_more=DOCS + "git-push",
    )


@rule("upstream_gone", "info", "The upstream branch was deleted on the remote")
def upstream_gone(st: RepoState):
    if not st.upstream_gone:
        return None
    return Finding(
        "upstream_gone",
        "info",
        f"The branch this tracks ({st.upstream}) no longer exists on the remote",
        "Someone deleted the branch on GitHub, often after its pull request was merged. Your local copy is untouched.",
        fix=[
            FixOption(
                "If the work was merged",
                [
                    Step("Moves to main", "git switch main"),
                    Step("Gets the merged work", "git pull"),
                    Step(
                        "Deletes the old local branch (refuses if it has unmerged work)",
                        f"git branch -d {_branch_or(st)}",
                    ),
                ],
            ),
            FixOption(
                "If you want to keep working on it",
                [Step("Pushes it again and tracks it", f"git push -u origin {_branch_or(st)}")],
            ),
        ],
        learn_more=DOCS + "git-branch",
    )


@rule("no_upstream", "info", "Branch has no upstream (first push needs -u)", quiet=True)
def no_upstream(st: RepoState):
    if not st.is_repo or st.unborn or st.detached or st.upstream or not st.remotes:
        return None
    remote = "origin" if "origin" in st.remotes else next(iter(st.remotes))
    b = _branch_or(st)
    if f"{remote}/{b}" in st.remote_branches:
        steps = [
            Step(
                f"Links {b} to {remote}/{b} so plain `git pull` and `git push` work",
                f"git branch --set-upstream-to={remote}/{b}",
            )
        ]
    else:
        steps = [
            Step(
                f"Uploads {b} and remembers {remote}/{b} as its upstream, so later you can just type `git push`",
                f"git push -u {remote} {b}",
            )
        ]
    return Finding(
        "no_upstream",
        "info",
        f"Branch '{b}' isn't linked to a branch on {remote} yet",
        "The 'upstream' is the branch on GitHub that this one pushes to and pulls from. Until it's set, "
        "`git push` and `git pull` don't know where to go.",
        fix=[FixOption("Set it up", steps)],
        learn_more=DOCS + "git-push",
    )


@rule("no_remote", "info", "Repository has no remote", quiet=True)
def no_remote(st: RepoState):
    if not st.is_repo or st.unborn or st.remotes:
        return None
    b = _branch_or(st, "main")
    return Finding(
        "no_remote",
        "info",
        "This repository isn't connected to GitHub (no remote)",
        "A remote is the address of the copy of your repository on a server such as GitHub. "
        "Without one, your commits exist only on this computer.",
        fix=[
            FixOption(
                "Connect it",
                [
                    Step(
                        "Create an empty repository on GitHub. Leave 'Add a README' unticked, or the first push will be rejected."
                    ),
                    Step("Saves GitHub's address under the name origin", "git remote add origin <repository-url>"),
                    Step("Uploads your branch and links it", f"git push -u origin {b}"),
                ],
            )
        ],
        learn_more=DOCS + "git-remote",
    )


# ---------------------------------------------------------------- repository layout and identity


@rule("nested_repo", "warning", "A folder inside the repository is its own repository")
def nested_repo(st: RepoState):
    if not st.is_repo:
        return None
    from .state import same_path

    inner = st.nested_repos + [p for p in st.unregistered_gitlinks if p not in st.nested_repos]
    outer = st.outer_repo if (st.outer_repo is not None and not same_path(st.outer_repo, st.home)) else None
    if not inner and not outer:
        return None
    if inner:
        target = inner[0]
        backup = "../" + target.replace("/", "-") + "-git-backup"
        expl = (
            "A folder inside your project has its own hidden .git folder, so it is a separate repository. "
            "The outer repository stores it as a single link instead of its files, so on GitHub it shows up as an "
            "empty or unclickable folder. This usually happens with downloaded or cloned starter code."
        )
        fix = [
            FixOption(
                "Make its files part of your project",
                [
                    *(
                        [
                            Step(
                                "Removes the link from the staging area without touching the files",
                                f"git rm --cached {q(target)}",
                            )
                        ]
                        if target in st.unregistered_gitlinks
                        else []
                    ),
                    Step(
                        "On macOS or Linux, moves the inner .git folder out of your project, so the folder becomes ordinary files "
                        "(Windows PowerShell: Move-Item "
                        + target.replace("/", "\\")
                        + "\\.git "
                        + backup.replace("/", "\\")
                        + ")",
                        f"mv {q(target + '/.git')} {q(backup)}",
                    ),
                    Step("Stages the folder's files normally", f"git add {q(target)}"),
                    Step(
                        f"The moved folder ({backup}) holds that folder's old history; delete it once you're sure you don't need it."
                    ),
                ],
            )
        ]
        if len(inner) > 1:
            fix.append(
                FixOption(
                    "Repeat for each folder listed", [Step("Do the same steps for every folder in the list above.")]
                )
            )
        return Finding(
            "nested_repo",
            "warning",
            f"{_plural(len(inner), 'folder')} inside this repository {'is its' if len(inner) == 1 else 'are their'} own repository",
            expl,
            details=inner,
            details_label="Nested repositories",
            fix=fix,
            learn_more=DOCS + "gitsubmodules",
        )
    return Finding(
        "nested_repo",
        "warning",
        "This repository is inside another repository",
        f"The folder {outer} is also a Git repository and contains this one. Git commands run in the outer folder "
        "will see this project as a single link, not as files, which is confusing and usually not intended.",
        details=[str(outer)],
        details_label="Outer repository",
        fix=[
            FixOption(
                "Check whether the outer repository was made by mistake",
                [Step("Shows the outer repository's recent commits", f"git -C {q(str(outer))} log --oneline -n 5")],
            )
        ],
        learn_more=DOCS + "gitsubmodules",
    )


@rule("missing_identity", "warning", "user.name or user.email is not set")
def missing_identity(st: RepoState):
    if not st.is_repo or (st.user_name and st.user_email):
        return None
    missing = [k for k, v in (("user.name", st.user_name), ("user.email", st.user_email)) if not v]
    return identity_finding(missing)


def identity_finding(missing: list[str] | None = None) -> Finding:
    missing = missing or ["user.name", "user.email"]
    steps = []
    if "user.name" in missing:
        steps.append(Step("Sets the name shown on your commits", 'git config --global user.name "Your Name"'))
    if "user.email" in missing:
        steps.append(
            Step(
                "Sets the email on your commits; use the one on your GitHub account so commits link to you",
                'git config --global user.email "you@example.com"',
            )
        )
    return Finding(
        "missing_identity",
        "warning",
        "Git doesn't know your name and email yet",
        "Every commit records who made it. Git needs your name and email set once per computer before it will "
        "commit (or it guesses an address GitHub won't recognise).",
        details=missing,
        details_label="Not set",
        fix=[FixOption("Introduce yourself to Git (once per computer)", steps)],
        learn_more=BOOK + "Getting-Started-First-Time-Git-Setup",
    )


# ---------------------------------------------------------------- what is about to be pushed


def _reset_soft_target(st: RepoState) -> str | None:
    if st.upstream and not st.upstream_gone:
        return "@{u}"
    for cand in ("origin/main", "origin/master"):
        if cand in st.remote_branches:
            return cand
    return None


def _remove_from_commit_steps(st: RepoState, paths: list[str], gitignore_hint: str) -> list[FixOption]:
    staged = [p for p in paths if p in {e.path for e in st.staged}]
    opts: list[FixOption] = []
    target = _reset_soft_target(st)
    unpushed = [p for p in paths if p not in staged]
    if staged:
        opts.append(
            FixOption(
                "Take it out of the next commit",
                [
                    Step("Unstages the file but keeps it on your computer", f"git rm --cached {_paths(staged)}"),
                    Step(gitignore_hint),
                ],
            )
        )
    if unpushed:
        if target:
            opts.append(
                FixOption(
                    "It's already in a commit you haven't pushed: rebuild those commits without it",
                    [
                        Step(
                            "Undoes the unpushed commits but keeps all their changes staged (your files are not touched)",
                            f"git reset --soft {target}",
                        ),
                        Step(
                            "Takes the file out of what will be committed, keeping it on disk",
                            f"git rm --cached {_paths(unpushed)}",
                        ),
                        Step(gitignore_hint),
                        Step("Commits everything else again", 'git commit -m "Your message"'),
                    ],
                )
            )
        else:
            opts.append(
                FixOption(
                    "It's already in a commit you haven't pushed",
                    [
                        Step("Finds the commit before the file was added", f"git log --oneline -- {q(unpushed[0])}"),
                        Step(
                            "Undoes the commits after that point but keeps their changes staged (your files are not touched)",
                            "git reset --soft <commit-before-it>",
                        ),
                        Step("Takes the file out, keeping it on disk", f"git rm --cached {_paths(unpushed)}"),
                        Step(gitignore_hint),
                        Step("Commits everything else again", 'git commit -m "Your message"'),
                    ],
                )
            )
    return opts


@rule("large_file_over_limit", "blocking", "A staged or unpushed file is over GitHub's 100 MB limit")
def large_file_over_limit(st: RepoState):
    big = [b for b in st.big_files if b.size >= GITHUB_HARD_LIMIT]
    if not big:
        return None
    paths = [b.path for b in big]
    fixes = _remove_from_commit_steps(
        st, paths, "Add the file (or a pattern like data/*.csv) to .gitignore so it isn't added again"
    )
    fixes.append(
        FixOption(
            "Or store it with Git LFS (if you really need it on GitHub)",
            [
                Step(
                    "Sets up Git Large File Storage, a GitHub add-on for big files (install it from git-lfs.com first)",
                    "git lfs install",
                ),
                Step("Tells LFS to handle files like this one", f'git lfs track "*.{paths[0].rsplit(".", 1)[-1]}"'),
            ],
        )
    )
    return Finding(
        "large_file_over_limit",
        "blocking",
        f"{_plural(len(big), 'file')} over GitHub's 100 MB limit",
        "GitHub rejects any push that contains a file over 100 MB, even if you delete the file in a later commit. "
        "Large data files (CSVs, models, zips) are better kept out of Git and shared another way.",
        details=[
            f"{b.path}  ({_mb(b.size)}, {'staged' if b.where == 'staged' else 'in a commit not pushed yet'})"
            for b in big
        ],
        details_label="Files",
        fix=fixes,
        learn_more=DOCS + "git-rm",
    )


@rule("large_file_warning", "warning", "A staged or unpushed file is over 50 MB")
def large_file_warning(st: RepoState):
    big = [b for b in st.big_files if b.size < GITHUB_HARD_LIMIT]
    if not big:
        return None
    return Finding(
        "large_file_warning",
        "warning",
        f"{_plural(len(big), 'large file')} (over 50 MB) about to go to GitHub",
        "GitHub accepts files up to 100 MB but warns above 50 MB, and big files make every clone slow. "
        "Data files usually belong in .gitignore instead.",
        details=[
            f"{b.path}  ({_mb(b.size)}, {'staged' if b.where == 'staged' else 'in a commit not pushed yet'})"
            for b in big
        ],
        details_label="Files",
        fix=_remove_from_commit_steps(st, [b.path for b in big], "Add the file to .gitignore so it isn't added again"),
        learn_more=DOCS + "git-rm",
    )


@rule("secret_staged", "warning", "A file that often holds secrets or keys is staged or unpushed")
def secret_staged(st: RepoState):
    if not st.sensitive:
        return None
    paths = [s.path for s in st.sensitive]
    return Finding(
        "secret_staged",
        "warning",
        "A file that may contain passwords or keys is about to be committed or pushed",
        "Files like .env, private keys (.pem, id_rsa) and credentials JSON usually hold secrets. Once pushed to "
        "GitHub, assume anyone can read them, even if you delete them later.",
        details=[
            f"{s.path}  ({'staged' if s.where == 'staged' else 'in a commit not pushed yet'})" for s in st.sensitive
        ],
        details_label="Files",
        fix=_remove_from_commit_steps(st, paths, "Add the file name to .gitignore so it isn't added again")
        + [
            FixOption(
                "If it was already pushed",
                [Step("Treat the secret as leaked: create a new key or password and revoke the old one.")],
            )
        ],
        learn_more=DOCS + "gitignore",
    )


@rule("notebook_outputs", "warning", "A staged notebook is large, probably from saved outputs")
def notebook_outputs(st: RepoState):
    if not st.big_notebooks:
        return None
    nbs = [b.path for b in st.big_notebooks]
    return Finding(
        "notebook_outputs",
        "warning",
        f"{_plural(len(nbs), 'staged notebook')} with large saved outputs",
        "These notebooks are over 1 MB, which usually means they contain saved outputs: plots, tables or printed data. "
        "That makes diffs unreadable and conflicts likely, and can publish data you didn't mean to share.",
        details=[f"{b.path}  ({_mb(b.size)})" for b in st.big_notebooks],
        details_label="Notebooks",
        fix=[
            FixOption(
                "Clear outputs before committing",
                [
                    Step("In Jupyter or VS Code, use 'Clear All Outputs' and save, or run:"),
                    Step(
                        "Removes the outputs from the notebook file",
                        f"jupyter nbconvert --clear-output --inplace {_paths(nbs)}",
                        destructive=True,
                        warning="The saved outputs are deleted from the file; re-run the notebook to get them back.",
                    ),
                    Step("Stages the cleaned notebook", f"git add {_paths(nbs)}"),
                ],
            )
        ],
        learn_more=DOCS + "gitattributes",
    )
