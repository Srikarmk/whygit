"""Command line front end: gitwhy, gitwhy status, gitwhy explain, gitwhy mcp."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .engine import PathNotFound, diagnose, explain_error, explain_state
from .render import Style, render_diagnosis, render_explanation, render_state, want_color

EPILOG = """examples:
  gitwhy                          explain what's going on in this repository
  gitwhy status                   plain summary: branch, upstream, changes
  gitwhy explain "fatal: refusing to merge unrelated histories"
  git push 2>&1 | gitwhy explain -
  gitwhy mcp                      run as an MCP server (for Claude Code, Cursor, Claude Desktop)

gitwhy only reads your repository. It never runs the fixes it suggests."""


def _common(p: argparse.ArgumentParser, suppress: bool) -> None:
    d = argparse.SUPPRESS if suppress else None
    p.add_argument(
        "--path", "-C", default=d if suppress else ".", help="repository folder to look at (default: current folder)"
    )
    p.add_argument("--json", action="store_true", default=d if suppress else False, help="print JSON instead of text")
    p.add_argument("--no-color", action="store_true", default=d if suppress else False, help="never use colour")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gitwhy",
        description="Explains what state your Git repository is in and how to fix it, in plain English.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"gitwhy {__version__}")
    _common(parser, suppress=False)
    sub = parser.add_subparsers(dest="command", metavar="command")
    p = sub.add_parser("diagnose", help="list problems, most urgent first (the default)")
    _common(p, suppress=True)
    p = sub.add_parser("status", help="plain summary of the repository")
    _common(p, suppress=True)
    p = sub.add_parser("explain", help="explain a git error message ('-' reads it from stdin)")
    p.add_argument("text", nargs="*", help="the error text, or - to read from stdin")
    _common(p, suppress=True)
    sub.add_parser("mcp", help="run the MCP server over stdio")
    return parser


def _setup_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _setup_stdout()
    args = build_parser().parse_args(argv)
    if args.command == "mcp":
        from .server import main as server_main

        server_main()
        return 0
    style = Style(want_color(force_off=args.no_color or args.json))
    try:
        if args.command == "status":
            res = explain_state(args.path)
            _emit(res, args.json, lambda r: render_state(r, style))
            return 0
        if args.command == "explain":
            text = " ".join(args.text)
            if text.strip() in ("", "-"):
                if sys.stdin is not None and sys.stdin.isatty():
                    print(
                        "Paste the error text, then press Ctrl-D (macOS/Linux) or Ctrl-Z then Enter (Windows):",
                        file=sys.stderr,
                    )
                text = sys.stdin.read() if sys.stdin is not None else ""
            if not text.strip():
                print("gitwhy explain: no error text given.", file=sys.stderr)
                return 2
            res = explain_error(text, args.path)
            _emit(res, args.json, lambda r: render_explanation(r, style))
            return 0 if res.get("recognised") else 3
        res = diagnose(args.path)
        _emit(res, args.json, lambda r: render_diagnosis(r, style))
        return 1 if any(f["severity"] == "blocking" for f in res["findings"]) else 0
    except PathNotFound as exc:
        print(
            f"gitwhy: the folder {exc} does not exist. Use --path with your project folder, or cd into it first.",
            file=sys.stderr,
        )
        return 2


def _emit(res: dict, as_json: bool, render) -> None:
    if as_json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print(render(res))


if __name__ == "__main__":
    sys.exit(main())
