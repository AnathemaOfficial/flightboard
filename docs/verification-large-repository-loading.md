<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
# Large-repository loading verification — 2026-11-13

Collector measurements and full Windows/WSL suites are complete. The running-server verification is recorded below.

## Result and measurement method

The optimized four-reader Collector completed the existing 267-worktree repository in **37.799 seconds for its
first reading and 24.059 seconds for its next reading**. Both readings returned 298 cards, all 267 worktrees read,
and no unread sessions. Four readers are retained as the default for eligible larger sets.

The comparison below uses the same optimized code with parallelism disabled, then with two and four readers.
Each case starts with a new Collector and cleared text-plan caches; its second reading retains the caches produced
by its first. The operating-system disk cache was not cleared, and other desktop activity was not isolated. All six
readings use the same fixed observation time, repository settings, authorized worktree scope,
`--max-worktrees 300` and `--read-seconds 120`.

| Readers | First reading | Next reading | First Python CPU | Next Python CPU |
| :- | -: | -: | -: | -: |
| Sequential | 65.477 s | 40.371 s | 20.500 s | 19.000 s |
| Two | 42.717 s | 24.684 s | 27.422 s | 23.344 s |
| Four | 37.799 s | 24.059 s | 44.406 s | 38.219 s |

Four readers reduced elapsed time by approximately 42% on the first reading and 40% on the next reading compared
with the optimized sequential path. Compared with two readers, four saved 4.918 seconds initially and 0.625 seconds
on the next reading, while using more Python CPU. CPU values use `time.process_time()` for the Collector's Python
process, including its threads; they exclude Git subprocess CPU and are not total machine CPU measurements.

Strict equality checks confirmed the complete views and card order across sequential, two-reader and four-reader
runs. Every run returned `main.state = ok`, 298 cards, 267 worktrees and zero unread sessions. This checks output
preservation for the measured repository; it does not establish a universal speedup or capacity guarantee.

The earlier `docs/verification-large-repositories.md` measurement was 95.353 seconds initially and 40.835 seconds
subsequently, before this optimization. That historical comparison is indicative: observation conditions and disk
cache state differ. The table above is the controlled comparison of reader counts within the optimized code.

## Opening the page and completing a reading

The live HTML route no longer performs a Collector reading or waits behind one. It returns a fresh completed view
when available; otherwise it returns a neutral, localized loading view and the browser immediately requests
`/state.json`. Pending HTML contains no provisional sessions or readiness verdicts. This lets the page appear
before a long repository reading finishes; it does not make the full data available immediately.

The state request still waits for a complete reading. The browser's ordinary refresh starts 10 seconds after the
preceding request finishes. A read failure removes prior verdicts, displays the failure, and can recover on a later
successful request. A static `--snapshot` still waits for its complete reading and does not poll. Git collection
is driven by state requests; opening no browser or making no state request does not start an automatic background
Git reading.

Local Event-controlled HTTP regression coverage verifies that GET and HEAD of the HTML route return while the
state route is blocked in a reading. The original server fails the new first-page regression, providing a red
baseline. After updating the installed Codex and Claude skills and stable startup engine, the live server returned
loading HTML in **0.006 seconds**. Its first measured state request joined an already-running reading and returned
in 6.529 seconds; this is not a cold-start measurement. After waiting past the server's five-second cache interval,
a new state request completed in **24.926 seconds**, with 298 cards, 267 worktrees and zero unread sessions.

The browser was observed first showing the French loading view with no session verdicts, then filling automatically
with the complete live board. The Windows supervisor restored the updated server with the same verified command,
port, reading budget, worktree cap and authorized roots. All eight saved repository configurations were preserved;
the other seven server processes retained their identities. Installed payload hashes matched the source.

## Bounded work and fresh observations

- Larger eligible sets use at most four independent Git readers. Small sets and custom readers use the sequential
  path. Results retain their input identity and order; Collector caches are published by the parent thread, and
  running workers finish before the reading returns.
- Readers inherit the same absolute reading deadline, filter settings and commit-graph policy. The 8-second
  per-command cap, configured total deadline, shared preflight entry budget and existing output limits remain.
- Commit relationships and bounded history can be reused by full immutable object IDs. Separate globally bounded
  caches reuse only path text components and parent-name plans; they retain no filesystem state.
- Working-file results are discarded between readings. Index bytes and names, ignore rules, directory contents,
  platform path policy, path length, links, reciprocal markers, authorized roots and modified-file status keep
  their current checks. Cached text or unchanged file timestamps do not establish that files are unchanged.
- Four workers bound concurrent tasks, not total process memory. File counts, bounded history results, working
  changes, storage and other activity continue to affect resource use and elapsed time. Increasing the worktree
  cap alone does not qualify equally complex sets of 400, 500 or 1000 worktrees within the reading deadline.

## Regression coverage

The change adds **27 Python regression tests**:

| Area | Added tests | Coverage |
| :- | -: | :- |
| Initial HTML | 4 | Metadata-only loading; fresh completed views; error invalidation; GET/HEAD during a blocked state request and hostile-Host refusal |
| Parallel reading | 12 | Fork context; four-task bound; result order; slow-job scheduling; sequential fallback; shared deadline and drained workers; cache publication; sequential/parallel equivalence; fresh working files, ignore rules and retained files; bad-index refusal and recovery |
| Text-plan caches | 11 | Immutable plans; eviction and size limits; concurrent parent plans; current platform/encoding/path-length policy; fresh directory contents, ignore rules, index names and link refusals |

Browser checks also cover neutral loading, immediate initial state fetch, the configured request timeout,
failure without an invented last-success time, removal of stale verdicts, and recovery.

## Completion record

| Verification | Result |
| :- | :- |
| Controlled existing-repository readings | Complete: six successful readings; strict complete-view and ordering equality; metrics above |
| Full Windows regression suite | `python -I -B -m unittest discover -s tests -t .`: 475 tests, 473 passed, 2 skipped; 304.910 s; exit 0 |
| Full WSL regression suite | `python3 -I -B -m unittest discover -s tests -t .`: 475 tests, 452 passed, 23 skipped; 75.490 s; exit 0 |
| Browser JavaScript checks | Complete: 11 JavaScript groups passed through test_live_page.py on Windows; Node unavailable in WSL |
| Hygiene and diff checks | Five hygiene checks, skill validation and `git diff --check` passed |
| Updated HTTP server | Loading HTML: 0.006 s; uncached following state request: 24.926 s; 298 cards, all 267 worktrees read; automatic browser loading and Windows restoration verified |
| Source revision and delivery | Uncommitted working tree on codex/fast-large-repository-reading, based on 0df4648070cb62aa1f7611c1fcea492345617b3c |

Both full suites emitted a `ResourceWarning` about a test subprocess while still completing successfully. Those
reported processes were absent when checked after the suites. Platform skips remain skips, not execution evidence.
No new GitHub CI run is associated with this uncommitted working tree.
