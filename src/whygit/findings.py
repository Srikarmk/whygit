from __future__ import annotations

from dataclasses import dataclass, field

SEVERITIES = ("blocking", "warning", "info")
SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITIES)}

DOCS = "https://git-scm.com/docs/"
BOOK = "https://git-scm.com/book/en/v2/"


@dataclass
class Step:
    """One thing for the person to do. command is None for manual steps
    such as editing a file."""

    does: str
    command: str | None = None
    destructive: bool = False
    warning: str | None = None

    def to_dict(self) -> dict:
        d: dict = {"does": self.does}
        if self.command:
            d["command"] = self.command
        if self.destructive:
            d["destructive"] = True
        if self.warning:
            d["warning"] = self.warning
        return d


@dataclass
class FixOption:
    title: str
    steps: list[Step]

    def to_dict(self) -> dict:
        return {"title": self.title, "steps": [s.to_dict() for s in self.steps]}


@dataclass
class Finding:
    rule_id: str
    severity: str
    title: str
    explanation: str
    fix: list[FixOption] = field(default_factory=list)
    learn_more: str = ""
    details: list[str] = field(default_factory=list)
    details_label: str = ""
    note: str = ""

    def to_dict(self, max_details: int = 10) -> dict:
        d: dict = {
            "rule": self.rule_id,
            "severity": self.severity,
            "title": self.title,
            "explanation": self.explanation,
        }
        if self.details:
            shown = self.details[:max_details]
            if len(self.details) > max_details:
                shown = shown + [f"... and {len(self.details) - max_details} more"]
            d["details"] = {"label": self.details_label or "Files", "items": shown}
        if self.note:
            d["note"] = self.note
        if self.fix:
            d["fix"] = [f.to_dict() for f in self.fix]
            first = d["fix"][0]
            if first["title"].startswith("Or "):
                first["title"] = first["title"][3].upper() + first["title"][4:]
        if self.learn_more:
            d["learn_more"] = self.learn_more
        return d


def sort_findings(findings: list[Finding], order: dict[str, int] | None = None) -> list[Finding]:
    order = order or {}
    return sorted(findings, key=lambda f: (SEVERITY_RANK.get(f.severity, 9), order.get(f.rule_id, 999)))


def q(path: str) -> str:
    """Quote a path for a shell command when it needs it. Double quotes work in
    bash, zsh, PowerShell and cmd for ordinary file names."""
    if path and all(c.isalnum() or c in "._-/+@:" for c in path):
        return path
    return '"' + path.replace('"', '\\"') + '"'
