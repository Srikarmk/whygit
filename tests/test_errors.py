"""Error-text matching. Most messages are produced for real in scenario repositories
with a local bare repository as the remote; GitHub-only messages are verbatim copies
and marked as such."""

import pytest
import scenarios as S

from whygit.engine import explain_error


def rules_of(res):
    return [m["rule"] for m in res.get("matches", [])]


# ---------------------------------------------------------------- real captures


def c_overwritten_merge(sb):
    repo, other, _ = S._two_clones(sb)
    sb.commit(other, {"analysis.py": "print('v2')\n"}, "v2")
    sb.git(other, "push", "-q")
    (repo / "analysis.py").write_text("print('my edit')\n")
    return sb.out(repo, "pull"), repo


def c_overwritten_checkout(sb):
    repo = sb.init(sb.home / "proj")
    sb.commit(repo, {"f.py": "a\n"})
    sb.git(repo, "switch", "-q", "-c", "other")
    sb.commit(repo, {"f.py": "b\n"})
    sb.git(repo, "switch", "-q", "main")
    (repo / "f.py").write_text("edited\n")
    return sb.out(repo, "checkout", "other"), repo


def c_untracked_overwritten(sb):
    repo = sb.init(sb.home / "proj")
    sb.commit(repo, {"f.py": "a\n"})
    sb.git(repo, "switch", "-q", "-c", "other")
    sb.commit(repo, {"new.py": "b\n"})
    sb.git(repo, "switch", "-q", "main")
    (repo / "new.py").write_text("mine\n")
    return sb.out(repo, "checkout", "other"), repo


def c_push_fetch_first(sb):
    repo, other, _ = S._two_clones(sb)
    sb.commit(other, {"o.py": "1\n"}, "other")
    sb.git(other, "push", "-q")
    sb.commit(repo, {"m.py": "2\n"}, "mine")
    return sb.out(repo, "push"), repo


def c_push_non_ff(sb):
    text, repo = c_push_fetch_first(sb)
    sb.git(repo, "fetch", "-q")
    return sb.out(repo, "push"), repo


def c_divergent_pull(sb):
    _, repo = c_push_fetch_first(sb)
    return sb.out(repo, "pull"), repo


def c_unrelated(sb):
    _, remote = sb.published()
    repo = sb.init(sb.home / "local")
    sb.commit(repo, {"README.md": "mine\n"})
    sb.git(repo, "remote", "add", "origin", str(remote))
    return sb.out(repo, "pull", "--no-rebase", "origin", "main"), repo


def c_not_repo(sb):
    d = S.not_repo(sb)
    return sb.out(d, "status"), d


def c_src_refspec_unborn(sb):
    repo = sb.init(sb.home / "fresh")
    sb.git(repo, "remote", "add", "origin", str(sb.bare()))
    return sb.out(repo, "push", "origin", "main"), repo


def c_src_refspec_master(sb):
    repo = sb.home / "old"
    repo.mkdir()
    sb.git(repo, "init", "-q", "-b", "master")
    sb.ident(repo)
    sb.commit(repo, {"a.py": "1\n"})
    sb.git(repo, "remote", "add", "origin", str(sb.bare()))
    return sb.out(repo, "push", "origin", "main"), repo


def c_pathspec_checkout(sb):
    repo, _ = sb.published()
    sb.git(repo, "branch", "feature-x")
    return sb.out(repo, "checkout", "featur-x"), repo


def c_pathspec_switch(sb):
    repo, _ = sb.published()
    return sb.out(repo, "switch", "nosuch"), repo


def c_pathspec_add(sb):
    repo, _ = sb.published()
    return sb.out(repo, "add", "Analysis.py.bak"), repo


def c_remote_exists(sb):
    repo, _ = sb.published()
    return sb.out(repo, "remote", "add", "origin", "https://example.com/x.git"), repo


def c_index_lock(sb):
    repo = S.index_lock(sb)
    (repo / "x.py").write_text("x\n")
    return sb.out(repo, "add", "x.py"), repo


def c_identity(sb):
    repo = sb.init(sb.home / "proj", identity=False)
    return sb.out(repo, "-c", "user.useConfigOnly=true", "commit", "--allow-empty", "-m", "x"), repo


