<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
# Optional LLM advisor

The live dashboard includes an optional advisor. It is disabled until the owner explicitly prepares a dossier and
consents to sharing it. Ordinary Flightboard reading, snapshots and `--resume` need no API key and make no LLM calls.
This implementation supersedes the board-only scope proposed in [optional-assistant.md](optional-assistant.md).
The panel is included on live pages, without a separate CLI enable/disable flag. File access and provider calls
remain inactive until the required consents are given; opening the panel does not authorize either. No key is saved.

## Choose the provider and information

Open **LLM advisor** on the live page. Choose an API protocol, base URL, model identifier and maximum output tokens:

| Protocol | Base URL example | Request |
| --- | --- | --- |
| OpenAI-compatible | `https://api.openai.com/v1` or your compatible provider's base | Chat Completions |
| Anthropic | `https://api.anthropic.com/v1` | Messages |
| Gemini | `https://generativelanguage.googleapis.com/v1beta` | GenerateContent |

Model identifiers are entered by the owner; Flightboard does not fetch a model catalogue. Protocol compatibility
depends on the provider/model. Unsupported parameters or provider errors produce a failed attempt, not a fallback
to another endpoint. Official OpenAI uses `max_completion_tokens`; other compatible endpoints use `max_tokens`.
The adapters follow the [OpenAI Chat API](https://developers.openai.com/api/reference/resources/chat),
[Anthropic Messages API](https://platform.claude.com/docs/en/api/messages/create) and
[Gemini GenerateContent API](https://aistudio.google.com/api-reference/generate-content).

For Anthropic API version `2026-10-21`, use a key scoped to a single Workspace. This configuration does not send
`anthropic-workspace-id`; credentials that can act across Workspaces require that additional header and are not
supported here. A Workspace-specific key may omit it, as documented in the Messages API header reference above.

For a local compatible model, explicitly enter an HTTP base URL on literal `127.0.0.1` or `[::1]`; a key is optional
there. Remote endpoints require HTTPS and an API key. URLs cannot contain credentials, a query or a fragment.
Redirects and environment proxies are not followed. Remote DNS must resolve to public addresses; the connection
pins a checked address while still verifying the TLS hostname. Provider calls happen in Python, not the browser.
The TLS context ignores inherited `SSLKEYLOGFILE` even in a non-isolated host: it creates no TLS key log and keeps
the standard client certificate, hostname and chain verification settings.

Enter a question, then optionally select exact files, one per line:

- **Repository files:** paths relative to this board's main checkout, such as `docs/architecture.md` or
  `src/engine.py`.
- **Local files:** absolute paths explicitly chosen by the owner, including files in another worktree or local
  evidence directory. A worktree's registration does not automatically authorize its source for the LLM.

First authorize reading the board observations and, separately, the selected repository/local files. **Prepare
preview** performs only local work. It freezes the observation, accepted file contents, source identifiers and
SHA-256 hashes. Review the complete JSON preview, omissions, base URL and model. Selecting a path is not consent
to transmitting it. A second, initially unchecked sharing consent is required before **Analyze**.

The API key is entered in a password field, cleared from that field when sending, and held only in process memory.
It never enters the board state, HTML snapshot, URL, log, localStorage or startup configuration. A one-off job uses
it transiently. Automatic monitoring retains it only for its active authorization. Process shutdown loses it.
Flightboard does not save credentials to disk or create provider accounts.

## One-off analysis and capped automatic monitoring

A one-off analysis consumes its approved preview. A further analysis requires a new preview and sharing consent.
Changes to the selected files after preview do not change the bytes of that one-off request.

Automatic monitoring requires an additional, initially unchecked consent to sharing **future versions of the same
selected files and board observations**, with the same question, provider, model and output cap:

- Check interval: **15–1440 minutes**, default 60.
- Total attempted calls for this authorization: **1–20**, default 4. This is a total cap, not a daily reset.
- Authorization expires after **24 hours**, even if calls remain. It also ends on revocation or process shutdown.
- The initial frozen dossier is analyzed immediately and consumes one call. Later intervals analyze only a
  meaningful context change. Scan timestamps and private cache expiration metadata do not spend calls.
- Failed provider attempts consume the cap too. No automatic retry, provider fallback or unbounded queue occurs.
- A blocked/unavailable reading is shown as such and consumes no provider call. Another check waits the full interval.

Monitoring can continue when the tab is hidden or closed. At a check, it uses the existing collector/cache; it
never overlaps a normal Git scan or changes the collector's worker, cache or deadline settings. A busy scan causes
that check to be skipped. An idle expired observation can be refreshed once for that interval, even without a page
poll. Opening the advisor panel again retrieves the current authorization and status without starting an analysis.

**Revoke and clear** stops future checks, clears the key, dossier and result from the service, and invalidates a
queued worker that has not begun. An already-started provider request cannot be recalled. Scope/provider controls
remain locked while a request or authorization is active; revoke before changing them. If a response is lost, the
page reconciles status instead of automatically sending the analysis again.

Usage counters are the input/output token counts actually returned by the provider. Missing counters remain
unknown. There is no invented price estimate; the call and output-token limits do not establish a dollar budget.

## Boundaries and performance

The dossier accepts at most **12 selected files**, each at most **32 KiB**, and at most **128 KiB of compact context**.
Board fields are filtered and bounded; a partial observation and omitted files remain explicit. Files are exact,
ordinary UTF-8 text. No recursive directory scan, whole-repository upload, binary upload, symlink/junction/reparse
point, hardlink, device, pipe or `.git` file is read. Obvious credential filenames and secret patterns
are refused. These checks cannot guarantee that an accepted document contains no sensitive information; the preview
and sharing consent are still necessary.

UNC paths are refused, and Windows mapped network drives are rejected before file lookup. On Linux and macOS,
mounted network filesystems (for example NFS or SMB) are not detected or rejected: an explicitly selected file on
such a mount may be read. Select repository and local files on trusted local filesystems.

The model receives a frozen dossier, not filesystem tools. It cannot enlarge the selected scope, open another file,
execute a command, edit a task, run tests, commit, push or merge. Code, evidence and architecture text can support
specific observations and proposed agent prompts; an LLM answer is not proof that an implementation ran, that tests
passed or that governance gates were satisfied. Results identify their observation time and remain advice.

One analysis worker and, only when enabled, one scheduler are separate from the Git collector. Network work has a
30-second total deadline, a 256-KiB request/response ceiling and a bounded textual result. The normal 10-second
page polling, five-second post-scan cache, bounded parallel reads, path-plan caches and background GitHub observer
remain independent. No advisor file reads, DNS lookup or provider call occur during ordinary page refresh.

The local endpoints `/advisor/preview`, `/advisor/analyze`, `/advisor/automate`, `/advisor/revoke` require JSON POST,
an exact same-origin Origin and a per-process page token. `/advisor/status` requires the same token. Requests have
bounded bodies and reject chunked encoding, duplicate keys/headers and non-finite JSON. The IPv4 and IPv6 listeners
share the same advisor, authorization, worker and limits. Model output is rendered as text under the existing CSP.

Validation uses synthetic credentials, fake providers and local HTTP fixtures. It does not spend a real API key or
certify every third-party provider/model; a real provider smoke test requires the owner's chosen key and consent.
