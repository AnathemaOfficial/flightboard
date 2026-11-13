<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
# Large-repository capacity checks — 2026-11-13

`--max-worktrees` accepts 1 to 1000 registered worktree admin entries, with 100 as the default. The cap does not
allocate worktrees or add read scope. A set over the chosen cap is refused, rather than silently truncated.
The shared reading deadline (12 to 120 seconds), each Git command's 8-second cap and the 50,000-entry preflight
budget remain separate limits.

## Isolated content-reading benchmark

On Windows, the test repository contained one shared commit and two tracked files per worktree. Ordinary admin
files, reciprocal markers and copied valid indexes were created in an isolated directory. The external worktree
root was explicitly authorized; modified files were then checked by the real Collector, not a mocked Git reader.
`--max-branches 0`, `--max-worktrees 1000` and `--read-seconds 120` were used throughout.

| Registered worktrees | First reading | Following reading | Cards, including checkout | Worktrees with detected changes |
| :- | -: | -: | -: | -: |
| 300 | 21.835 s | 22.422 s | 301 | 18 |
| 400 | 30.902 s | 28.000 s | 401 | 24 |
| 500 | 39.679 s | 39.401 s | 501 | 30 |
| 1000 | 75.756 s | 74.583 s | 1001 | 59 |

Every reading completed within its deadline, with every worktree's files read and no session omitted. "First"
means a new Collector with empty Flightboard caches; the operating-system disk cache was not cleared. These are
small-content synthetic measurements, not a capacity guarantee for an arbitrary repository or computer.

## Existing-repository qualification

A separate existing repository had 267 registered worktrees, extensive history and retained working changes.
It previously returned `too_many_worktrees` with no cards. After authorizing its existing worktree locations and
using `--max-worktrees 300 --read-seconds 120`, the first Collector reading took 95.353 seconds and the following
reading took 40.835 seconds. All 267 worktrees were read, with 298 cards including the checkout and selected
branch-only sessions. Another 125 branch-only sessions remained outside the default 30-branch selection, as
reported by the page.

That profile retains a cap of 300. Raising its cap alone would not change the cost of its current 267 worktrees,
but these measurements do not qualify 400, 500 or 1000 equally complex worktrees within 120 seconds.

## Regression coverage and remaining limits

- Incremental discovery checks cover 300, 400, 500 and 1000 admins; the Collector retains every card at 1000.
  That regression deliberately leaves external files unauthorized and verifies that no unread card is called ready.
  It is distinct from the authorized content-reading benchmark above.
- A 1001st registered admin is refused at a configured cap of 1000.
- Shared entry and time budgets, exact-root authorization, reciprocal markers, links and duplicate admins retain
  their refusal behavior.

Capacity depends on file counts, history, working changes, storage and caches. Measure the intended repository;
the configurable ceiling alone cannot establish its supported workload. No provider conversations or APIs are read.
