# whygit

**What just happened to my Git repository, and how do I fix it?**

whygit looks at a Git repository and tells you, in plain English, what state it is in and
which commands will get you out of it: a merge conflict, a rebase stopped halfway, a detached
HEAD, a rejected push, a login GitHub won't accept, a 120 MB CSV that GitHub will refuse.
Paste it an error message and it explains that too.

It is written for people meeting Git for the first time. Git's own messages are accurate
but hard to read; whygit turns them into a short explanation and the exact fix.

It only ever **reads** your repository. It never runs the fixes it suggests, so you stay in
control and learn the commands as you go.

There are two ways to use it, built on the same engine:

- **On the command line**, with no AI tools involved: `whygit`.
- **As an MCP server**, so an assistant such as Claude Code, Claude Desktop or Cursor gets a
  reliable diagnosis instead of guessing from `git status`.

## Install

whygit needs Python 3.10 or newer and Git. Pick one:

```
uv tool install whygit     # with uv (https://docs.astral.sh/uv/)
pipx install whygit        # with pipx
uvx whygit                 # run once without installing
```

This works the same on macOS, Windows and Linux.

## Use it from the terminal

Run it inside your project folder:

```
whygit                    # what's wrong here, most urgent first
whygit status             # a plain summary: branch, upstream, what's changed
whygit explain "fatal: refusing to merge unrelated histories"
git push 2>&1 | whygit explain -
```

Options: `--path <folder>` (or `-C`) to look at another folder, `--json` for machine-readable
output, `--no-color` to turn off colour. Colour is only used in a real terminal and never
when `NO_COLOR` is set.

Exit codes: `0` nothing blocking, `1` something blocking was found, `2` bad usage (for example
the folder does not exist), `3` `explain` did not recognise the message.

### Example

```
$ whygit
whygit: /Users/sam/ds3500/hw2 (branch main)

[BLOCKING] Merge in progress with conflicts in 1 file
  Git tried to combine two lines of work, but both changed the same part of these
  files, so it stopped and is waiting for you to choose what the result should be.
  Nothing is lost while you decide.
  Conflicted files:
    - analysis.py  (both changed)
  How to fix:
    Finish the merge:
      1. Open each file and find the blocks between <<<<<<< and >>>>>>>. The part
         above ======= is one version, the part below is the other. Keep what you
         want, and delete the three marker lines.
      2. git add analysis.py
         Marks the files as resolved
      3. git commit --no-edit
         Records the merge and finishes it
    Or cancel the merge:
      1. git merge --abort
         Puts everything back the way it was before the merge started
  Learn more: https://git-scm.com/docs/git-merge#_how_to_resolve_conflicts

1 blocking. whygit never runs these commands for you; copy the ones you want.
```

Commands that can lose work (`git restore`, `git rebase --skip`, `git push --force-with-lease`
and so on) are always marked with a warning, and a safer option is listed first when one
exists.

## Use it with an AI assistant (MCP)

`whygit mcp` runs a Model Context Protocol server over stdio with three read-only tools:

| Tool | Use it when | Returns |
|---|---|---|
| `diagnose_repo(path=".")` | something seems stuck or broken | every problem found, most urgent first, with explanation and fix |
| `explain_git_error(error_text, path=None)` | a git command printed an error | what the error means and the fix, using the repository's state if `path` is given |
| `explain_state(path=".")` | you want a neutral summary | branch, upstream, ahead/behind, remotes, staged and changed files, operations in progress |

Results are small JSON objects. Pass an absolute path: relative paths resolve against the
server's working directory, which for desktop apps is usually not your project. `~` works.

### Claude Code

```
claude mcp add --scope user whygit -- uvx whygit mcp
```

`--scope user` makes it available in every project; leave it out to add it to the current
project only. Check it with `claude mcp list`.

### Claude Desktop

Open Settings > Developer > Edit Config, and add whygit to
`claude_desktop_config.json` (on macOS `~/Library/Application Support/Claude/`, on Windows
`%APPDATA%\Claude\`):

```json
{
  "mcpServers": {
    "whygit": {
      "command": "uvx",
      "args": ["whygit", "mcp"]
    }
  }
}
```

Restart Claude Desktop. If it can't find `uvx`, use the full path that `which uvx` (macOS)
or `where uvx` (Windows) prints as the `command`.

### Cursor

Add the same block to `~/.cursor/mcp.json` (all projects) or `.cursor/mcp.json` in a project:

```json
{
  "mcpServers": {
    "whygit": {
      "command": "uvx",
      "args": ["whygit", "mcp"]
    }
  }
}
```

If you installed whygit with `uv tool install` or `pipx`, you can use `"command": "whygit"`
with `"args": ["mcp"]` instead.

## What it recognises

Repository states: merge conflicts (and a merge that is resolved but not committed, including
leftover `<<<<<<<` markers), a rebase stopped on a conflict or an `edit`, cherry-pick, revert,
`git am` and bisect in progress, detached HEAD (and commits that no branch points to),
diverged / behind / ahead of the upstream, no upstream yet (the first `git push -u`), no
remote, upstream branch deleted, no commits yet, not a repository (including being one folder
too high, and your home folder), a home folder that was accidentally turned into a
repository, nested repositories (common with downloaded starter code), files over GitHub's
100 MB limit (and over 50 MB) staged or in unpushed commits, files that usually hold secrets
(`.env`, `id_rsa`, `*.pem`, `kaggle.json`, credentials JSON), notebooks with large saved
outputs, Jupyter notebook conflicts, missing `user.name` / `user.email`, a leftover
`index.lock`, and folders Git refuses because of "dubious ownership".

Error messages: rejected pushes, "You have divergent branches", "refusing to merge unrelated
histories", GitHub login failures (passwords no longer work; it explains tokens, SSH and
`gh auth login`, and never asks for your token), `Permission denied (publickey)`, repository
not found, 403, "Your local changes would be overwritten", untracked files in the way,
"not a git repository", "src refspec main does not match any", "pathspec did not match",
"remote origin already exists", missing upstream, "couldn't find remote ref", GitHub's
large-file rejection (GH001), "detected dubious ownership", "Please tell me who you are",
`index.lock` exists, line-ending warnings, network errors, and more. If it doesn't recognise
a message, it says so and shows what it can see in the repository instead.

## The read-only promise

whygit never changes your repository, and this is enforced in code rather than left to good
intentions:

- Every Git command goes through a single function that only accepts read-only subcommands
  (`status`, `rev-parse`, `for-each-ref`, `rev-list`, `diff`, `log`, `ls-files`, `cat-file`,
  `config --get`, `remote -v`, ...) and refuses anything else, including the writing forms of
  `config`, `remote` and `symbolic-ref`.
- It sets `GIT_OPTIONAL_LOCKS=0`, so even `git status` doesn't refresh the index, and turns off
  external diff programs and the fsmonitor hook.
- It never runs `git fetch`. Ahead/behind counts are "as of your last fetch", and whygit tells
  you to run `git fetch` yourself when that matters.
- The test suite builds each state in a real repository, snapshots every file under `.git`
  (names, timestamps and contents) before and after diagnosing, and checks nothing changed. It
  also checks that no other module in the package can start a process or write a file.

Credentials are never printed: a remote address like `https://name:token@github.com/...`
is shown as `https://***@github.com/...`, in every output.

## Privacy

whygit collects nothing and makes no network calls. It reads your repository on your own
computer and prints the result. That's all.

## Licence

MIT. Copyright (c) 2026 Kameswara Sai Srikar Manda.
