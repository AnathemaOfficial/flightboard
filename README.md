<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
<p align="left">
  <img src="assets/wordmark.svg" alt="flightboard" width="312">
</p>

# flightboard

[Français](docs/fr/README.md)

**A read-only board of your parallel coding-agent sessions: what each one changed in your roadmap, and what waits for
you.**

You run coding agents in parallel, each in its own Git worktree and branch. Your roadmap in `main` only learns
what they did once you merge them, and nothing shows at a glance who does what, what moved, and what waits for your
go. flightboard is one local page, and a few lines of text for an agent, that answer that from the repository itself:

- **What waits for you**, in your own verbs: give a merge go, arbitrate a conflict, check a decision recorded in your
  name in a branch, start a review, look at a quiet session with uncommitted changes.
- **Every session**: writing now or quiet since when, uncommitted / committed / pushed / in main, behind its remote,
  and what it may be called — "ready for your merge go" or "ended" only when its state allows it.
- **The roadmap, live**: the task statuses each session declares in its own copy of your task file, overlaid on
  `main` before anything is merged, with conflicts between sessions shown, never resolved for you.
- **Progress**: tasks done over time, milestones, moves per day, each with a table view.

It works without any task file too: a repository without one gets the whole sessions view from git alone.

flightboard uses guarded Git and file reads, writes nothing in the repository or authorized worktree roots, and
serves its page to this computer only. Its checks and remaining risks are described below. It needs
**Python 3.12+ and git 2.41+, nothing else**: no
package to install, no network, no account.

Claude Code, Codex and tools running Qwen, MiMo, MiniMax, Kimi or other models can use the same Git workflow. The
board observes their files, commits and declared task ownership; it does not connect to providers, read conversations
or launch itself when a desktop chat starts. The tool running a model must provide the Git worktree/branch workflow.

> flightboard is an independent project; product and model names describe Git workflows it can observe.

The standalone command and both plugins use the same engine in `skills/flightboard/scripts` and the same web
dashboard. Claude Code uses `.claude-plugin`; Codex uses the portable root `plugin.json` and
`.agents/plugins/marketplace.json`. The plugins supply the workflow for choosing a repository and launching that
engine; Python and Git still run locally. Each running instance reads one repository and its authorized worktrees.

## Quick start: ask your coding agent

