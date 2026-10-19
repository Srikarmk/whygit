import json

from gitwhy.cli import main
from gitwhy.engine import diagnose, explain_error, explain_state
from gitwhy.gitcmd import redact

TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
URL = f"https://student:{TOKEN}@github.com/student/hw1.git"


def test_redact_patterns():
    assert redact(URL) == "https://***@github.com/student/hw1.git"
    assert redact("https://student@github.com/x.git") == "https://***@github.com/x.git"
    assert redact(f"token is {TOKEN}") == "token is ***"
    assert redact("github_pat_11ABCDEFG0123456789_abcdefghijklmnop") == "***"
    assert redact("git@github.com:student/hw1.git") == "git@github.com:student/hw1.git"
    assert redact("https://github.com/student/hw1.git") == "https://github.com/student/hw1.git"


def test_remote_credentials_never_appear(sandbox, capsys):
    repo, _ = sandbox.published()
    sandbox.git(repo, "remote", "add", "github", URL)
    sandbox.git(repo, "remote", "set-url", "origin", URL)
    outputs = [
        json.dumps(diagnose(repo)),
        json.dumps(explain_state(repo)),
        json.dumps(explain_error(f"fatal: Authentication failed for '{URL}/'", repo)),
        json.dumps(explain_error(f"fatal: something unknown at {URL}", repo)),
        json.dumps(explain_error("remote: Repository not found.", repo)),
    ]
    for argv in (
        ["status", "--path", str(repo)],
        ["status", "--json", "--path", str(repo)],
        ["explain", "--path", str(repo), f"weird {URL}"],
    ):
        main(argv)
        outputs.append(capsys.readouterr().out)
    for out in outputs:
        assert TOKEN not in out
        assert "student:" not in out
    state = explain_state(repo)
    assert state["remotes"]["github"] == "https://***@github.com/student/hw1.git"
