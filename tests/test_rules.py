import pytest
from scenarios import SCENARIOS

from whygit.engine import diagnose
from whygit.rules import RULES


def ids(report):
    return [f["rule"] for f in report["findings"]]


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenario_fires_expected_rules(build, name):
    _, expected, _ = SCENARIOS[name]
    report = diagnose(build(name))
    found = set(ids(report))
    assert expected <= found, f"{name}: expected {expected}, got {found}"


def test_every_rule_has_a_scenario():
    covered = set().union(*(exp for _, exp, _ in SCENARIOS.values()))
    missing = {r.id for r in RULES} - covered - {"git_not_installed"}
    assert not missing, f"rules without a scenario: {missing}"


def test_clean_repo_fires_nothing(build):
    report = diagnose(build("clean"))
    assert report["findings"] == []
    assert report["summary"] == "No problems found."


def test_most_urgent_first(build):
    report = diagnose(build("notebook_conflict"))
    sev = [f["severity"] for f in report["findings"]]
    order = {"blocking": 0, "warning": 1, "info": 2}
    assert sev == sorted(sev, key=order.get)
    assert report["findings"][0]["rule"] == "merge_conflict"


def _find(report, rule):
    return next(f for f in report["findings"] if f["rule"] == rule)


def test_merge_conflict_details_and_fix(build):
    report = diagnose(build("merge_conflict"))
    f = _find(report, "merge_conflict")
    assert f["details"]["items"] == ["analysis.py  (both changed)"]
    assert f["learn_more"].startswith("https://git-scm.com/")
    commands = [s.get("command") for opt in f["fix"] for s in opt["steps"]]
    assert "git add analysis.py" in commands
    assert "git merge --abort" in commands


def test_merge_markers_left_in_staged_file(build):
    f = _find(diagnose(build("merge_resolved_markers")), "merge_resolved")
    assert "analysis.py" in f["note"]


def test_rebase_conflict_vs_edit(build, sandbox):
    f = _find(diagnose(build("rebase_conflict")), "rebase_in_progress")
    assert "conflict" in f["title"]
    assert "ours" in f["explanation"]


def test_rebase_edit_title(build):
    f = _find(diagnose(build("rebase_edit")), "rebase_in_progress")
    assert "edit" in f["title"]
    assert any(s.get("command") == "git commit --amend --no-edit" for s in f["fix"][0]["steps"])


def test_bisect_does_not_also_report_detached(build):
    assert "detached_head" not in ids(diagnose(build("bisect")))


def test_detached_with_orphans_suggests_branch_first(build):
    f = _find(diagnose(build("detached_orphans")), "detached_head")
    assert "1 commit" in f["explanation"]
    assert f["fix"][0]["steps"][0]["command"] == "git switch -c <new-branch-name>"


def test_detached_clean_suggests_going_back(build):
    f = _find(diagnose(build("detached_clean")), "detached_head")
    assert f["fix"][0]["steps"][0]["command"] == "git switch main"


def test_ahead_behind_mentions_last_fetch(build):
    f = _find(diagnose(build("diverged")), "diverged")
    assert "git fetch" in f["note"]
    assert "1 commit" in f["explanation"]
    destructive = [s for o in f["fix"] for s in o["steps"] if s.get("destructive")]
    assert destructive and all(s.get("warning") for s in destructive)
    assert not f["fix"][0]["steps"][0].get("destructive")


def test_no_upstream_suggests_push_u(build):
    f = _find(diagnose(build("no_upstream")), "no_upstream")
    assert f["fix"][0]["steps"][0]["command"] == "git push -u origin feature"


def test_parent_of_clone_points_to_child(build):
    f = _find(diagnose(build("parent_of_clone")), "not_a_repo")
    assert f["fix"][0]["steps"][0]["command"] == "cd hw1"


def test_home_folder_warnings(build):
    f = _find(diagnose(build("at_home")), "not_a_repo")
    assert "home folder" in f["explanation"]
    init = [s for o in f["fix"] for s in o["steps"] if s.get("command") == "git init"]
    assert init and "home folder" in init[0]["warning"]


def test_home_repo_severity(build):
    assert _find(diagnose(build("home_repo")), "home_repo")["severity"] == "blocking"


def test_home_repo_outer_is_warning_not_nested(build):
    report = diagnose(build("home_repo_outer"))
    assert _find(report, "home_repo")["severity"] == "warning"
    assert "nested_repo" not in ids(report)


def test_home_repo_fix_never_deletes(build):
    f = _find(diagnose(build("home_repo")), "home_repo")
    cmds = " ".join(s.get("command") or "" for o in f["fix"] for s in o["steps"])
    assert "rm " not in cmds and "mv ~/.git" in cmds


def test_nested_gitlink_suggests_rm_cached(build):
    f = _find(diagnose(build("nested_gitlink")), "nested_repo")
    cmds = [s.get("command") for o in f["fix"] for s in o["steps"]]
    assert "git rm --cached starter-code" in cmds


def test_large_files_details(build):
    report = diagnose(build("large_staged"))
    over = _find(report, "large_file_over_limit")
    assert over["severity"] == "blocking"
    assert any("big.csv" in i for i in over["details"]["items"])
    warn = _find(report, "large_file_warning")
    assert any("medium.csv" in i for i in warn["details"]["items"])
    assert not any("medium.csv" in i for i in over["details"]["items"])


def test_large_unpushed_uses_reset_soft(build):
    f = _find(diagnose(build("large_unpushed")), "large_file_warning")
    cmds = [s.get("command") for o in f["fix"] for s in o["steps"]]
    assert "git reset --soft @{u}" in cmds


def test_secret_staged_skips_example_files(build):
    f = _find(diagnose(build("secret_staged")), "secret_staged")
    items = " ".join(f["details"]["items"])
    assert ".env " in items + " " and "keys/id_rsa" in items
    assert ".env.example" not in items


def test_missing_identity_lists_both(build):
    f = _find(diagnose(build("missing_identity")), "missing_identity")
    assert f["details"]["items"] == ["user.name", "user.email"]


def test_dubious_fix_mentions_safe_directory(build):
    f = _find(diagnose(build("dubious")), "dubious_ownership")
    assert "safe.directory" in f["fix"][0]["steps"][0]["command"]


def test_git_not_installed(sandbox, monkeypatch, tmp_path):
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    report = diagnose(sandbox.root)
    assert ids(report) == ["git_not_installed"]


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_findings_are_complete_and_destructive_steps_warn(build, name):
    for f in diagnose(build(name))["findings"]:
        assert f["title"] and f["explanation"] and f["fix"]
        assert f["learn_more"].startswith("https://git-scm.com/")
        assert f["severity"] in ("blocking", "warning", "info")
        for opt in f["fix"]:
            assert opt["steps"]
            for s in opt["steps"]:
                if s.get("destructive"):
                    assert s.get("warning"), (name, f["rule"], s)


def test_many_child_repos_says_how_many_more(sandbox):
    top = sandbox.home / "projects"
    for i in range(13):
        sandbox.init(top / f"repo{i:02d}")
    f = _find(diagnose(top), "not_a_repo")
    items = f["details"]["items"]
    assert items[:8] == [f"repo{i:02d}" for i in range(8)]
    assert items[8] == "... and 5 more"
