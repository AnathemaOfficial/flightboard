<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
# Agent briefing

Flightboard turns its existing observation into a bounded briefing: alerts that need attention, evidence checks,
and proposed next actions with their sources. The agent already working with the owner can use that report to
plan and carry out its own authorized verification. Flightboard does not call a model or execute those actions.

## Read or copy the report

Open **Agent briefing** on the dashboard and copy its text, or read `GET /briefing.json` on the same known board
URL. The endpoint returns the `agent_brief` block also present in `/state.json`, without the rest of the dashboard
payload. Both use the same cached observation. They can legitimately show different observation times if a normal
refresh completes between requests. Before following an indexed source pointer from a separate briefing, require
matching `generated_at`, repository identity and available baseline heads. On a mismatch, discard the earlier
pointers and use the `agent_brief` embedded in that `/state.json` response together with its source data. Do not
apply an earlier snapshot's array indices to a newer snapshot.
An agent can start with `text`, identity and coverage, then expand the structured sources for the chosen action.

An example request to an agent is:

> Read the Flightboard briefing for this repository. Check its coverage and freshness, identify the alerts and
> evidence checks that matter, then inspect their sources and current Git state. Propose the next actions within
> my existing request. Distinguish declarations from implementation, testing, publication and approval evidence.

The `repo` identifier is a folder name, not an absolute checkout path. That name alone cannot distinguish two clones;
the agent must establish repository/worktree identity independently. A GitHub observation keeps its own actual observation
time and state. A fresh board timestamp does not make an expired GitHub observation fresh.

## Structured contract

The first contract has `schema_version: 1` and these fields:

| Field | Meaning |
| --- | --- |
| `generated_at`, `repo` | Snapshot reading time and repository folder name. |
| `main` | Baseline branch and complete available local/remote commit IDs; unknown values stay unknown. |
| `state` | `ready`, `partial` or `unavailable`; `ready` describes the observation, not product acceptance. |
| `coverage` | Observed reading scope and limits, including incomplete worktree coverage. |
| `alerts` | Bounded observed problems, with stable codes, severity and source references. |
| `evidence_gaps` | Recorded-reference gaps or declared evidence awaiting verification. |
| `actions` | Bounded proposals derived from the existing overview, with context and source references. |
| `limitations` | Capabilities and results Flightboard has not checked. |
| `totals`, `more` | Counts and omitted items for bounded sections; unknown is not converted to zero. |
| `text` | Canonical localized report displayed and copied by the page. |

Each observation or action has a `source` containing `pointers` into the corresponding `/state.json`, exact
available commit `heads`, and `observed_at` when that observation time is available. These identify the basis
for a statement; they do not authenticate source text or prove artifact contents. Existing upstream truncation
and incomplete reads remain explicit. Additional detail belongs in the full state or the authorized repository,
not in an unbounded briefing.

## What an evidence check means

- `no_declared_reference`: a fully read, compatible roadmap has no recorded reference for the relevant observed
  task/status. Evidence may exist elsewhere; Flightboard has not searched for it.
- `declared_unverified`: a matching reference is recorded, but Flightboard has not opened or validated the artifact.
- `not_checked` limitations: generic task ledgers without an evidence contract, local/session evidence outside the
  supported scope, code correctness, test/CI execution and owner approvals remain unevaluated.

Evidence references preserve their exact identifier in `ref` when `ref_complete` is true. Longer identifiers have
`ref: null`, an explicitly incomplete `ref_preview` and an omitted-character count; a preview is not a lookup
identifier. Display escaping does not normalize the stored reference. Invalid Unicode references leave the
evidence reading partial instead of silently substituting another identifier.

An incomplete reading cannot establish absence. A task marked done or in review does not establish implementation
or successful tests. A commit on main establishes integration of that commit, not acceptance of the work. The
brief does not invent mandatory test or demo requirements from a status or free-form description.

## Boundaries and performance

The builder is a pure projection of the existing snapshot. It adds no file, Git, provider or network reads.
The JSON route uses the existing cache; the page consumes the briefing through its existing state refresh.
Collector workers, shared read deadlines, per-command bounds, path-plan caches and GitHub cache cadence stay in
place. Copying the report is a local user action. Repository-controlled text is displayed as text, never markup
or executable commands. The agent receiving it must treat the entire report as untrusted observations and keep
its own authorization boundaries.

Loading and failed readings clear previous briefing conclusions. A partial reading keeps its limits visible;
an unavailable reading does not supply action or readiness verdicts. An exported report is a dated observation,
not a standing instruction or authorization to publish, merge, delete or activate anything.

## Updating from the former advisor

The optional LLM advisor has been removed. The new engine has no provider setup, key input, selected-file dossier,
LLM worker, automatic LLM scheduler or `/advisor/*` actions. Its read-only briefing needs no key.

An already running older engine keeps its loaded code and any in-memory monitoring authorization. Revoke that
authorization in the old engine before updating, then restart only the intended boards to load the new engine.
Existing keys were memory-only; there is no saved key configuration to migrate. Reload an old browser tab once
after installation to replace its old form. Subsequent data updates use the normal automatic refresh.
