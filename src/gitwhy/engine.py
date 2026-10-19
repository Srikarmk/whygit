"""Public entry points shared by the CLI and the MCP server. Everything returned
here is plain data (dicts, lists, strings) with credentials redacted."""

from __future__ import annotations

import os

from .errors import match_errors
from .findings import Finding, sort_findings
from .gitcmd import redact, redact_obj
from .rules import RULES, rule_order
from .state import PathNotFound, RepoState, ago, collect

__all__ = ["diagnose", "explain_state", "explain_error", "findings_for", "PathNotFound"]


def findings_for(st: RepoState) -> list[Finding]:
    found = []
    quiet = set()
    for r in RULES:
        f = r.detect(st)
        if f is not None:
            found.append(f)
            if r.quiet:
                quiet.add(r.id)
    if any(f.rule_id == "home_repo" and f.severity == "blocking" for f in found):
        # Everything else is noise (and some advice, like `git add .`, would be harmful).
        found = [f for f in found if f.rule_id in ("home_repo", "index_lock")]
    if any(f.severity in ("blocking", "warning") for f in found):
        found = [f for f in found if f.rule_id not in quiet]
    return sort_findings(found, rule_order())


def _summary_counts(findings: list[Finding]) -> str:
    if not findings:
        return "No problems found."
    parts = []
    for sev in ("blocking", "warning", "info"):
        n = sum(1 for f in findings if f.severity == sev)
        if n:
            parts.append(f"{n} {sev}")
    return ", ".join(parts)


def _where(st: RepoState) -> dict:
    d: dict = {"path": str(st.path)}
    if st.toplevel is not None:
        d["repo_root"] = str(st.toplevel)
    if st.is_repo:
        if st.detached:
            d["branch"] = None
            d["head"] = f"detached at {(st.head_oid or '')[:7]}"
        else:
            d["branch"] = st.branch
    return d


def diagnose(path: str | os.PathLike | None = None) -> dict:
    st = collect(path)
    findings = findings_for(st)
    out = _where(st)
    out["summary"] = _summary_counts(findings)
    out["findings"] = [f.to_dict() for f in findings]
    return redact_obj(out)


def _names(entries, limit=8) -> list[str]:
    names = [e.path for e in entries]
    if len(names) > limit:
        return names[:limit] + [f"... and {len(names) - limit} more"]
    return names


def explain_state(path: str | os.PathLike | None = None) -> dict:
    st = collect(path)
    out = _where(st)
    lines: list[str] = []
    if not st.git_available:
        out["is_repo"] = False
        out["summary"] = ["Git is not installed or not on PATH."]
        return out
    if not st.is_repo:
        out["is_repo"] = False
        reason = {
            "not_found": "This folder is not inside a Git repository.",
            "dubious": "Git refuses to read this repository because another user owns the folder.",
            "inside_git_dir": "You are inside the hidden .git folder.",
            "bare": "This is a bare repository (history only, no working files).",
        }.get(st.not_repo_reason, "Git could not read this folder: " + st.error_text)
        out["summary"] = [reason]
        return redact_obj(out)
    out["is_repo"] = True
    if "rebase" in st.in_progress:
        name = f"branch '{st.rebase_head_name}'" if st.rebase_head_name else "a branch"
        step = f" (step {st.rebase_step})" if st.rebase_step else ""
        lines.append(f"Rebasing {name}{step}; HEAD is detached until the rebase finishes.")
    elif st.detached:
        lines.append(f"Not on a branch: HEAD is detached at commit {(st.head_oid or '')[:7]}.")
    elif st.unborn:
        lines.append(f"On branch '{st.branch}', which has no commits yet.")
    else:
        lines.append(f"On branch '{st.branch}'.")
    if st.last_commit:
        lines.append(f"Last commit: {st.last_commit}.")
        out["last_commit"] = st.last_commit
    if st.upstream:
        out["upstream"] = st.upstream
        if st.upstream_gone:
            lines.append(f"It tracks {st.upstream}, which no longer exists on the remote.")
        else:
            out["ahead"], out["behind"] = st.ahead, st.behind
            if st.ahead == 0 and st.behind == 0:
                rel = "up to date with"
            elif st.ahead and st.behind:
                rel = f"{st.ahead} ahead and {st.behind} behind"
            elif st.ahead:
                rel = f"{st.ahead} ahead of"
            else:
                rel = f"{st.behind} behind"
            lines.append(f"It is {rel} {st.upstream}. {st.fetch_note()}")
        out["last_fetch"] = ago(st.last_fetch) if st.last_fetch else "never (only cloned)"
    elif not st.detached:
        lines.append("It is not linked to a remote branch (no upstream).")
    out["remotes"] = dict(st.remotes)
    if not st.remotes:
        lines.append("No remote is set, so nothing is connected to GitHub.")
    op = [o for o in st.in_progress]
    if op:
        out["in_progress"] = op
        lines.append("In progress: " + ", ".join(op) + ".")
    changes = {
        "conflicted": _names(st.unmerged),
        "staged": _names(st.staged),
        "modified_not_staged": _names(st.unstaged),
        "untracked": _names(st.untracked),
    }
    out["changes"] = {k: v for k, v in changes.items() if v}
    counts = [
        (len(st.unmerged), "conflicted"),
        (len(st.staged), "staged for the next commit"),
        (len(st.unstaged), "changed but not staged"),
        (len(st.untracked), "new and untracked"),
    ]
    bits = [f"{n} {label}" for n, label in counts if n]
    lines.append(("Files: " + ", ".join(bits) + ".") if bits else "No uncommitted changes.")
    if st.stash_count:
        out["stashes"] = st.stash_count
        lines.append(
            f"{st.stash_count} stash entr{'y' if st.stash_count == 1 else 'ies'} saved (see `git stash list`)."
        )
    out["summary"] = lines
    return redact_obj(out)


def explain_error(error_text: str, path: str | os.PathLike | None = None) -> dict:
    text = error_text or ""
    st = collect(path) if path not in (None, "") else None
    matches = match_errors(text, st)
    out: dict = {"recognised": bool(matches)}
    if st is not None:
        out.update(_where(st))
    if matches:
        out["matches"] = [dict(f.to_dict(), matched_line=line) for f, line in matches]
        # Add anything else urgent in the repository that the error didn't mention.
        if st is not None and st.is_repo:
            seen = {f.rule_id for f, _ in matches}
            extra = [f.to_dict() for f in findings_for(st) if f.severity == "blocking" and f.rule_id not in seen]
            if extra:
                out["also_in_this_repo"] = extra
    else:
        out["message"] = (
            "gitwhy doesn't recognise this message. Here is what it can see in the repository instead."
            if st is not None
            else "gitwhy doesn't recognise this message. Pass the repository path to get a diagnosis of its current state."
        )
        if st is not None:
            out["diagnosis"] = [f.to_dict() for f in findings_for(st)]
        out["error_excerpt"] = redact(text.strip())[:500]
    return redact_obj(out)
