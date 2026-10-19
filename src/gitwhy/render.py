"""Plain-text rendering for the terminal."""

from __future__ import annotations

import os
import shutil
import sys
import textwrap

LABELS = {"blocking": "BLOCKING", "warning": "WARNING", "info": "INFO"}


class Style:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def _c(self, code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if self.enabled else s

    def bold(self, s):
        return self._c("1", s)

    def dim(self, s):
        return self._c("2", s)

    def cmd(self, s):
        return self._c("36", s)

    def sev(self, sev, s):
        return self._c({"blocking": "1;31", "warning": "1;33", "info": "1;34"}.get(sev, "1"), s)

    def warn(self, s):
        return self._c("1;31", s)


def want_color(stream=None, force_off: bool = False) -> bool:
    stream = stream or sys.stdout
    if force_off or os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    if not hasattr(stream, "isatty") or not stream.isatty():
        return False
    if os.name == "nt":
        return _enable_windows_vt()
    return True


def _enable_windows_vt() -> bool:
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def _width() -> int:
    return max(60, min(100, shutil.get_terminal_size((88, 24)).columns - 2))


def _wrap(text: str, indent: str, width: int) -> list[str]:
    return textwrap.wrap(
        text,
        width=width,
        initial_indent=indent,
        subsequent_indent=indent,
        break_on_hyphens=False,
        break_long_words=False,
    ) or [indent]


def finding_lines(f: dict, s: Style, width: int) -> list[str]:
    out = [s.sev(f["severity"], f"[{LABELS.get(f['severity'], f['severity'].upper())}]") + " " + s.bold(f["title"])]
    out += _wrap(f["explanation"], "  ", width)
    if f.get("details"):
        out.append("  " + f["details"]["label"] + ":")
        for item in f["details"]["items"]:
            out.append("    - " + item)
    if f.get("note"):
        out += _wrap(f["note"], "  ", width)
    fixes = f.get("fix") or []
    if fixes:
        out.append("  " + s.bold("How to fix:"))
        for i, opt in enumerate(fixes):
            title = opt["title"] if i == 0 else opt["title"]
            out.append("    " + title + ":")
            for n, step in enumerate(opt["steps"], 1):
                num = f"{n}. "
                pad = "      " + " " * len(num)
                if step.get("command"):
                    out.append("      " + num + s.cmd(step["command"]))
                    out += _wrap(step["does"], pad, width)
                else:
                    wrapped = _wrap(step["does"], pad, width)
                    wrapped[0] = "      " + num + wrapped[0].lstrip()
                    out += wrapped
                if step.get("warning"):
                    out += [
                        s.warn(x) if j == 0 else x
                        for j, x in enumerate(_wrap("Warning: " + step["warning"], pad, width))
                    ]
    if f.get("learn_more"):
        out.append("  " + s.dim("Learn more: " + f["learn_more"]))
    return out


def render_diagnosis(report: dict, s: Style) -> str:
    width = _width()
    head = "gitwhy: " + report.get("repo_root", report["path"])
    if report.get("branch"):
        head += f" (branch {report['branch']})"
    elif report.get("head"):
        head += f" ({report['head']})"
    lines = [s.bold(head)]
    if report.get("repo_root") and report["repo_root"] != report["path"]:
        lines.append(s.dim("Run the commands below from the repository folder above; file paths are relative to it."))
    lines.append("")
    findings = report.get("findings", [])
    if not findings:
        lines.append("No problems found. Run `gitwhy status` for a plain summary of the repository.")
        return "\n".join(lines)
    for f in findings:
        lines += finding_lines(f, s, width)
        lines.append("")
    lines.append(s.dim(report["summary"] + ". gitwhy never runs these commands for you; copy the ones you want."))
    return "\n".join(lines)


def render_state(state: dict, s: Style) -> str:
    width = _width()
    head = "gitwhy status: " + state.get("repo_root", state["path"])
    lines = [s.bold(head), ""]
    for line in state.get("summary", []):
        lines += _wrap(line, "", width)
    ch = state.get("changes") or {}
    labels = {
        "conflicted": "Conflicted",
        "staged": "Staged",
        "modified_not_staged": "Changed, not staged",
        "untracked": "Untracked",
    }
    for key, label in labels.items():
        if ch.get(key):
            lines.append("")
            lines.append(label + ":")
            lines += ["  " + p for p in ch[key]]
    if state.get("remotes"):
        lines.append("")
        lines.append("Remotes:")
        lines += [f"  {k}  {v}" for k, v in state["remotes"].items()]
    return "\n".join(lines)


def render_explanation(res: dict, s: Style) -> str:
    width = _width()
    lines: list[str] = []
    if res.get("recognised"):
        for f in res["matches"]:
            if f.get("matched_line"):
                lines.append(s.dim("Matched: " + f["matched_line"]))
            lines += finding_lines(f, s, width)
            lines.append("")
        extra = res.get("also_in_this_repo") or []
        if extra:
            lines.append(s.bold("Also found in this repository:"))
            lines.append("")
            for f in extra:
                lines += finding_lines(f, s, width)
                lines.append("")
        lines.append(s.dim("gitwhy never runs these commands for you; copy the ones you want."))
    else:
        lines += _wrap(res.get("message", "Not recognised."), "", width)
        lines.append("")
        diag = res.get("diagnosis")
        if diag:
            for f in diag:
                lines += finding_lines(f, s, width)
                lines.append("")
        elif diag is not None:
            lines.append("No problems found in the repository either.")
    return "\n".join(lines).rstrip() + "\n"