def c_merge_conflict(sb):
    repo = sb.init(sb.home / "proj")
    S.conflict_pair(sb, repo)
    return sb.out(repo, "merge", "other"), repo


def c_pull_unmerged(sb):
    repo = S.merge_conflict(sb)
    return sb.out(repo, "pull"), repo


def c_merge_head_exists(sb):
    repo = S.merge_resolved(sb)
    return sb.out(repo, "merge", "other"), repo


def c_rebase_exists(sb):
    repo = S.rebase_conflict(sb)
    return sb.out(repo, "rebase", "main"), repo


def c_cherry_pick(sb):
    repo = sb.init(sb.home / "proj")
    S.conflict_pair(sb, repo)
    return sb.out(repo, "cherry-pick", "other"), repo


def c_detached(sb):
    repo = sb.init(sb.home / "proj")
    sb.commit(repo, {"f": "1\n"})
    sb.commit(repo, {"f": "2\n"})
    return sb.out(repo, "checkout", "HEAD~1"), repo


def c_embedded(sb):
    repo = S.nested_untracked(sb)
    return sb.out(repo, "add", "starter-code"), repo


def c_no_upstream_push(sb):
    repo = S.no_upstream(sb)
    return sb.out(repo, "push"), repo


def c_no_tracking_pull(sb):
    repo = S.no_upstream(sb)
    return sb.out(repo, "pull"), repo


def c_remote_ref_missing(sb):
    repo, _ = sb.published()
    return sb.out(repo, "pull", "origin", "master"), repo


def c_no_such_remote(sb):
    repo, _ = sb.published()
    return sb.out(repo, "push", "upstream", "main"), repo


def c_clone_exists(sb):
    repo, remote = sb.published()
    return sb.out(sb.home, "clone", str(remote), "proj"), None


def c_diverged_status(sb):
    repo = S.diverged(sb)
    return sb.out(repo, "status"), repo


def c_up_to_date(sb):
    repo, _ = sb.published()
    return sb.out(repo, "push"), repo


def c_dubious(sb):
    repo, _ = sb.published()
    return sb.out(repo, "status", env={"GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"}), None


def c_crlf(sb):
    repo, _ = sb.published()
    (repo / "notes.txt").write_bytes(b"a\nb\n")  # bytes: write_text would already give CRLF on Windows
    return sb.out(repo, "-c", "core.autocrlf=true", "add", "notes.txt"), repo


# name -> (capture, rule expected with repo state, rule expected from text alone)
REAL = {
    "overwritten_merge": (c_overwritten_merge, "local_changes_overwritten", "local_changes_overwritten"),
    "overwritten_checkout": (c_overwritten_checkout, "local_changes_overwritten", "local_changes_overwritten"),
    "untracked_overwritten": (c_untracked_overwritten, "untracked_overwritten", "untracked_overwritten"),
    "push_fetch_first": (c_push_fetch_first, "push_rejected_remote_ahead", "push_rejected_remote_ahead"),
    "push_non_ff": (c_push_non_ff, "push_rejected_remote_ahead", "push_rejected_remote_ahead"),
    "divergent_pull": (c_divergent_pull, "divergent_pull", "divergent_pull"),
    "unrelated": (c_unrelated, "unrelated_histories", "unrelated_histories"),
    "not_repo": (c_not_repo, "not_a_repo", "not_a_repo"),
    "src_refspec_unborn": (c_src_refspec_unborn, "src_refspec", "src_refspec"),
    "src_refspec_master": (c_src_refspec_master, "src_refspec", "src_refspec"),
    "pathspec_checkout": (c_pathspec_checkout, "pathspec_no_match", "pathspec_no_match"),
    "pathspec_switch": (c_pathspec_switch, "pathspec_no_match", "pathspec_no_match"),
    "pathspec_add": (c_pathspec_add, "pathspec_no_match", "pathspec_no_match"),
    "remote_exists": (c_remote_exists, "remote_exists", "remote_exists"),
    "index_lock": (c_index_lock, "index_lock", "index_lock"),
    "identity": (c_identity, "missing_identity", "missing_identity"),
    "merge_conflict": (c_merge_conflict, "merge_conflict", "merge_conflict"),
    "pull_unmerged": (c_pull_unmerged, "merge_conflict", "merge_conflict"),
    "merge_head_exists": (c_merge_head_exists, "merge_resolved", "merge_resolved"),
    "rebase_exists": (c_rebase_exists, "rebase_in_progress", "rebase_in_progress"),
    "cherry_pick": (c_cherry_pick, "cherry_pick_in_progress", "merge_conflict"),
    "detached": (c_detached, "detached_head", "detached_head"),
    "embedded": (c_embedded, "nested_repo", "nested_repo"),
    "no_upstream_push": (c_no_upstream_push, "no_upstream", "no_upstream"),
    "no_tracking_pull": (c_no_tracking_pull, "no_upstream", "no_upstream"),
    "remote_ref_missing": (c_remote_ref_missing, "remote_ref_missing", "remote_ref_missing"),
    "no_such_remote": (c_no_such_remote, "no_remote", "no_remote"),
    "clone_exists": (c_clone_exists, "clone_dest_exists", "clone_dest_exists"),
    "diverged_status": (c_diverged_status, "diverged", "diverged"),
    "up_to_date": (c_up_to_date, "everything_up_to_date", "everything_up_to_date"),
    "dubious": (c_dubious, "dubious_ownership", "dubious_ownership"),
    "crlf": (c_crlf, "line_endings", "line_endings"),
}


