<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
# Optional Flightboard Assistant — proposed boundary

Status: design proposal, not an implemented provider integration. No API-key
entry, model call, automatic monitoring or paid service is enabled by this
document. The existing dashboard and its deterministic overview remain useful
without this optional mode.

## Product shape

Use one Flightboard with an optional Assistant mode. The user chooses a
supported provider and model, supplies their own API key, previews the context
and requests an analysis. One small transport interface can have several
reviewed provider adapters; an arbitrary provider key alone does not establish
API compatibility.

The assistant explains observed gaps, identifies what evidence is unavailable
and prepares proposals for the existing action briefs. It cannot change a task,
run a command, publish a branch, merge a PR or activate a product gate.

## Data boundary

The provider receives a dedicated allowlisted projection of an already
completed, cached Flightboard view. It does not receive the collector, a path
to the repository, file contents, repository tools, a shell, a browser or a
mechanism for requesting additional local data.

Do not send raw state.json. Its strings already include information derived
from local files, including task titles, paths and commit subjects. A model
having no repository tool does not make every dashboard field safe to send.

The default projection contains only bounded structured observations:

- A schema version, context identifier, observation time and freshness limits.
- Coverage and synchronization states, with exact versus unknown counts.
- Main and local declared-progress counts with their distinct denominators.
- Coded alerts and a bounded publication summary using opaque target IDs.
- Evidence-reference availability and provenance, without claiming that tests
  were executed or that referenced artifacts were inspected.

Repository identity, absolute paths, branch names, commit subjects, task titles,
free text and evidence contents are excluded by default. Any later option to
include more data must show the actual expanded payload before transmission.
The selected provider necessarily receives the submitted payload; no promise
about its retention or use should be inferred from this local boundary.

## Key and transport handling

Keep the key in private server memory for the current session by default, with
an explicit forget control. Do not persist it in repository files, public
settings, URLs, logs, command arguments or browser local storage. Optional OS
credential-vault persistence can be a later feature.

Send provider requests from a separately bounded server-side worker, keeping
the browser's existing same-origin connection policy. The provider destination
comes from reviewed configuration, never from a ledger or model response.
Provider adapters must not load arbitrary user-supplied code. A custom local
model endpoint would need a separately explicit configuration boundary.

New assistant POST routes would need an unpredictable session token, origin
checks, request-size limits and a narrow handler. The current read-only
server's general POST rejection must not be relaxed for unrelated routes.

## Execution and results

Start with manual analysis, one bounded request at a time, with time, output
and token limits. The assistant consumes the completed view cache; it must not
trigger Git, a filesystem scan or another GitHub observation. Normal dashboard
refreshes and the initial page must not wait for a provider.

An eventual automatic-follow-up option requires explicit activation, a rate
limit and a visible usage budget. Do not retry an ambiguous paid request as if
it were known to have failed before provider admission.

Validate the returned structured result: bounded text, known observation IDs
and proposals attributed to the model. Render output as text, never trusted
HTML or executable instructions. References must resolve to observations in
the submitted context. A model cannot raise a declaration or an evidence
reference to a higher verification level.

Cache analyses by semantic context, provider, model and policy version; show
their age and invalidate their conclusions when relevant facts or freshness
change. Prepared prompts remain reviewable by the user before being passed to
an agent. Provider adapters should first be qualified with fakes and canaries;
a real paid smoke call is a distinct, explicit test.
