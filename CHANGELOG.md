<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
-->
# Changelog

## Unreleased

- Add a deterministic agent briefing with source-linked alerts, evidence checks
  and proposed next actions, copied from the page or read through `/briefing.json`.
- Reuse the existing snapshot, cache and refresh loop for the briefing.
- Remove the optional LLM advisor, provider configuration and automatic LLM
  monitoring; agents can consume the briefing through their existing tools.

## 0.2.0 base

- Add the Git/GitHub publication overview, unique commit counts, grouped branch
  stacks, open PRs and uncommitted work, independently of task status.
- Show registered-worktree file and working-ledger coverage explicitly.
- Add opt-in, bounded GitHub metadata observation with a separate five-minute
  cache, explicit freshness and no fetch or repository writes.
- Preserve the parallel reader, shared deadlines, graph cache, initial-page and
  background-tab refresh optimizations.
- Correct canonical GitHub URL casing and remote-card deduplication for renamed
  upstreams found during PR review.
- Add deterministic installable archives, checksums and an exact-commit release
  manifest. Publish a stable package after each validated `main` update.

Stable distribution patch numbers identify CI runs; the exact source commit is
recorded in each release manifest. See [the release policy](docs/releases.md).
