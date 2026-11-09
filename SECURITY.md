<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
# Security policy

## Reporting a vulnerability

Please report a vulnerability privately, through GitHub's **Report a vulnerability** button on this repository's
**Security** tab (private vulnerability reporting). Do not open a public issue for it. Say what you found, how to
reproduce it, and what it lets an attacker do. You will get an answer, and credit if you want it, once a fix ships.

Only the latest release is supported.

## What flightboard defends against

flightboard reads a git repository where coding agents write: their worktrees, their branches and their copies of the
task ledger. It assumes any of them may be hostile and implements the checks below. These checks reduce exposure;
they are not an isolation boundary against a process that can rewrite `.git` while it is being read.

- **No program of the repository ever starts.** No filter, textconv, LFS, fsmonitor, hook, external diff or signature
  program: attributes come from git's empty tree, every configured filter driver is blanked for the whole reading,
  git runs no command on the repository where `.git` holds something git would follow, and no `git status` in a
  worktree whose index does (a tracked file turned into a link, say). git never fetches:
  a partial clone's remote is never asked for a missing object (with git older than 2.45, which cannot be kept from
  fetching, a partial clone is not read at all: a promisor remote, a remote with a partial clone filter, or
  `extensions.partialClone`).
- **File reads reject links they can identify.** No symlink, junction or reparse point, and no `.git` file planted in a new folder: every
  folder on the way is checked with `lstat` and must be a plain folder (never a device, which is what Windows answers
  for a last part named `nul`), and untracked content is listed by flightboard, never walked by git.
- **git is not run on the repository** when `.git` holds a link on one of its entries (or among the direct entries of
  its refs, objects, reflogs and rebase folders), a pipe, a socket or a device there, a configuration include,
  `core.worktree`, a `commondir` file, borrowed objects, a reftable ref store or a SHA-256 object store, since git
  would follow them (or wait on them) at every command. The configuration is read by the installed git itself, from a
  copy of its bytes on git's standard input with no include followed, so no spelling git accepts hides one of these,
  and a worktree's `commondir` must read `../..`. Replacement objects (`refs/replace`), grafts, mailmap files, a diff
  order file and the multi-pack-index are never read, nor a commit-graph chain unless each of its lines is a plain
  object id. The board reads stash and detached-HEAD reflog metadata itself to avoid treating held work as finished;
  it does not ask git to count or apply a stash. Revision arguments given to git are full SHA-1 ids. Symbolic targets
  are parsed as data and checked against the shared refs, rather than passed back as revision arguments. The board
  checks index names before git reads them, refuses a `.gitignore` that is a
  pipe, and, on Windows, no path of 260 characters or more (`core.longpaths` off). An index git would read as a sparse
  one, or a split index, is never handed to git, which would write into `.git/objects` or touch the shared part to
  read it; git reads every other index with one thread, as the board walks it. A worktree folder whose name ends with
  a dot, and on Windows a tracked name with a part ending in a dot or a space or named after a device (`nul`, `con`,
  `com1`…: Windows reads them as another file depending on where they fall in a path), or one that is not UTF-8, keep
  `git status` out.
- **The page is served to this computer only** (`127.0.0.1` and `[::1]`), after Host, Origin and Sec-Fetch checks
  that stop DNS rebinding, other sites and other local pages.
- **Only the page's own script runs**: a Content Security Policy names it by its SHA-256 and requires Trusted Types;
  every text read in the repository becomes a text node, never markup.
- **The lines agents read carry no free text from a branch.** `--resume` keeps verbs, ids, names and counts, and a
  name may be one a session chose (a branch or a worktree folder: letters, digits, `.` `_` `/` `-`, 100 characters at
  most); titles, quotes and commit messages read in a branch stay on the page.
- **External worktrees require explicit scope.** `--worktrees-root DIR` authorizes a local absolute root supplied
  by the user; it is repeatable. Only this repository's registered worktrees, one or two plain components below that
  root, can be read. Root and worktree paths must pass the plain-directory and marker checks: UNC/device paths,
  symlinks, junctions and reparse points are refused. A root does not authorize scanning other repositories or
  arbitrary descendants. It can cover Codex's `<root>/<hash>/<project>` layout without trusting a path found in a chat.
- **Nothing is written** but the snapshot, outside the repository and every authorized external root, through a new
  file, never through a link. Run
  from a folder whose `.git` is not a plain git folder of its own (a worktree the board does not read, a submodule, a
  checkout whose git folder lives elsewhere), the board reads nothing, never looks at what a `.git` file names, and
  writes the snapshot only to the cache folder.
- **Incomplete evidence does not prove completion.** Unreadable HEADs, symbolic chains, distances or file listings
  remain unknown. Stashed work and detached commits can hold back relevant cards. A complete reading has a shared
  12-second budget and git runs keep their 8-second cap; the browser aborts a state request after 20 seconds. The
  server's separate socket timeout is 10 seconds. If a live refresh fails, old session verdicts are removed and the
  failure is announced visually and accessibly. The next successful reading restores the current view.

The full model, and what it does not cover, is in the [README](README.md#security-model).

## Known limits

A session that can write in `.git` can plant a finer trap than the ones flightboard looks for (a link on one loose
object, on one ref or reflog file inside a folder of branches, or a link or a pipe on any entry of `.git` or of a
worktree's admin folder that a symbolic ref or a reflog line names, such as the target of a detached worktree's last
checkout: git follows the link, or waits on the pipe until its time limit), or race a reading by rewriting a file the
board has just checked.
Any git run in that repository meets the same trap; flightboard narrows that exposure, it cannot remove it. A browser
extension with access to the page's address can read it.

Refs and reflog messages are local evidence, not authenticated provider activity. A process that can write them can
mislead the board. Local main remains the baseline when its fetched remote is ahead; remote-tracking refs are not
proof that a merge has been pulled. Stash attribution and retained detached history are bounded, and old commits
missing from reflogs may not be discoverable. A ready/ended card does not authorize deletion, merging or approval.
The board reads no conversations and does not connect to Claude, OpenAI or other model providers.
