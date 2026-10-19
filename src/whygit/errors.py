"""Matching pasted git and GitHub error text to explanations."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Callable

from . import rules as R
from .findings import BOOK, DOCS, Finding, FixOption, Step, q
from .gitcmd import redact
from .state import RepoState

Build = Callable[[re.Match, str, "RepoState | None"], Finding]


@dataclass
class ErrorRule:
    id: str
    family: str
    patterns: list[re.Pattern]
    build: Build


ERROR_RULES: list[ErrorRule] = []


def error_rule(rule_id: str, *patterns: str, family: str | None = None):
    def deco(fn: Build) -> Build:
        ERROR_RULES.append(ErrorRule(rule_id, family or rule_id, [re.compile(p, re.I | re.M) for p in patterns], fn))
        return fn

    return deco


def _repo(st: RepoState | None) -> RepoState | None:
    return st if st is not None and st.is_repo else None


def _branch(st: RepoState | None, default: str = "main") -> str:
    st = _repo(st)
    return (st.branch if st and st.branch else None) or default


def _remote(st: RepoState | None) -> str:
    st = _repo(st)
    if st and st.remotes and "origin" not in st.remotes:
        return next(iter(st.remotes))
    return "origin"


def _tab_list(text: str, start: int) -> list[str]:
    """Files git lists on tab-indented lines after a message."""
    out = []
    for line in text[start:].splitlines()[1:]:
        if line.startswith("\t") or line.startswith("        "):
            out.append(line.strip())
        elif out or line.strip():
            break
    return out


def _no_force_step() -> Step:
    return Step(
        "Don't use `git push --force` to get past this: it would delete the other commits from GitHub.",
    )


# ---------------------------------------------------------------- authentication and access


@error_rule(
    "auth_failed",
    r"Support for password authentication was removed",
    r"Authentication failed for '[^']+'",
    r"Invalid username or (?:password|token)",
    r"could not read Username for '[^']+'",
)
def _auth(m, text, st):
    return Finding(
        "auth_failed",
        "blocking",
        "GitHub didn't accept your login",
        "GitHub stopped accepting your account password for Git in 2021. When Git asks for a password it now needs "
        "a personal access token (a long generated password), or you can let the GitHub CLI or SSH keys handle "
        "logging in. Never paste a token into a chat, a file, or your code.",
        fix=[
            FixOption(
                "Easiest: log in with the GitHub CLI",
                [
                    Step("Install the GitHub CLI from https://cli.github.com (on macOS: brew install gh)"),
                    Step(
                        "Logs in through your browser and sets Git up to use that login; choose HTTPS when asked",
                        "gh auth login",
                    ),
                    Step("Run the command that failed again, for example", "git push"),
                ],
            ),
            FixOption(
                "Or use a personal access token",
                [
                    Step(
                        "On GitHub go to Settings > Developer settings > Personal access tokens and create one with access to this repository."
                    ),
                    Step(
                        "Run your command again and, when Git asks for a password, paste the token (it won't show as you type)."
                    ),
                    Step(
                        "If Git doesn't ask and fails straight away, an old password is saved: on macOS remove the github.com entry in "
                        "Keychain Access; on Windows remove git:https://github.com in Credential Manager > Windows Credentials."
                    ),
                ],
            ),
        ],
        learn_more=DOCS + "gitcredentials",
    )


def _https_url(st: RepoState | None) -> str:
    st = _repo(st)
    url = (st.remotes.get(_remote(st)) if st else "") or ""
    m = re.match(r"^(?:ssh://)?git@github\.com[:/](.+?)(?:\.git)?/?$", url)
    if m:
        return f"https://github.com/{m.group(1)}.git"
    return "https://github.com/<owner>/<repo>.git"


@error_rule("ssh_publickey", r"Permission denied \(publickey")
def _publickey(m, text, st):
    return Finding(
        "ssh_publickey",
        "blocking",
        "GitHub rejected your SSH key",
        "This repository's address uses SSH (it starts with git@github.com), and GitHub didn't accept any SSH key from "
        "this computer. An SSH key is a pair of files that proves who you are; either none exists yet, or it isn't "
        "added to your GitHub account.",
        fix=[
            FixOption(
                "Simplest: switch this repository to HTTPS and log in with the GitHub CLI",
                [
                    Step(
                        "Changes the address Git uses for GitHub to the HTTPS form",
                        f"git remote set-url {_remote(st)} {_https_url(st)}",
                    ),
                    Step("Logs in through your browser (install from https://cli.github.com)", "gh auth login"),
                ],
            ),
            FixOption(
                "Or set up an SSH key",
                [
                    Step(
                        "Creates a new key pair; press Enter to accept the defaults",
                        'ssh-keygen -t ed25519 -C "you@example.com"',
                    ),
                    Step(
                        "Copy the contents of the .pub file it created (~/.ssh/id_ed25519.pub) into GitHub > Settings > SSH and GPG keys."
                    ),
                    Step("Checks that GitHub now recognises you", "ssh -T git@github.com"),
                ],
            ),
        ],
        learn_more=BOOK + "Git-on-the-Server-Generating-Your-SSH-Public-Key",
    )


@error_rule("repo_not_found", r"remote: Repository not found", r"fatal: repository '[^']+' not found")
def _repo_not_found(m, text, st):
    st2 = _repo(st)
    details = [f"{k}: {v}" for k, v in st2.remotes.items()] if st2 else []
    return Finding(
        "repo_not_found",
        "blocking",
        "GitHub can't find that repository (or won't show it to you)",
        "Either the address has a typo, the repository was renamed or deleted, or it is private and the account you're "
        "logged in as doesn't have access. GitHub says 'not found' rather than 'forbidden' for private repositories.",
        details=details,
        details_label="Remote addresses",
        fix=[
            FixOption(
                "Check the address",
                [
                    Step("Shows the address this repository uses", "git remote -v"),
                    Step(
                        "If it's wrong, replaces it with the address from the repository's green Code button on GitHub",
                        f"git remote set-url {_remote(st)} <correct-url>",
                    ),
                ],
            ),
            FixOption(
                "Check access",
                [
                    Step(
                        "Make sure you're logged in as the right account and have accepted the invitation to the repository (for a class, accept the assignment link first)."
                    )
                ],
            ),
        ],
        learn_more=DOCS + "git-remote",
    )


@error_rule("push_forbidden", r"The requested URL returned error: 403", r"Permission to \S+ denied to \S+")
def _forbidden(m, text, st):
    return Finding(
        "push_forbidden",
        "blocking",
        "You're logged in, but not allowed to push to this repository",
        "GitHub knows who you are, but that account can't write to this repository. Usually the remote points at someone "
        "else's repository (for example the course's starter repository instead of your own copy), or your token "
        "doesn't have write access.",
        fix=[
            FixOption(
                "Point at your own repository",
                [
                    Step("Shows where Git is pushing to", "git remote -v"),
                    Step(
                        "Changes it to your own repository's address",
                        f"git remote set-url {_remote(st)} <your-repository-url>",
                    ),
                    Step("Pushes again", f"git push -u {_remote(st)} {_branch(st)}"),
                ],
            ),
            FixOption("Or log in as the right account", [Step("Logs in again through your browser", "gh auth login")]),
        ],
        learn_more=DOCS + "git-push",
    )


# ---------------------------------------------------------------- push and pull


@error_rule(
    "push_rejected_remote_ahead",
    r"\[rejected\].*\((?:fetch first|non-fast-forward)\)",
    r"Updates were rejected because the remote contains work that you do",
    r"Updates were rejected because the tip of your current branch is behind",
    r"Updates were rejected because a pushed branch tip is behind",
    family="push",
)
def _push_rejected(m, text, st):
    st2 = _repo(st)
    expl = (
        "GitHub has commits on this branch that you don't have yet (a teammate pushed, or you pushed from another "
        "computer or edited on the website). Git won't let you push until you've combined their work with yours."
    )
    note = ""
    if st2 and st2.ahead is not None and st2.behind is not None and st2.upstream:
        note = f"Right now you are {st2.ahead} ahead and {st2.behind} behind {st2.upstream}. " + st2.fetch_note()
    return Finding(
        "push_rejected_remote_ahead",
        "blocking",
        "Push rejected: GitHub has commits you don't have",
        expl,
        note=note,
        fix=[
            FixOption(
                "Get their commits, then push",
                [
                    Step("Downloads their commits and merges them with yours", "git pull --no-rebase"),
                    Step(
                        "If it reports conflicts, fix them (whygit will explain the state), then `git add` and `git commit`."
                    ),
                    Step("Uploads the combined result", "git push"),
                    _no_force_step(),
                ],
            )
        ],
        learn_more=DOCS + "git-push#_note_about_fast_forwards",
    )


@error_rule(
    "divergent_pull",
    r"You have divergent branches and need to specify how to reconcile them",
    r"Need to specify how to reconcile divergent branches",
    r"Not possible to fast-forward, aborting",
    family="pull",
)
def _divergent(m, text, st):
    return Finding(
        "divergent_pull",
        "blocking",
        "Pull stopped: Git wants you to choose how to combine your work",
        "Both you and GitHub have new commits on this branch. Git can combine them with a merge (adds one commit that "
        "joins the two) or a rebase (replays your commits on top of theirs), and it's asking which you want.",
        fix=[
            FixOption(
                "Merge (simplest, recommended if unsure)",
                [
                    Step("Pulls and merges this time", "git pull --no-rebase"),
                    Step(
                        "Optional: makes merging the default so you aren't asked again",
                        "git config --global pull.rebase false",
                    ),
                ],
            ),
            FixOption("Or rebase", [Step("Pulls and replays your commits on top of theirs", "git pull --rebase")]),
        ],
        learn_more=DOCS + "git-pull",
    )


@error_rule("unrelated_histories", r"refusing to merge unrelated histories", family="pull")
def _unrelated(m, text, st):
    b = _branch(st)
    r = _remote(st)
    return Finding(
        "unrelated_histories",
        "blocking",
        "Git refuses to combine two unrelated projects",
        "Your local repository and the one on GitHub don't share any starting commit. This almost always happens when "
        "the GitHub repository was created with a README or license, and you also ran `git init` and committed on your computer.",
        fix=[
            FixOption(
                "Combine them once",
                [
                    Step(
                        "Pulls the GitHub history and allows joining it to yours this one time",
                        f"git pull {r} {b} --no-rebase --allow-unrelated-histories",
                    ),
                    Step("If README.md or another file conflicts, fix it, then `git add` it and `git commit`."),
                    Step("Uploads the joined history and links the branch", f"git push -u {r} {b}"),
                    _no_force_step(),
                ],
            )
        ],
        learn_more=DOCS + "git-merge#Documentation/git-merge.txt---allow-unrelated-histories",
    )


@error_rule("remote_ref_missing", r"couldn't find remote ref (\S+)", family="pull")
def _remote_ref_missing(m, text, st):
    name = m.group(1)
    st2 = _repo(st)
    have = [b.split("/", 1)[1] for b in st2.remote_branches] if st2 else []
    alt = "main" if name == "master" else ("master" if name == "main" else "")
    guess = alt if (alt and (not have or alt in have)) else ""
    steps = [Step("Lists the branches the remote has (as of your last fetch)", "git branch -r")]
    if guess:
        steps.append(Step("Pulls the branch that probably exists instead", f"git pull {_remote(st)} {guess}"))
    return Finding(
        "remote_ref_missing",
        "blocking",
        f"The remote has no branch called '{name}'",
        "You asked for a branch that doesn't exist on the remote. A common cause: GitHub names the first branch "
        "'main' while older tutorials say 'master'.",
        fix=[FixOption("Use the right branch name", steps)],
        learn_more=DOCS + "git-pull",
    )


@error_rule("no_upstream_push", r"The current branch (\S+) has no upstream branch", family="upstream")
def _no_upstream_push(m, text, st):
    b = m.group(1)
    return Finding(
        "no_upstream",
        "blocking",
        f"Git doesn't know where to push '{b}' yet",
        "This branch isn't linked to a branch on GitHub (its 'upstream'), which is normal the first time you push it.",
        fix=[
            FixOption(
                "Push and link it",
                [
                    Step(
                        f"Uploads {b} and remembers where it goes, so next time `git push` is enough",
                        f"git push -u {_remote(st)} {b}",
                    )
                ],
            )
        ],
        learn_more=DOCS + "git-push",
    )


@error_rule("no_tracking_pull", r"There is no tracking information for the current branch", family="upstream")
def _no_tracking(m, text, st):
    b = _branch(st, "<branch>")
    r = _remote(st)
    st2 = _repo(st)
    if st2 and f"{r}/{b}" not in st2.remote_branches:
        steps = [
            Step(
                f"The remote doesn't have {b} yet (as of your last fetch); push it first and link it",
                f"git push -u {r} {b}",
            )
        ]
    else:
        steps = [
            Step(f"Links this branch to {r}/{b}", f"git branch --set-upstream-to={r}/{b}"),
            Step("Pulls again", "git pull"),
        ]
    return Finding(
        "no_upstream",
        "blocking",
        "Git doesn't know which branch to pull from",
        "This branch isn't linked to a branch on the remote (its 'upstream'), so plain `git pull` doesn't know what to fetch.",
        fix=[FixOption("Link it", steps)],
        learn_more=DOCS + "git-branch#Documentation/git-branch.txt---set-upstream-toltupstreamgt",
    )


@error_rule("src_refspec", r"src refspec (\S+) does not match any", family="push")
def _src_refspec(m, text, st):
    name = m.group(1)
    st2 = _repo(st)
    r = _remote(st)
    if st2 and st2.unborn:
        return Finding(
            "src_refspec",
            "blocking",
            "There's nothing to push yet: no commits",
            f"Git can't push '{name}' because you haven't made any commits, so the branch doesn't exist yet.",
            fix=[
                FixOption(
                    "Commit, then push",
                    [
                        Step("Stages your files (check `git status` first)", "git add ."),
                        Step("Makes the first commit", 'git commit -m "First commit"'),
                        Step("Uploads it", f"git push -u {r} {st2.branch or name}"),
                    ],
                )
            ],
            learn_more=DOCS + "git-push",
        )
    if st2 and st2.branch and st2.branch != name:
        cur = st2.branch
        return Finding(
            "src_refspec",
            "blocking",
            f"You don't have a branch called '{name}'; yours is '{cur}'",
            f"You asked Git to push '{name}', but your branch is named '{cur}' (older Git versions call the first branch "
            "'master', GitHub calls it 'main').",
            fix=[
                FixOption("Push the branch you have", [Step(f"Uploads {cur}", f"git push -u {r} {cur}")]),
                FixOption(
                    f"Or rename it to {name} first",
                    [
                        Step(f"Renames {cur} to {name}", f"git branch -m {cur} {name}"),
                        Step("Uploads it", f"git push -u {r} {name}"),
                    ],
                ),
            ],
            learn_more=DOCS + "git-branch",
        )
    return Finding(
        "src_refspec",
        "blocking",
        f"There's no local branch called '{name}' to push",
        "Either you haven't made a commit yet (so no branch exists), or your branch has a different name, such as 'master' instead of 'main'.",
        fix=[
            FixOption("Check", [Step("Shows your branch name and whether anything is committed", "git status")]),
            FixOption(
                "If nothing is committed",
                [
                    Step("Stages your files", "git add ."),
                    Step("Makes the first commit", 'git commit -m "First commit"'),
                    Step("Pushes", f"git push -u {r} {name}"),
                ],
            ),
            FixOption(
                "If your branch has another name",
                [
                    Step("Renames the current branch", f"git branch -m {name}"),
                    Step("Pushes", f"git push -u {r} {name}"),
                ],
            ),
        ],
        learn_more=DOCS + "git-push",
    )


@error_rule("push_too_large", r"RPC failed; HTTP 413", r"pack exceeds maximum allowed size", family="large")
def _too_large(m, text, st):
    st2 = _repo(st)
    if st2:
        f = R.large_file_over_limit(st2) or R.large_file_warning(st2)
        if f:
            return f
    return Finding(
        "push_too_large",
        "blocking",
        "The push was too big for the server",
        "The server stopped the upload because it was too large, usually because big data files were committed.",
        fix=[
            FixOption(
                "Find the big files",
                [Step("Run whygit in the repository to list large files waiting to be pushed", "whygit")],
            )
        ],
        learn_more=DOCS + "git-push",
    )


@error_rule(
    "large_file_rejected",
    r"GH001: Large files detected",
    r"exceeds GitHub's file size limit",
    family="large",
)
def _gh001(m, text, st):
    st2 = _repo(st)
    if st2:
        f = R.large_file_over_limit(st2)
        if f:
            return f
    files = [(g.group(1), g.group(2)) for g in re.finditer(r"File (.+?) is ([\d.]+ MB); this exceeds", text)]
    paths = [p for p, _ in files]
    b = _branch(st)
    return Finding(
        "large_file_over_limit",
        "blocking",
        "GitHub rejected the push: a file is over 100 MB",
        "GitHub refuses any push containing a file over 100 MB, and deleting the file in a new commit isn't enough "
        "because it is still inside an earlier commit. You need to rebuild your unpushed commits without it.",
        details=[f"{p}  ({s})" for p, s in files],
        details_label="Files GitHub rejected",
        fix=[
            FixOption(
                "Rebuild the unpushed commits without the file",
                [
                    Step(
                        "Undoes the commits GitHub hasn't accepted but keeps all their changes staged (your files are not touched)",
                        f"git reset --soft {_remote(st)}/{b}",
                    ),
                    Step(
                        "Takes the big file out of what will be committed, keeping it on disk",
                        f"git rm --cached {' '.join(q(p) for p in paths) or '<file>'}",
                    ),
                    Step("Add the file (or a pattern like data/*.csv) to .gitignore so it isn't added again."),
                    Step("Commits everything else again", 'git commit -m "Your message"'),
                    Step("Pushes", "git push"),
                ],
            )
        ],
        learn_more=DOCS + "git-rm",
    )


@error_rule("everything_up_to_date", r"^Everything up-to-date", family="push")
def _up_to_date(m, text, st):
    return Finding(
        "everything_up_to_date",
        "info",
        "Nothing new to push",
        "Every commit you have is already on the remote. If a change is missing on GitHub, it probably hasn't been "
        "committed yet: pushing only sends commits, not edited files.",
        fix=[
            FixOption(
                "Commit your changes first",
                [
                    Step("Shows changed files that aren't committed", "git status"),
                    Step("Stages them", "git add <file>"),
                    Step("Commits", 'git commit -m "Describe the change"'),
                    Step("Pushes", "git push"),
                ],
            )
        ],
        learn_more=DOCS + "git-push",
    )


# ---------------------------------------------------------------- local changes and paths


@error_rule(
    "local_changes_overwritten",
    r"Your local changes to the following files would be overwritten by ([\w-]+)",
    r"cannot (?:pull with rebase|rebase): You have unstaged changes",
    r"Your local changes would be overwritten by ([\w-]+)",
)
def _overwritten(m, text, st):
    files = _tab_list(text, m.start())
    st2 = _repo(st)
    if not files and st2:
        files = [e.path for e in st2.unstaged]
    op = m.group(1) if m.groups() and m.group(1) else "the command"
    paths = " ".join(q(f) for f in files[:6]) or "<file>"
    return Finding(
        "local_changes_overwritten",
        "blocking",
        "You have uncommitted changes that would be overwritten",
        f"You've edited files that aren't committed yet, and {op} would replace them. Git stopped so your edits aren't lost.",
        details=files,
        details_label="Files with uncommitted changes",
        fix=[
            FixOption(
                "Keep the changes by committing them",
                [
                    Step("Stages your edits", f"git add {paths}"),
                    Step("Commits them", 'git commit -m "Work in progress"'),
                    Step("Then run your command again."),
                ],
            ),
            FixOption(
                "Or set them aside for a moment",
                [
                    Step("Saves your edits away and cleans the files (nothing is lost)", "git stash"),
                    Step("Run your command again."),
                    Step("Brings your edits back", "git stash pop"),
                ],
            ),
            FixOption(
                "Or throw the edits away",
                [
                    Step(
                        "Restores the files to the last commit",
                        f"git restore {paths}",
                        destructive=True,
                        warning="Your uncommitted edits to these files are permanently lost.",
                    )
                ],
            ),
        ],
        learn_more=DOCS + "git-stash",
    )


@error_rule("untracked_overwritten", r"untracked working tree files would be (?:overwritten|removed) by ([\w-]+)")
def _untracked_overwritten(m, text, st):
    files = _tab_list(text, m.start())
    paths = " ".join(q(f) for f in files[:6]) or "<file>"
    return Finding(
        "untracked_overwritten",
        "blocking",
        "Files you haven't committed are in the way",
        f"You have files that Git isn't tracking yet, and the {m.group(1)} would put tracked files with the same names in their place.",
        details=files,
        details_label="Files in the way",
        fix=[
            FixOption(
                "Move them aside",
                [
                    Step("Makes a backup folder next to the project", "mkdir ../whygit-backup"),
                    Step("Moves the files there (macOS/Linux; on Windows use move)", f"mv {paths} ../whygit-backup/"),
                    Step("Run your command again, then compare with the backup."),
                ],
            )
        ],
        learn_more=DOCS + "git-checkout",
    )


@error_rule(
    "pathspec_no_match",
    r"pathspec '([^']+)' did not match any file\(s\) known to git",
    r"fatal: pathspec '([^']+)' did not match any files",
    r"fatal: invalid reference: (\S+)",
)
def _pathspec(m, text, st):
    name = m.group(1)
    st2 = _repo(st)
    is_add = "did not match any files" in m.group(0)
    if is_add:
        return Finding(
            "pathspec_no_match",
            "blocking",
            f"There's no file called '{name}' here",
            "Git couldn't find that file. Check the spelling and capital letters, which folder you're in, and put quotes "
            "around names with spaces.",
            fix=[
                FixOption(
                    "Check the name",
                    [
                        Step("Lists changed and new files with their exact names", "git status"),
                        Step("Adds the file using the exact name shown", f'git add "{name}"'),
                    ],
                )
            ],
            learn_more=DOCS + "git-add",
        )
    candidates: list[str] = []
    remote_match = ""
    if st2:
        names = st2.local_branches + [b.split("/", 1)[1] for b in st2.remote_branches if "/" in b]
        candidates = difflib.get_close_matches(name, sorted(set(names)), n=3, cutoff=0.6)
        if any(b.split("/", 1)[-1] == name for b in st2.remote_branches):
            remote_match = name
    steps = [Step("Lists all branches, including ones on the remote", "git branch -a")]
    if remote_match:
        steps.append(Step("Creates a local copy of the remote branch and switches to it", f"git switch {name}"))
    else:
        steps.insert(
            0,
            Step(
                "Downloads the latest list of branches (it only updates your local copy of GitHub's branches)",
                "git fetch",
            ),
        )
        steps.append(Step("Switches to the branch once it shows up", f"git switch {name}"))
    for c in candidates:
        if c != name:
            steps.append(Step(f"Did you mean '{c}'?", f"git switch {c}"))
    return Finding(
        "pathspec_no_match",
        "blocking",
        f"Git doesn't know a branch or file called '{name}'",
        "There's no branch with that name on this computer yet. Check the spelling, or if the branch was just made on GitHub, "
        "fetch first so your computer hears about it.",
        fix=[FixOption("Find the branch", steps)],
        learn_more=DOCS + "git-switch",
    )


@error_rule("remote_exists", r"remote (\S+) already exists")
def _remote_exists(m, text, st):
    name = m.group(1).rstrip(".")
    st2 = _repo(st)
    details = [f"{name}: {st2.remotes[name]}"] if st2 and name in st2.remotes else []
    return Finding(
        "remote_exists",
        "info",
        f"A remote called '{name}' is already set",
        "This repository already has an address saved under that name, usually because it was cloned or you ran "
        "`git remote add` before. You can keep it or change where it points.",
        details=details,
        details_label="Current address",
        fix=[
            FixOption(
                "Check or change it",
                [
                    Step("Shows the saved addresses", "git remote -v"),
                    Step("Changes the address if it's wrong", f"git remote set-url {name} <new-url>"),
                ],
            )
        ],
        learn_more=DOCS + "git-remote",
    )


@error_rule("no_such_remote", r"fatal: '([^']+)' does not appear to be a git repository")
def _no_such_remote(m, text, st):
    name = m.group(1)
    st2 = _repo(st)
    if "/" not in name and ":" not in name and "\\" not in name:
        has = ", ".join(st2.remotes) if st2 and st2.remotes else "none"
        return Finding(
            "no_remote",
            "blocking",
            f"There's no remote called '{name}'",
            f"Git doesn't have an address saved under the name '{name}' (remotes set here: {has}). Add one before pushing or pulling.",
            fix=[
                FixOption(
                    "Add the remote",
                    [
                        Step("Saves GitHub's address under that name", f"git remote add {name} <repository-url>"),
                        Step("Pushes and links your branch", f"git push -u {name} {_branch(st)}"),
                    ],
                )
            ],
            learn_more=DOCS + "git-remote",
        )
    return Finding(
        "repo_not_found",
        "blocking",
        "That address isn't a Git repository",
        "Git looked at the address you gave and found no repository there. Check the address for typos.",
        fix=[FixOption("Check the address", [Step("Shows the addresses this repository uses", "git remote -v")])],
        learn_more=DOCS + "git-remote",
    )


@error_rule("clone_dest_exists", r"destination path '([^']+)' already exists and is not an empty directory")
def _clone_exists(m, text, st):
    d = m.group(1)
    return Finding(
        "clone_dest_exists",
        "info",
        f"A folder called '{d}' already exists",
        "Clone makes a new folder and won't put a repository into one that already has files. You may have cloned it already.",
        fix=[
            FixOption(
                "If it's the same project",
                [Step("Moves into it", f"cd {q(d)}"), Step("Gets the latest changes", "git pull")],
            ),
            FixOption(
                "Or clone into a new folder name",
                [Step("Clones into a different folder", f"git clone <repository-url> {q(d + '-2')}")],
            ),
        ],
        learn_more=DOCS + "git-clone",
    )


# ---------------------------------------------------------------- state-backed errors


@error_rule("not_a_repo", r"not a git repository")
def _not_repo(m, text, st):
    if st is not None and not st.is_repo:
        f = R.not_a_repo(st) or R.inside_git_dir(st) or R.bare_repo(st)
        if f:
            return f
    return Finding(
        "not_a_repo",
        "blocking",
        "That folder is not a Git repository",
        "Git commands only work inside a project folder that was cloned or set up with `git init`. You're probably in "
        "the wrong folder (often one level above the project).",
        fix=[
            FixOption(
                "Move into the project",
                [Step("Shows where you are", "pwd"), Step("Moves into the project folder", "cd <project-folder>")],
            ),
            FixOption(
                "Or get the project", [Step("Downloads the repository into a new folder", "git clone <repository-url>")]
            ),
        ],
        learn_more=DOCS + "git-init",
    )


@error_rule("dubious_ownership", r"detected dubious ownership in repository at '([^']+)'")
def _dubious(m, text, st):
    return R.dubious_finding(m.group(1))


@error_rule(
    "missing_identity",
    r"Please tell me who you are",
    r"Author identity unknown",
    r"unable to auto-detect email address",
    r"empty ident name",
)
def _identity(m, text, st):
    st2 = _repo(st)
    missing = [k for k, v in (("user.name", st2.user_name), ("user.email", st2.user_email)) if not v] if st2 else None
    f = R.identity_finding(missing or None)
    f.severity = "blocking"
    return f


@error_rule("index_lock", r"Unable to create '([^']+index\.lock)': File exists")
def _lock(m, text, st):
    return R.index_lock_finding(m.group(1))


def _state_conflict(st: RepoState | None) -> Finding | None:
    st2 = _repo(st)
    if not st2:
        return None
    for fn in (
        R.rebase_in_progress,
        R.cherry_pick_in_progress,
        R.revert_in_progress,
        R.am_in_progress,
        R.merge_conflict,
        R.merge_resolved,
    ):
        f = fn(st2)
        if f:
            return f
    return None


@error_rule(
    "merge_conflict",
    r"CONFLICT \([^)]+\): Merge conflict in (.+)",
    r"Automatic merge failed; fix conflicts",
    r"you need to resolve your current index first",
    r"(?:Pulling|Committing|Merging|Reverting|Cherry-picking) is not possible because you have unmerged files",
    r"could not apply [0-9a-f]+",
    family="conflict",
)
def _conflict(m, text, st):
    f = _state_conflict(st)
    if f:
        return f
    files = [g.group(1).strip() for g in re.finditer(r"CONFLICT \([^)]+\): Merge conflict in (.+)", text)]
    return Finding(
        "merge_conflict",
        "blocking",
        "Git stopped because of a conflict",
        "Two sets of changes touched the same lines, and Git needs you to decide what the result should be. "
        "Nothing is lost while you decide.",
        details=files,
        details_label="Conflicted files",
        fix=[
            FixOption(
                "Resolve it",
                [
                    R._edit_step(),
                    Step("Marks the files as resolved", f"git add {' '.join(q(f) for f in files[:6]) or '<file>'}"),
                    Step("Finishes (for a rebase use `git rebase --continue` instead)", "git commit --no-edit"),
                ],
            ),
            FixOption(
                "Or cancel",
                [Step("Goes back to before the merge (or use git rebase --abort for a rebase)", "git merge --abort")],
            ),
        ],
        learn_more=DOCS + "git-merge#_how_to_resolve_conflicts",
    )


@error_rule("merge_unfinished", r"You have not concluded your merge \(MERGE_HEAD exists\)", family="conflict")
def _merge_unfinished(m, text, st):
    f = _state_conflict(st)
    if f:
        return f
    return Finding(
        "merge_resolved",
        "blocking",
        "An earlier merge isn't finished",
        "You started a merge and haven't made the merge commit yet, so Git won't start anything new.",
        fix=[
            FixOption("Finish it", [Step("Records the merge", "git commit --no-edit")]),
            FixOption("Or cancel it", [Step("Goes back to before the merge", "git merge --abort")]),
        ],
        learn_more=DOCS + "git-merge",
    )


@error_rule(
    "rebase_exists",
    r"already a rebase-(?:merge|apply) directory",
    r"It seems that there is already a rebase",
    family="conflict",
)
def _rebase_exists(m, text, st):
    f = _state_conflict(st)
    if f:
        return f
    return Finding(
        "rebase_in_progress",
        "blocking",
        "A rebase is already in progress",
        "An earlier rebase was never finished or cancelled, so Git won't start another.",
        fix=[
            FixOption("Continue it", [Step("Carries on with the earlier rebase", "git rebase --continue")]),
            FixOption("Or cancel it", [Step("Goes back to before it started", "git rebase --abort")]),
        ],
        learn_more=DOCS + "git-rebase",
    )


@error_rule("detached_head", r"You are in 'detached HEAD' state", r"HEAD detached at", r"Not currently on any branch")
def _detached(m, text, st):
    st2 = _repo(st)
    if st2:
        f = R.detached_head(st2)
        if f:
            return f
    return Finding(
        "detached_head",
        "warning",
        "You're not on a branch (detached HEAD)",
        "You're looking at a specific commit rather than a branch. That's fine for looking around, but commits made here "
        "don't belong to any branch and are easy to lose.",
        fix=[
            FixOption(
                "Keep any work you did here",
                [Step("Creates a branch at this point and moves onto it", "git switch -c <new-branch-name>")],
            ),
            FixOption("Or go back to your branch", [Step("Returns to main", "git switch main")]),
        ],
        learn_more=DOCS + "git-checkout#_detached_head",
    )


@error_rule("diverged", r"have diverged,\s*and have (\d+) and (\d+) different commits", family="status")
def _diverged(m, text, st):
    st2 = _repo(st)
    if st2:
        f = R.diverged(st2)
        if f:
            return f
    return Finding(
        "diverged",
        "warning",
        "Your branch and the remote have diverged",
        f"You have {m.group(1)} commit(s) the remote doesn't, and it has {m.group(2)} you don't. Combine them before pushing.",
        fix=[
            FixOption(
                "Combine them",
                [
                    Step("Downloads and merges their commits", "git pull --no-rebase"),
                    Step("Uploads the result", "git push"),
                ],
            )
        ],
        learn_more=DOCS + "git-pull",
    )


@error_rule("nested_repo", r"adding embedded git repository: (.+)")
def _embedded(m, text, st):
    st2 = _repo(st)
    if st2:
        f = R.nested_repo(st2)
        if f:
            return f
    p = m.group(1).strip()
    return Finding(
        "nested_repo",
        "warning",
        f"'{p}' is a separate repository inside yours",
        "That folder has its own .git folder, so Git added it as a single link rather than its files. On GitHub it will "
        "show as an empty folder.",
        fix=[
            FixOption(
                "Add its files normally",
                [
                    Step("Undoes the add without touching the files", f"git rm --cached {q(p)}"),
                    Step(
                        "Renames the inner .git folder (macOS/Linux) so the files become ordinary files",
                        f"mv {q(p + '/.git')} {q(p + '/git-backup')}",
                    ),
                    Step("Adds the files", f"git add {q(p)}"),
                ],
            )
        ],
        learn_more=DOCS + "gitsubmodules",
    )


@error_rule("line_endings", r"\b(?:LF|CRLF) will be replaced by (?:CRLF|LF)")
def _line_endings(m, text, st):
    return Finding(
        "line_endings",
        "info",
        "Just a line-ending warning, nothing is broken",
        "Windows and macOS end lines of text differently (CRLF vs LF), and Git is telling you it will convert them. "
        "It's harmless; your command still worked.",
        fix=[
            FixOption(
                "Optional: make it consistent for the whole team",
                [
                    Step("Create a file called .gitattributes in the project root containing the line:  * text=auto"),
                    Step("Commits it", 'git add .gitattributes && git commit -m "Normalise line endings"'),
                ],
            )
        ],
        learn_more=DOCS + "gitattributes#_end_of_line_conversion",
    )


@error_rule(
    "network",
    r"Could not resolve host",
    r"Failed to connect to \S+",
    r"Connection timed out",
    r"Could not resolve hostname",
)
def _network(m, text, st):
    return Finding(
        "network",
        "blocking",
        "Git couldn't reach the server",
        "This is a network problem, not a problem with your repository: no internet connection, a typo in the address, "
        "or a network (some campus or public Wi-Fi) blocking the connection.",
        fix=[
            FixOption(
                "Check the connection",
                [
                    Step("Open https://github.com in a browser to check you're online."),
                    Step("Shows the address Git is trying to reach", "git remote -v"),
                    Step("Try again on another network if it still fails."),
                ],
            )
        ],
        learn_more=DOCS + "git-remote",
    )


@error_rule("push_failed", r"failed to push some refs", family="push")
def _push_failed(m, text, st):
    st2 = _repo(st)
    if st2:
        for fn in (R.large_file_over_limit, R.diverged, R.behind, R.unborn_branch):
            f = fn(st2)
            if f:
                return f
    return Finding(
        "push_failed",
        "blocking",
        "The push failed",
        "Git couldn't upload your commits. The lines just before 'failed to push some refs' say why; paste the whole "
        "output to get a specific explanation.",
        fix=[FixOption("Look closer", [Step("Shows your branch and whether you're ahead or behind", "git status")])],
        learn_more=DOCS + "git-push",
    )


# ---------------------------------------------------------------- matching


def match_errors(text: str, st: RepoState | None = None) -> list[tuple[Finding, str]]:
    """Return (finding, matched line) for every rule the text matches, one per family."""
    out: list[tuple[Finding, str]] = []
    families: set[str] = set()
    for er in ERROR_RULES:
        if er.family in families:
            continue
        for pat in er.patterns:
            m = pat.search(text)
            if not m:
                continue
            if er.id == "push_failed" and out:
                break
            finding = er.build(m, text, st)
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.end())
            line = text[line_start : line_end if line_end != -1 else len(text)].strip()
            out.append((finding, redact(line)[:300]))
            families.add(er.family)
            break
    return out
