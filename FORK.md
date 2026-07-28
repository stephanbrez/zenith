# Fork status

This checkout is a **fork-primary** line of
[Intelligent-Internet/zenith](https://github.com/Intelligent-Internet/zenith)
(remote `origin`), published at
[stephanbrez/zenith](https://github.com/stephanbrez/zenith) (remote `fork`).
`local/integration` is the durable branch this fork actually runs; it may
diverge from upstream. Decided 2026-07-27 after upstream review latency made
PR-first development untenable (at the time: one upstream merge in 24 days,
10+ open PRs, zero review engagement on this fork's PRs #26 and #31).

## Working rules

- Develop on small topic branches off `local/integration`; test with
  `uv run pytest` in `zenith/`; merge fast-forward; push to `fork`.
- **Pull freely, push selectively.** Cherry-pick useful changes from
  upstream's *open PR queue* (not just merges), preserving authorship.
- File an upstream PR **only when marginal cost is near zero**: the change
  is self-contained, rebases cleanly onto `origin/main`, and depends on no
  unmerged work. Never shape code for upstream mergeability at the expense
  of what this fork needs.
- On upstream sync, prefer upstream's variant of anything carried here and
  drop the local copy to minimize drift.
- Keep the delta table below current: add a row when a change merges to
  `local/integration`, update it when upstream merges/rejects anything.

## Independence tripwires

Stop filing upstream PRs entirely (pulling continues) when **any** fires:

1. PR [#26](https://github.com/Intelligent-Internet/zenith/pull/26) or
   [#31](https://github.com/Intelligent-Internet/zenith/pull/31) reaches
   **~60 days with zero maintainer interaction** (≈ mid-September 2026).
2. Upstream merges something **semantically conflicting** with this fork's
   gate/ownership changes (`revalidates`, `follow_up`, `file_finding`).
3. A change here gets **designed differently than wanted** just to stay
   mergeable upstream.
4. A PR from this fork is **rejected on design direction** (not on
   mechanics like "rebase" or "split this up") — the review channel works
   but points away from where this fork is going; split off rather than
   argue.

If a tripwire fires: keep this file as the delta record, keep cherry-picking
upstream work with authorship intact, and do not rename/detach the fork —
a batch offer of the delta remains possible if upstream revives.

## Delta vs `origin/main`

Newest first. "fork-only" = deliberately not filed upstream (design-level
change or depends on unmerged work).

| Commit | Change | Upstream status |
| --- | --- | --- |
| `02aaf73` | Scoped `CODEX_HOME` for the codex terminal reviewer | not filed (depends on PR #31) |
| `2fa9a62` | Terminal reviewer: `_meta` settingSources/skills isolation (claude) | [PR #33](https://github.com/Intelligent-Internet/zenith/pull/33), filed 2026-07-27 |
| `32907a2` | Wave transition events also written to the log | not filed (depends on progress notifications) |
| `3e3a4d2` | `follow_up` patch op — ownership transfer from cleared work tasks | fork-only (schema change) |
| `a7c462f` | Findings channel: worker/validator prompt guidance + `file_finding` tool | fork-only (tool-surface change) |
| `426495b` | `Task.revalidates` — explicit gate revalidation + supersede coverage guard | fork-only (schema change) |
| `81aeffd` | Progress notifications + heartbeat during blocking waves | not filed (depends on PR #25) |
| `ea38d25` | Orchestrator prompt: digests are hypotheses, not evidence | [PR #32](https://github.com/Intelligent-Internet/zenith/pull/32), filed 2026-07-27 |
| `3ddf1a6` | Cherry-pick of upstream [PR #14](https://github.com/Intelligent-Internet/zenith/pull/14) (gate checkpoints + skill validation) | open upstream since 2026-07-02 |
| `6017363` | Cherry-pick of upstream [PR #25](https://github.com/Intelligent-Internet/zenith/pull/25) (wave lock held in worker thread) | open upstream since 2026-07-11 |
| `6d618ca` | `ZENITH_LOG_FILE` durable log | not filed |
| `6f3cc39` | Log ACP spawn command + `CODEX_CONFIG` per dispatch | not filed |
| `9b80498` | Route codex `-c` overrides through `CODEX_CONFIG` | [PR #31](https://github.com/Intelligent-Internet/zenith/pull/31), open, no review |
| `385d0ac` | Wire `--terminal-reviewer-provider`/`acp-command` through to config | [PR #26](https://github.com/Intelligent-Internet/zenith/pull/26), open, no review |

Background for the 2026-07-27 changes (`ea38d25`..`32907a2`): findings from a
real end-to-end mission, analyzed and verified against source in
[`zenith-harness-findings.md`](zenith-harness-findings.md) (repo root;
fork-only documentation, not part of any upstream PR).