After the [one-time installation](#install), open a Codex or Claude Code session in the Git repository you want to
watch and ask:

```text
Open Flightboard for this repository, in English.
```

Or name another local repository: `Open Flightboard for the repository "/path/to/my-project", in English.`
The user installation works across your projects on this computer; you do not copy Flightboard into every repository.
The agent starts the local server and opens its web dashboard. These instructions require a coding-agent session
with local file and command access.

To select the skill explicitly:

| Agent | Prompt |
| :- | :- |
| Codex | `$flightboard Open the live dashboard for this repository, in English.` |
| Claude Code | `/flightboard:flightboard Open the live dashboard for this repository, in English.` |

Ask for a **live dashboard** to open the page, or for a **text summary** to get a one-time status in the chat.

### Open the page and choose a language

Click the URL returned by the agent, or paste it into Chrome, Edge, Firefox or another browser. The default address
is [http://127.0.0.1:8790/](http://127.0.0.1:8790/); it works while the server is running on this computer. You can
bookmark it. The page refreshes every 10 seconds.

English is the default. Ask `Open Flightboard for this repository, in French` for French; the corresponding command
options are `--lang en` and `--lang fr`. They select the language of both the dashboard and the text summary.

### Watch several repositories

Start one server per repository and request a different port for each:

```text
Open Flightboard for "/path/to/project-a" on port 8791, in English.
Open Flightboard for "/path/to/project-b" on port 8792, in English.
```

Open `http://127.0.0.1:8791/` and `http://127.0.0.1:8792/` in separate tabs. Each tab shows one repository and its
authorized worktrees. Flightboard currently has no combined dashboard for unrelated repositories.

Closing a browser tab does not stop its server. If you started it in a terminal, press **Ctrl+C** there. If an agent
started it in the background, ask that agent to stop the Flightboard server for the named repository. After the
process exits or the computer restarts, launch it again to use the bookmarked page, or enable the optional Windows
startup helper below.

### Start automatically on Windows, across repositories

The optional startup helper remembers several dashboards and starts them at **Windows sign-in**. They run
independently of Codex and Claude: closing and reopening either application leaves the dashboards available.
It checks local processes and listening ports about once a minute, and restarts a missing server without opening
a browser. It does not read Git or request dashboard pages during these checks.

Install once, using a working Python 3.12+ with its matching `pythonw.exe`. For an installed Codex skill, in
PowerShell:

```powershell
py -3 -I -B "$env:USERPROFILE/.agents/skills/flightboard/scripts/flightboard_startup.py" install
```

From a clone, run the same command with `./skills/flightboard/scripts/flightboard_startup.py` from the clone's
root instead. For Claude Code, use the helper in its installed skill's `scripts` folder. Installation copies the
engine into `$env:LOCALAPPDATA/Flightboard/startup/engine`, creates a `Flightboard.lnk` shortcut in your user's
Startup folder, and starts the supervisor immediately. No administrator account or change to either AI app is
needed. Rerun `install` from an updated Flightboard installation to update the copied engine.

To remember another repository:

1. Ask your agent to open its Flightboard dashboard, with a distinct port and **`--repo` set to its absolute path**.
   Keep the required worktree-root options in that launch command.
2. Leave the server running for at least one minute. The supervisor remembers its port, language and read options.
3. Reopen the bookmarked URL after your next Windows sign-in. New Git sessions within that repository appear under
   its existing worktree rules. A chat in a new repository alone does not register a dashboard.

Discovery accepts only live servers using `-I -B`, an explicit absolute `--repo`, an authorized engine and Python
interpreter, and a loopback listener owned by that server. `install` authorizes its source engine and interpreter,
plus the stable copy. To include a separate Codex or Claude installation, run `install` from that copy too, or add
its absolute paths explicitly with repeatable `--trust-engine FILE` and `--trust-python FILE` options on `install`.
New plugin paths after an upgrade may need this step again. No additional worktree roots are authorized by discovery.

Use the stable helper to inspect or change the setup:

```powershell
$startupTool = "$env:LOCALAPPDATA/Flightboard/startup/engine/flightboard_startup.py"
py -3 -I -B $startupTool status
py -3 -I -B $startupTool forget --repo "$env:USERPROFILE/projects/project-a"
py -3 -I -B $startupTool disable
py -3 -I -B $startupTool enable
```

Replace the example repository with its absolute path. `forget` removes it from the saved list and excludes it from
future discovery. `disable` removes the startup shortcut and asks the supervisor to exit; both commands leave
existing dashboard servers running. `enable` restores startup and supervision. `once` runs one supervision pass;
`run` runs the supervisor in the foreground for diagnosis.
To watch a forgotten repository again, remove its path from `excluded_repos` in `config.json`, then reopen its dashboard.

Configuration, status and rotating logs stay in `$env:LOCALAPPDATA/Flightboard/startup`. Keep the chosen Python
installation available. An unavailable repository drive is retried; a port occupied by another process is reported
and left untouched. A server process that still exists but has stopped responding is reported when it has no
listener, and is not forcibly terminated. This helper does not merge the repositories into one dashboard.

## Install

### Claude Code

Install once for your user from a shell (this repository contains both the marketplace and the plugin):

```bash
claude plugin marketplace add AnathemaOfficial/flightboard --scope user
claude plugin install flightboard@flightboard --scope user
```

To install from a local clone instead, replace `AnathemaOfficial/flightboard` in the first command with its quoted
absolute path, such as `"/absolute/path/to/flightboard"`. Start a new Claude Code session after installation, then
use the prompts above. See the [official Claude Code plugin instructions](https://code.claude.com/docs/en/discover-plugins).

### Codex

For Codex, choose either the plugin or the standalone skill so the same skill is not discovered twice. To install
the plugin from a local clone:

```bash
codex plugin marketplace add "/absolute/path/to/flightboard"
codex plugin add flightboard@flightboard
```

Replace the path with the absolute path of your clone. The local marketplace points to the shared plugin at `./`;
see [OpenAI's plugin packaging guide](https://developers.openai.com/plugins/build/plugins).

For the skill alone, copy a clean `skills/flightboard` folder, including `SKILL.md` and `scripts`, to
`~/.agents/skills/flightboard`; exclude `__pycache__` folders and `*.pyc` files. Codex discovers user skills there;
see the [official skills documentation](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills).
Then invoke `$flightboard` or ask naturally, for example "Open Flightboard for this repository". The skill uses the
current repository, or a repository you explicitly name with `--repo`. Installation does not launch it when a chat
starts, and the board never fetches from a remote. If the skill does not appear, restart Codex.

### Standalone command

You can also launch the same engine directly. Replace the first path with your Flightboard clone and `--repo` with
the local Git repository to watch:

```bash
python3 -I -B "/path/to/flightboard/skills/flightboard/scripts/flightboard.py" --repo "/path/to/my-project" --lang en
```

Always run it with `-I -B` (isolated: no environment variable, user site or current folder steers Python).
Check that your interpreter is Python 3.12 or newer before launching it. On Windows, use a working `python` or
`py -3` if `python3` is unavailable or opens the Microsoft Store. For an installed Codex skill, in PowerShell:

```powershell
py -3 --version
py -3 -I -B "$env:USERPROFILE/.agents/skills/flightboard/scripts/flightboard.py" --repo "$PWD" --lang en
```

Here `$PWD` means the current project folder. The terminal stays open while the server runs: open the printed URL
in your browser and press Ctrl+C in that terminal to stop it.

For a one-time text summary instead of the live page:

```powershell
py -3 -I -B "$env:USERPROFILE/.agents/skills/flightboard/scripts/flightboard.py" --repo "$PWD" --resume --lang en
```

## Use

From a clone, these commands explicitly name the shared script and the repository to read:

```bash
python3 -I -B "/path/to/flightboard/skills/flightboard/scripts/flightboard.py" --repo "/path/to/my-project"
python3 -I -B "/path/to/flightboard/skills/flightboard/scripts/flightboard.py" --repo "/path/to/my-project" --resume
python3 -I -B "/path/to/flightboard/skills/flightboard/scripts/flightboard.py" --repo "/path/to/my-project" --snapshot
```

The first command serves the live page; `--resume` prints a text summary; `--snapshot` writes a standalone HTML
page in your cache and prints its location. A snapshot does not refresh. Add `--lang fr` to any mode for French.

### Include agent worktrees

The default folder is `.claude/worktrees`. To include another folder inside the repository, explicitly request it
with `--worktrees .worktrees`. Registered Codex worktrees outside the repository need an explicit root, for example
`--worktrees-root "$HOME/.codex/worktrees"`; in PowerShell you can use
`--worktrees-root "$env:USERPROFILE/.codex/worktrees"`. You can also tell the agent to include that root in your prompt.
Only registered worktrees belonging to the chosen repository are eligible; authorizing a root does not scan other projects.

An existing repository's sessions and commits need no import from an AI tool. The board reads the Git state already
on disk. If it reports too many registered worktrees, check their count and use `--max-worktrees N` (100 by default,
from 1 to 1000). This includes every registered admin entry, even when its working files are outside the authorized
roots. Exceeding the limit refuses the reading rather than silently dropping sessions; it does not mean data was lost.

Large repositories may exceed the shared 12-second reading budget. To focus on worktrees, request
`--max-branches 0`: this excludes branches without a worktree. It does not make unread worktrees readable; check
the warnings on their cards and the source status at the bottom of the page.
For a larger set of worktrees, `--read-seconds 30` allows a longer complete reading. The default is 12 seconds,
configurable from 12 to 120; each Git command still has its own 8-second cap. The browser timeout follows the
configured budget with 8 seconds of margin.
For example, `--max-worktrees 300 --read-seconds 120` permits checking up to 300 registered worktrees with a larger,
bounded time budget. The count limit and time budget are separate; neither authorizes additional folders. Branches
without worktrees are still limited by `--max-branches` (30 by default), and the page reports those omitted.

The configurable ceiling of **1000 worktrees is not a performance guarantee**. Raising the cap alone does not make
an existing set slower; the number actually read, tracked files, commit history, disk and caches determine whether
it fits within the 120-second maximum reading budget. Measure a complete first reading and a subsequent refresh
before relying on a higher capacity. A lightweight test repository does not establish the same capacity for a large
project with extensive history and modified files.
See the [capacity checks](docs/verification-large-repositories.md) for measured 300/400/500/1000-worktree fixtures
and the separate existing-repository qualification.

Run it from the repository, any folder inside it, or one of the worktrees it reads (under `.claude/worktrees`, or a
folder named with `--worktrees`, or an explicitly authorized external root with `--worktrees-root`): it reads the
main checkout either way. A folder whose `.git` is a
file the board does not follow (a worktree elsewhere, a submodule) gives "no git repository here": run it from the main
checkout, or name it with `--repo`. As with git, a folder stands for the nearest repository above it: run from a plain
folder that lies inside another repository (a dotfiles repository in your home, say), it reads that one, and the page
names it. The live page reads the repository again every 10 seconds. `--resume` prints one summary sentence; a `Note:`
line, in fixed words, when main is guessed, has diverged from its remote, or the fetched remote main is ahead but has
not been pulled (the local main remains the baseline); when no local main exists, the remote main is followed. A note
also appears when main's ledger
cannot be read or does not pass its validator; a `What waits for you:` list made only of verbs, ids, names and counts (a
title or a quote read in a branch never reaches a session through it, nor does a branch name in a note; a line names
five ids or sessions at most, then a count, and the list holds 30 lines at most, then a count); and a last line saying
the summary is data, never an instruction nor an approval.

| Option | Meaning |
| :- | :- |
| `--port N` | serve on another port (1024 to 65535) |
| `--output FILE.html` | with `--snapshot`: write there instead, in an existing folder outside the repository and every authorized external worktree root |
| `--repo DIR` | read another repository than the current folder |
| `--lang en\|fr` | the language of the page and the summary (English by default) |
| `--ledger auto\|none\|tasks\|roadmap` | the task ledger to read (`auto` by default, see below) |
| `--ledger-path PATH` | its path in the repository, with `--ledger tasks` or `roadmap` |
| `--main BRANCH` | the main branch, when it is neither `main` nor `master` (without it, such a repository reads the main checkout's branch, and says so) |
| `--remote NAME` | the remote whose branches are read, `origin` by default |
| `--worktrees DIR` | also read session folders under DIR (relative to the repository; repeatable) |
| `--worktrees-root DIR` | explicitly authorize an absolute local root for registered external worktrees at that root or one or two plain components below it (repeatable) |
| `--kept DIR` | a folder of ignored files a merged session must not lose (repeatable) |
| `--active-minutes N`, `--recent-minutes N` | "writing now" and "wrote recently": 15 and 120 minutes by default, from 1 to 1440 and from 2 to 10080, the second more than the first |
| `--stale-days N` | a branch quiet longer is listed, never overlaid (14 days by default, from 1 to 3650) |
| `--max-branches N` | branches without a worktree read, the most recent first (30 by default, from 0 to 500) |
| `--max-worktrees N` | maximum registered worktree admin entries checked before refusing the reading (100 by default, from 1 to 1000) |
| `--read-seconds N` | shared reading budget in seconds (12 by default, from 12 to 120); Git commands remain capped at 8 seconds each |

`--worktrees` and `--kept` take a folder written plainly inside the repository: six names at most, no `..`, drive,
`.git` or device name.

External roots are opt-in: for example, `--worktrees-root "$HOME/.codex/worktrees"` can authorize registered Codex
worktrees laid out as `<root>/<hash>/<project>`. A registered worktree may also be the exact directory explicitly
authorized as its root, so a single worktree needs no broader parent authorization. A root is an absolute local directory, with no traversal, UNC or
device path; the root and the path to each worktree must have no symlink, junction or reparse point. Only worktrees
registered in this repository's `.git/worktrees` are considered. Naming a root does not scan other repositories or
authorize arbitrary descendants. Snapshots are forbidden anywhere inside every authorized root, including its other
children. Supply the same option when starting the board inside an authorized external worktree.

A usage error exits with code 2; a busy port or a write error, with code 1. Every setting comes from the command
line, never from a file of the observed repository; with `--ledger auto`, only the files main holds (never a branch's)
choose which ledger is read.

## What it reads

1. **main**: its last commit and its history, from its reflog (when and why main moved, "merge claude/x: Fast-forward"),
   then its first-parent line for what the reflog no longer holds, marked approximate. Local main remains the
   baseline when the fetched remote main is ahead: a note says those commits have not been pulled. Only when no local
   main exists does the board follow the remote main. Divergence is reported too. With neither `main` nor `master`,
   locally or on the remote, and no
   `--main`, main is the main checkout's branch: a guess that moves if a session switches that checkout's branch,
   flagged by a note until `--main` pins it. A guessed main whose name git may not be given (one holding a `+` or an
   accented letter, say) has no reflog read: its history is its first-parent line alone, marked approximate.
2. **Every session**: the main checkout, each worktree under `.claude/worktrees` (and the folders you name with
   `--worktrees`, plus registered worktrees under explicit `--worktrees-root` roots), and each branch holding commits
   main lacks, a branch pushed by a cloud session and fetched
   included. For each one: its ledger (the working copy for a worktree, uncommitted changes included; the last
   commit for a branch), its merge base with main, how far ahead and behind it is, its modified tracked files, its new
   files, and when they were last written.
3. **Nothing else**: not GitHub, not the network, not the sessions' transcripts, not other repositories. CI does not
   show.

## Ledgers

`--ledger auto` (the default) picks the first file main holds among `data/roadmap.json` (the roadmap ledger),
`tasks.toml` and `tasks.json` (a simple task file). Without one, or when main's copy cannot be read, the board is
git's alone, and says so.

### A simple task file

```toml
# tasks.toml (or the same in tasks.json)
[statuses]              # optional: your words for flightboard's statuses
todo = "planned"
doing = "in_progress"
review = "awaiting_review"

[[milestones]]          # optional
id = "M1"
title = "First release"

[[tasks]]
id = "AUTH-1"           # a letter or a digit first, then letters, digits, . _ -; one letter at least, 40 at most
title = "Login page"
status = "doing"        # planned, ready, in_progress, awaiting_review, done, blocked, dropped, or your words
owner = "codex"         # optional: lowercase, a letter first, a-z 0-9 _ -, 31 characters at most; "owner" (you)
                        # and "reviewer" tasks never move from a branch
milestone = "M1"        # optional
depends_on = ["AUTH-0"] # optional: ids of other tasks in this file
priority = "P1"         # optional, P0 to P9
acceptance = ["A user can sign in"]  # optional

[[tasks]]
id = "AUTH-0"
title = "Users table"
status = "done"
```

Its validator is small and structural: unique ids, statuses that map to flightboard's, dependencies that resolve, no
cycle. A branch whose file fails it is listed, never overlaid; so is one declaring more than 2000 tasks, read in
part. A task file whose tasks cannot be used says why on the page, and `--resume` says that it does; in main's
history, a version without one usable task (every status unknown, say) is skipped, never read as every task
removed. "Next to start" lists tasks owned by any safely named agent or by nobody; `owner` and `reviewer` are human
roles and excluded. An id without a digit (`auth`) is never
inferred from a branch name.

### The roadmap ledger

`data/roadmap.json`, schema 2: milestones with exit criteria, capacity, a launch gate, decisions and external
dependencies. Its validator is part of flightboard, never loaded from the repository it judges;
ids take any uppercase prefix (`ABC-123`, `ABC-M1-02`, `ADR-0001`). With it the board also draws main's forecast,
the plan, and decisions a branch records in your name. A ledger past the validator's caps (more than 2000 tasks, say)
is never valid, and is read in part: 4000 tasks at most.

Agent owners use the same lowercase names as the simple task file: `claude`, `codex`, `qwen`, `mimo`, `minimax`,
`kimi`, or another safe name. Their behavior is identical; `owner` and `reviewer` remain human roles. In `capacity`,
use `agent_sessions_per_week` for the shared capacity of all coding agents. The legacy key
`claude_sessions_per_week` is still accepted; if both keys are present they must hold the same positive integer.
`review_slots_per_week` and `owner_hours_per_week` keep the human reviewer and owner separate. Renaming an agent
does not change the forecast. Dependencies are checked in full, independently of display limits.

### The live overlay

- A session's changes are its ledger against **its merge base with main**, never against main itself: a branch that
  is behind moves nothing back.
- A ledger in a branch is an agent's claim, not a fact. The live view adds to main only status changes and new tasks,
  only from a ledger its validator accepts, and never for a task owned by you or the reviewer, which moves only in
  main. Decisions, milestones, capacity and the launch gate are never applied; the page shows them, to check.
- A change applies when main still holds the session's starting status, or already holds the same one. Otherwise it
  is a conflict and main's status stays, as when two sessions change one task differently. One id added by two
  sessions with different content is flagged, never merged.
- main's figures stay main's; what the sessions declare is counted apart.
- What branches declare never grows the page without bound: a card names 40 tasks, then a count; the page holds the
  details of 500 tasks at most; what waits for you lists 30 items, then a count.

### What a session may be called

- **Ready for your merge go**: committed, quiet for `--active-minutes` (15 by default), its modified files read,
  nothing refused; with a ledger, every task it works on in review or done in its own ledger; without one, a local
  branch pushed as it is (a branch that lives only on the remote is pushed by nature, which says nothing).
- **Ended**: all in main, its files read, and every task it worked on done or dropped in main. Without a ledger
  nothing says a session is finished, so none is ever called ended: quiet and merged may still mean waiting for a
  review.
- A session whose modified files were not read is never called ready nor ended, and `--resume` says so.
- Stashed work, detached commits no branch holds, an unreadable HEAD or an uncertain symbolic branch chain also
  prevent a readiness or completion claim. A stash that cannot be attributed safely holds back relevant cards;
  unknown Git distances are shown as unknown, never as zero. These safeguards do not make the board a cleanup tool.
- "In main" means reachable from main. A branch merged by squash or by rebase (a common pull-request flow) keeps its
  own commits, so it stays listed until you delete it. Held by a worktree, it may read "ready for your merge go" all
  that time; with no worktree, it loses that reading once it has been quiet for the stale period (`--stale-days`) and
  is then listed only. The board compares no patches.

## Security model

flightboard reads a repository where agents write. It treats everything there as data, and assumes a session might
try to plant a trap for the next program that reads its folder.

**Git.** Before any git command on the repository, flightboard looks at its `.git` with `lstat` and small reads, never
through a link. git itself follows, at every command, a link planted on one of its entries (config, index, info,
objects, refs, logs, shallow, reftable, a split index's shared file, the state of a merge, a rebase or a bisect…, and
the direct entries of `refs`, `refs/heads`, the remote's refs, `objects`, `objects/info`, `objects/pack`, `logs/refs`,
the branches' reflogs and the rebase and sequencer folders), a configuration include (`include`, `includeIf`),
`core.worktree`, a `commondir` file and borrowed objects (`objects/info/alternates`), and it waits on a pipe planted
where it expects a file: if flightboard finds one, it runs no git command on the repository and says why. The small
files the board reads itself (a HEAD, a `gitdir`, a reflog) are read only when they are regular files, never waited
on, never through a link. It reads no repository with a reftable ref store (whose `tables.list` names the files git
opens) or a SHA-256 object store (where the empty tree the board names would be a ref name a session could write), and
says so. The configuration is read by the installed git itself, from a copy of its bytes on git's standard input
(`git config --file - --no-includes`, with no system or global configuration and no repository around it), so no
spelling git accepts (a byte order mark, several headers on one line, a value carried on to the next line, a carriage
return alone) hides one of these; a configuration git itself could not parse stops the board too. Then a fixed list of
reads, each with an explicit `--git-dir`, runs:

- with the attributes of git's empty tree (`--attr-source`), no user attributes, excludes or mailmap file and no diff
  order file (a path there could name a network share), so no textconv and no LFS program;
- without the multi-pack-index (a pack name in it is a file name git opens as written, `..` included), with the
  commit-graph only when each line of its chain is a plain object id (git opens each line as a file name too), and
  following no rename in a history walk;
- using full SHA-1 ids for revision arguments, with ambiguous-ref checks disabled. Symbolic targets are parsed as
  data and checked against the shared ref listing; git counts no stash, and reflogs (including stash and detached
  HEAD moves) are read by the board itself, through plain folders (git, finding
  none it can read, would look up `refs/tags/<name>` and the like), so git never looks for `.git/<id>` or
  `refs/tags/<name>`;
- with sparse checkout off for the commands that read index names the board has not checked yet (`git ls-files`,
  `git check-ignore`): git would otherwise look up on disk each skip-worktree name of the index, wherever it points,
  since it checks none of them. `git status`, run only once every name has passed the checks below, keeps the
  repository's own sparse checkout, so a file a session wrote outside its sparse patterns counts as modified, as git
  counts it. git never turns a full index into a sparse one (`index.sparse`) and reads every index with one thread
  (`index.threads`), entry after entry, as the board walks it. An index git would take for a sparse one (one entry
  that is a folder is enough) is never handed to git, which writes into `.git/objects` to read one, nor is a split
  index, whose shared part git touches at every read: that worktree's modified and new files are not read;
- without ever fetching (`GIT_NO_LAZY_FETCH`): a partial clone's remote is never asked for a missing object, so no
  upload-pack, ssh or other program its configuration names starts. git older than 2.45 ignores that switch, so with
  it a partial clone (a promisor remote, a remote with a partial clone filter, or `extensions.partialClone`) is not
  read at all, and the board says why;
- with every filter driver the configuration defines switched off for the whole reading (`-c filter.<name>.clean=`
  and its kin), whatever attributes name them meanwhile. An unusual driver name, more than 40 drivers, or a filled
  `.git/info/attributes` stop the reads of modified files, and the board says so;
- never walking untracked content: a `.git` file planted in a new folder could otherwise send git to a network share;
- after a check of every path the index tracks, done on disk without looking through any link: a tracked file turned
  into a folder or a link, a submodule holding a `.git` or replaced by a link, a link in place of a tracked folder, a
  tracked name that leaves the worktree or is not UTF-8 (the board would look up another path than git), a tracked
  path of 260 characters or more on Windows, or more than 50,000 tracked files keep `git status` out of that worktree;
- on Windows, with the real git rather than one of its launchers (`Git\cmd`, `Git\bin`), so that the 8-second
  timeout stops git itself (killing a launcher would leave its git running), and with `core.longpaths` off: git then
  reaches no path of 260 characters or more, which the board's own checks may not see (Windows' default) and would
  take for a deleted file;
- without optional locks (a reading never rewrites a session's index), replacement objects or grafts (neither a
  `refs/replace` entry, whatever `core.useReplaceRefs` says, nor a line in `info/grafts` changes what main's commits
  hold), fsmonitor or signature checks, with git found by an absolute path and an environment cut down to a short
  allowlist: no API key reaches git or anything it starts.

There is no `git diff` command (`git status` compares files the same way, with the settings above), no `git log -g`
(the board reads the reflogs); revision arguments passed to git are full SHA-1 ids.

**Paths.** Worktrees are found in `.git/worktrees/<id>`, never through `git worktree list`. A folder is read only when
it is the main checkout, a direct child of an internal worktree folder (`.claude/worktrees`, and those you name), or
an explicitly authorized local external root itself or one or two plain components below it. External worktrees must be
registered in this repository and their marker must match its admin folder. These boundaries are checked before
reading content. The board's own reads then
follow no link, junction or reparse point, so no path of a worktree leads them to a network share. A worktree
anywhere else, or one whose admin folder is unusual (a `commondir` other than `../..`, a link or a pipe on its HEAD,
index, shared index, gitdir, info, logs, reftable or a file of a merge or rebase in progress, a `config.worktree` that
sets more than the allowed booleans or the exact `codex.localenvironmentconfigpath = __none__` marker), is never read:
it stays a card, by its name, with the
reason.
The Codex marker is metadata and is never opened as a path; other values of that key remain refused.
The admin folder's files are read as git reads them (a `commondir` of `../..` with only a line end, say), so that the
board and git never mean two different folders. Run from a folder whose `.git` is not a plain git folder of its own (a
worktree the board does not read, a submodule, a checkout whose git folder lives elsewhere, an odd or empty `.git`),
the board reads nothing and never looks at what a `.git` file names; it cannot tell where that repository ends, so
`--output` is refused there, and the snapshot, an error page, may go only to the cache folder.

**Server.** It listens on `127.0.0.1` and on `[::1]` at the same port (a browser tries `::1` first for `localhost`, so
no other program can answer there in its place), and checks every request before any work. It refuses a `Host` other
than `127.0.0.1:<port>` or `localhost:<port>` (DNS rebinding), an `Origin` from elsewhere (`null` included), a
same-site or cross-site `Sec-Fetch-Site`, the state loaded as a script, an image or a frame (`Sec-Fetch-Dest`), any
method but `GET` and `HEAD`, and any path but `/` and `/state.json`. A refused request never reads the repository.
The repository is read at most once every 5 seconds, counted from the end of the last reading, however many pages are
open; a failed reading is not repeated within that time. A reading shares a budget of 12 seconds by default
(`--read-seconds` accepts 12 to 120), with an 8-second cap per git run. The browser aborts a state request after the
configured budget plus 8 seconds (20 by default); the server's 10-second
socket timeout bounds incoming HTTP handling separately. A failed live reading displays an explicit error and removes
the previous session verdicts until a successful refresh. An open task detail is refreshed or marked unavailable.

**Page.** A Content Security Policy starting from `default-src 'none'` lets only the page's own script run, named by
its SHA-256, and only its own requests (`connect-src 'self'`); Trusted Types are required, no frame is allowed, and
`nosniff`, `no-store`, `no-referrer` and same-origin CORP and COOP are sent. The state carries its own sandboxing
policy and refuses any value JSON cannot hold. Every text read in the repository (titles, commit messages, branch
and folder names) is cleaned of control, format and bidi characters and only ever becomes a text node, never markup.
The page holds no absolute path of your computer and makes no network request but its own state.

**Disk.** Dashboard modes write only the snapshot: in your cache folder by default (made only outside the repository, and
never through a link planted in its place), or the `--output` file, which must be an `.html` file in an existing
folder that lies outside the repository and all authorized external roots once its links are resolved, whichever
folder of the repository the board
runs from (one it can read: see Paths). It is written whole through a new file, then swapped in, never written through
an existing file.
The optional Windows startup helper additionally stores its copied engine, configuration, status and rotating logs
under your local application-data folder, and manages its shortcut in your user's Startup folder. It does not write
in an observed repository or authorize additional worktree roots.

**Scope.** The board approves nothing and authorizes nothing: it reads.

**Limits, said plainly.** A session that can write in `.git` can plant a finer trap than the ones the board looks for (a
link on one object file, say), or race a reading: rewrite a file the board has just checked (a new filter driver and
`info/attributes`, a commit-graph chain) before git reads it. git would then follow it, a network share included. Any
git run in that repository — by Claude Code, an editor or you — meets the same trap: the board does not widen that
exposure, it narrows it. Links on the entries of `.git` listed above are refused, but not every file of `.git` is
looked at: a link on another file git opens by name stays possible, be it one loose object, one ref or reflog file
inside a folder of branches, or any entry of `.git` or of a worktree's admin folder that a symbolic ref
(`ref: <name>`) or a reflog line names (in a detached worktree, `git status` looks up the name its last checkout moved
to); a pipe there makes git wait until the 8-second limit, and the reading fails. The board trusts what the refs say,
remote-tracking refs included: a session that can write refs can make its
branch look merged, as it could by moving `main` itself; the page and `--resume` report a fetched remote ahead of local
main, a remote-only baseline, divergence, or a guess from the checkout's branch. git runs with the worktree it reads as its
working folder (Windows searches that folder last for libraries). A browser extension with access to the site can
read the page. See [SECURITY.md](SECURITY.md) to report a vulnerability.

## Limits

- "Writing now" means a file or a commit was just written. A session that thinks, reads, waits for CI or for your
  answer looks quiet.
- A session that marks its task in progress only when it commits stays "planned" in the live view until then; the
  board infers the task from the branch name and its commits, without counting it.
- A branch pushed by a cloud session shows only once fetched: the board never fetches. When a session went on
  elsewhere while its local worktree stayed behind, the board reads the local worktree and says it is behind its
  remote.
- A new folder is looked at three levels deep. Ignored deeper down, or holding a nested repository of its own, it
  counts as a new file: the error leans the safe way, and the session is never called ended for it. A folder that
  cannot be listed (its permissions, say) is never taken for an empty one: that worktree's new files are not read.
- A session whose reading fails within a successful snapshot is marked unreadable. If the whole live reading fails,
  the page removes the old session verdicts and announces the failure. Retrying never turns old data into evidence
  that a session has finished.
- When a worktree's modified files are not read, its activity is "unknown", unless its last commit, a new file the
  board lists or the worktree's creation is within `--active-minutes` (15 by default): it then reads "writing now",
  never "wrote recently" nor "quiet".
- The forecast is the roadmap ledger's own model, from the remaining work and the declared capacity, not a
  measurement.
- An external worktree is listed but its files are unread unless its local root was explicitly authorized with
  `--worktrees-root` and its path meets the registration, depth and plain-folder checks above. A worktree can be the
  root itself; any one or two child components must use plain names: spaces, unusual characters and trailing dots
  are refused there. Matching the exact root does not bypass admin, duplicate-target or reciprocal-marker checks.
- A partial clone (`git clone --filter=...`) needs git 2.45 or later, and objects it never fetched (the ledger in an
  old commit, say) are simply not read: the board never fetches them. In a clone without trees (`--filter=tree:0`),
  git cannot find the commits that changed the ledger: main's older history is then not read, and the page says so
  (without a ledger, it is read).
- A very long history is read as fast as git can when it has a commit-graph (`git gc` and `git maintenance` write
  one). Without one, or with a chain the board does not trust, a walk can exceed its 8-second command limit. The
  affected history or branch listing is then unread; exhausting the shared reading budget (12 seconds by default) can fail the
  whole refresh. The page reports incomplete or stale evidence instead of establishing a clean state.
- A worktree with a sparse index (`git sparse-checkout set --sparse-index`, `index.sparse`) or a split index
  (`core.splitIndex`, `git update-index --split-index`) has its modified and new files unread: git writes into
  `.git/objects` to read the first, and touches the shared part of the second. A sparse checkout without a sparse
  index is read as git reads it. So is an index up to 64 MB; a bigger one has its modified and new files unread too.
- A git configuration over 1 MB, or one git lists past 4 MB (git repeats a section's name for each of its keys, so a
  long subsection name over many keys lists far bigger than it is), is not weighed: the repository is not read, and
  the page says its configuration is unreadable.
- On Windows, a worktree tracking a path of 260 characters or more (counted as Windows counts them: a character
  beyond the basic plane, an emoji say, counts twice), or a name with a part ending in a dot or a space or named after
  a device (`nul`, `con`, `com1`…), has its modified files unread, and a repository whose own paths reach that length
  cannot be read: the board runs git with `core.longpaths` off.
- A reflog is read from its last 2 MB: older moves of main then come from its first-parent line, marked approximate.
- Stash attribution and detached history are conservative and bounded. Unreadable or truncated evidence can hold
  sessions back; an old detached commit absent from retained reflogs may no longer be discoverable. Inspect Git
  directly before removing a worktree or branch.
- A cutoff in tracked status, new-file enumeration or a timed-out reading is incomplete evidence, not a clean tree.
  Unread files and unknown states block readiness/completion; activity times, inferred task ids and short commit
  lists are clues, not a transcript or proof of provider activity.
- On Linux or BSD under a locale that is not UTF-8, with Python older than 3.15, a tracked name beyond ASCII keeps
  `git status` out of its worktree: run the board under a UTF-8 locale, or with `python3 -X utf8`.
- A folder of `.git` holding more than 50,000 entries is refused, and the board says so; the folders of branches and
  of their reflogs, which a big repository may fill, are read in full.
- macOS ships git 2.39 with its developer tools, too old for the board: install a newer git (Homebrew, say). On a
  case-insensitive macOS volume, give `--repo` with the folder's own case. A Windows `subst` drive is resolved to its
  real folder, while git keeps the drive's paths: run the board from the real folder.

## Development

Session attribution reads up to 1,000 commits and 4,000 characters per commit subject; only eight commits are
displayed on a card. A failed or incomplete history, or a subject past that cap, blocks ready/ended conclusions.
The HEAD and stash reflogs must be readable in full within 1,000 entries and 2 MB. Crossing those bounds is unknown
work, rather than evidence that the session is clean.

```bash
python3 -I -B -m unittest discover -s tests -t .
```

The tests build real git repositories with worktrees, branches and planted traps; they need git 2.41+ and nothing
else. A French version of this document is in [docs/fr/README.md](docs/fr/README.md).
These checks use local fixtures; they do not certify real Claude, Codex or third-party provider sessions, nor
desktop-chat startup behavior.

## License

Apache-2.0. Copyright 2026 Technologies CoreXalt Inc.