@pytest.mark.parametrize("name", sorted(REAL))
def test_real_git_errors(sandbox, name):
    capture, with_state, text_only = REAL[name]
    text, path = capture(sandbox)
    assert text.strip(), f"{name}: git produced no output"
    res = explain_error(text, path)
    assert res["recognised"], f"{name}: not recognised:\n{text}"
    assert rules_of(res)[0] == with_state, f"{name}: {rules_of(res)}\n{text}"
    res2 = explain_error(text)
    assert rules_of(res2)[0] == text_only, f"{name} (text only): {rules_of(res2)}"
    for m in res["matches"]:
        assert m["title"] and m["explanation"] and m["fix"]


def test_overwritten_lists_files(sandbox):
    text, repo = c_overwritten_merge(sandbox)
    m = explain_error(text, repo)["matches"][0]
    assert m["details"]["items"] == ["analysis.py"]
    cmds = [s.get("command") for o in m["fix"] for s in o["steps"]]
    assert cmds.index("git stash") < cmds.index("git restore analysis.py")
    restore = next(s for o in m["fix"] for s in o["steps"] if s.get("command") == "git restore analysis.py")
    assert restore["destructive"] and restore["warning"]


def test_src_refspec_uses_state(sandbox):
    text, repo = c_src_refspec_master(sandbox)
    m = explain_error(text, repo)["matches"][0]
    assert "master" in m["title"]
    text, repo = c_src_refspec_unborn(sandbox)
    assert "no commits" in explain_error(text, repo)["matches"][0]["title"]


def test_pathspec_suggests_close_branch(sandbox):
    text, repo = c_pathspec_checkout(sandbox)
    m = explain_error(text, repo)["matches"][0]
    assert any(s.get("command") == "git switch feature-x" for o in m["fix"] for s in o["steps"])


def test_remote_ref_missing_suggests_main(sandbox):
    text, repo = c_remote_ref_missing(sandbox)
    m = explain_error(text, repo)["matches"][0]
    assert any(s.get("command") == "git pull origin main" for o in m["fix"] for s in o["steps"])


def test_conflict_with_state_lists_files(sandbox):
    text, repo = c_merge_conflict(sandbox)
    m = explain_error(text, repo)["matches"][0]
    assert m["details"]["items"] == ["analysis.py  (both changed)"]


def test_push_rejected_never_recommends_force(sandbox):
    text, repo = c_push_non_ff(sandbox)
    m = explain_error(text, repo)["matches"][0]
    cmds = [s.get("command") or "" for o in m["fix"] for s in o["steps"]]
    assert not any("--force" in c for c in cmds)
    assert "ahead" in m["note"]


# ---------------------------------------------------------------- verbatim GitHub messages
# These come from GitHub's servers (or ssh / curl talking to them) and can't be produced
# against a local bare repository, so they are copied verbatim.

