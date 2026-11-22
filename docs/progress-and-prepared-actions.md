<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
# Overview, progress and prepared actions

The overview answers three questions from the existing completed snapshot:
what needs attention, what progress the ledgers declare, and what an agent can
inspect next. It adds no Git command, GitHub request, file read or model call.

## Summary banner

A matching local main and GitHub main is one observation, not a verdict about
all local work. The banner also accounts for unread or excluded worktrees,
incomplete history, local commits, uncommitted files and remote freshness.
Incomplete reading takes priority over a reassuring synchronization message.
GitHub observation being disabled or expired remains explicitly unverified.
Loading, errors and a failed refresh remove actionable conclusions.

## Progress and evidence

Main's task counts and the combined local declarations have separate
denominators. New local tasks must not inflate the completion percentage in
main. Conflicting and uncommitted declarations remain identifiable.

A task marked done is a ledger declaration. A Git commit establishes that some
content was committed; it does not establish that implementation works or that
a test passed. Flightboard does not execute tests or open evidence artifacts.

Roadmap ledgers can supply bounded evidence references from the main ledger.
These are labeled as references, with their main provenance, rather than
independently verified results. They are not borrowed to validate a different
local status. The simple task-ledger format has no structured evidence
contract, so its evidence is explicitly not evaluated. Missing support is not
reported as zero successful tests or as a failed product validation.

## Prepared actions

Actions are deterministic inspection or preparation briefs based on the current
snapshot: restore reading coverage, inspect a publication stack, review an
uncommitted worktree, reconcile a tracking notice, or inspect an eligible next
task. A brief identifies the target, observed Git identities and known limits.
Displayed queue samples are not treated as a complete inventory.

Each brief is visible before the user copies it. Copying requires an explicit
click; when the browser clipboard is unavailable, the text can be selected and
copied manually. Stable identities preserve open details and keyboard focus
across refreshes. A copied brief asks the receiving agent to check current
facts; it does not grant publication, merge or product-activation authority.

There is no execution endpoint and no automatic status mutation. Existing
background polling and refresh on returning to the tab remain in place.

The [agent briefing](agent-briefing.md) consolidates these observations, evidence
checks and prepared actions into one copyable report and a compact JSON export.
It uses the same snapshot and needs no API key.
