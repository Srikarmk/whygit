import io
import json
import subprocess
import sys

from gitwhy.cli import main


def test_default_is_diagnose_and_exit_code(build, capsys):
    path = build("merge_conflict")
    assert main(["--path", str(path)]) == 1
    out = capsys.readouterr().out
    assert "[BLOCKING] Merge in progress with conflicts in 1 file" in out
    assert "git merge --abort" in out
    assert "\033[" not in out  # not a terminal, so no colour


def test_clean_exit_zero(build, capsys):
    path = build("clean")
    assert main(["diagnose", "--path", str(path)]) == 0
    assert "No problems found" in capsys.readouterr().out


def test_json_output(build, capsys):
    path = build("diverged")
    main(["--json", "--path", str(path)])
    data = json.loads(capsys.readouterr().out)
    assert data["findings"][0]["rule"] == "diverged"


def test_path_option_after_subcommand(build, capsys):
    path = build("ahead")
    assert main(["status", "--path", str(path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ahead"] == 1 and data["branch"] == "main"


def test_status_text(build, capsys):
    path = build("merge_conflict")
    main(["status", "-C", str(path)])
    out = capsys.readouterr().out
    assert "On branch 'main'" in out and "In progress: merge." in out and "Conflicted:" in out


def test_explain_from_stdin(build, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("fatal: refusing to merge unrelated histories\n"))
    assert main(["explain", "-"]) == 0
    out = capsys.readouterr().out
    assert "unrelated" in out.lower() and "--allow-unrelated-histories" in out


def test_explain_argument_unknown(capsys, sandbox):
    assert main(["explain", "--path", str(sandbox.root), "nothing like git"]) == 3
    assert "doesn't recognise" in capsys.readouterr().out


def test_missing_path(capsys, sandbox):
    assert main(["--path", str(sandbox.root / "nope")]) == 2
    assert "does not exist" in capsys.readouterr().err


def test_no_emoji_or_non_ascii_in_rule_text(build, capsys):
    for name in ("merge_conflict",):
        main(["--path", str(build(name))])
    out = capsys.readouterr().out
    assert out.isascii()


def test_module_entry_point(build):
    path = build("detached_clean")
    p = subprocess.run([sys.executable, "-m", "gitwhy", "--path", str(path)], capture_output=True, text=True)
    assert p.returncode == 0
    assert "detached HEAD" in p.stdout


def test_color_only_on_tty(monkeypatch):
    from gitwhy.render import want_color

    class Tty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm")
    if sys.platform != "win32":
        assert want_color(Tty()) is True
    assert want_color(io.StringIO()) is False
    monkeypatch.setenv("NO_COLOR", "1")
    assert want_color(Tty()) is False