VERBATIM = {
    "auth_password_removed": (
        "remote: Support for password authentication was removed on August 13, 2021.\n"
        "remote: Please see https://docs.github.com/get-started/getting-started-with-git/about-remote-repositories#cloning-with-https-urls for information on currently recommended modes of authentication.\n"
        "fatal: Authentication failed for 'https://github.com/student/hw1.git/'\n",
        "auth_failed",
    ),
    "auth_invalid_token": (
        "remote: Invalid username or token. Password authentication is not supported for Git operations.\n"
        "fatal: Authentication failed for 'https://github.com/student/hw1.git/'\n",
        "auth_failed",
    ),
    "ssh_publickey": (
        "git@github.com: Permission denied (publickey).\n"
        "fatal: Could not read from remote repository.\n\n"
        "Please make sure you have the correct access rights\nand the repository exists.\n",
        "ssh_publickey",
    ),
    "repo_not_found": (
        "remote: Repository not found.\nfatal: repository 'https://github.com/student/hw1.git/' not found\n",
        "repo_not_found",
    ),
    "forbidden_403": (
        "remote: Permission to course/starter.git denied to student.\n"
        "fatal: unable to access 'https://github.com/course/starter.git/': The requested URL returned error: 403\n",
        "push_forbidden",
    ),
    "gh001": (
        "remote: error: Trace: 1a2b3c4d5e6f\n"
        "remote: error: See https://gh.io/lfs for more information.\n"
        "remote: error: File data/train.csv is 123.45 MB; this exceeds GitHub's file size limit of 100.00 MB\n"
        "remote: error: GH001: Large files detected. You may want to try Git Large File Storage - https://git-lfs.github.com.\n"
        "To https://github.com/student/hw1.git\n"
        " ! [remote rejected] main -> main (pre-receive hook declined)\n"
        "error: failed to push some refs to 'https://github.com/student/hw1.git'\n",
        "large_file_over_limit",
    ),
    "http_413": (
        "error: RPC failed; HTTP 413 curl 22 The requested URL returned error: 413\nsend-pack: unexpected disconnect while reading sideband packet\n",
        "push_too_large",
    ),
    "no_network": (
        "fatal: unable to access 'https://github.com/student/hw1.git/': Could not resolve host: github.com\n",
        "network",
    ),
}


@pytest.mark.parametrize("name", sorted(VERBATIM))
def test_verbatim_github_errors(name):
    text, rule = VERBATIM[name]
    res = explain_error(text)
    assert res["recognised"]
    assert rules_of(res)[0] == rule, rules_of(res)


def test_gh001_lists_file_and_rebuild_steps():
    m = explain_error(VERBATIM["gh001"][0])["matches"][0]
    assert m["details"]["items"] == ["data/train.csv  (123.45 MB)"]
    cmds = [s.get("command") for o in m["fix"] for s in o["steps"]]
    assert "git rm --cached data/train.csv" in cmds
    assert len(rules_of(explain_error(VERBATIM["gh001"][0]))) == 1


def test_auth_never_asks_for_token():
    m = explain_error(VERBATIM["auth_password_removed"][0])["matches"][0]
    assert "gh auth login" in [s.get("command") for o in m["fix"] for s in o["steps"]]
    assert "Never paste a token" in m["explanation"]


def test_publickey_offers_https_url_from_remote(sandbox):
    repo, _ = sandbox.published()
    sandbox.git(repo, "remote", "set-url", "origin", "git@github.com:student/hw1.git")
    m = explain_error(VERBATIM["ssh_publickey"][0], repo)["matches"][0]
    assert m["fix"][0]["steps"][0]["command"] == "git remote set-url origin https://github.com/student/hw1.git"


# ---------------------------------------------------------------- unknown text


def test_unknown_error_without_path():
    res = explain_error("fatal: the flux capacitor is misaligned")
    assert res["recognised"] is False
    assert "doesn't recognise" in res["message"]
    assert "diagnosis" not in res


def test_unknown_error_with_path_shows_diagnosis(build):
    path = build("merge_conflict")
    res = explain_error("fatal: the flux capacitor is misaligned", path)
    assert res["recognised"] is False
    assert [f["rule"] for f in res["diagnosis"]][0] == "merge_conflict"


def test_extra_blocking_state_is_mentioned(build):
    path = build("merge_conflict")
    res = explain_error(VERBATIM["no_network"][0], path)
    assert [f["rule"] for f in res["also_in_this_repo"]] == ["merge_conflict"]
