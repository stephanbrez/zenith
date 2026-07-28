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
| `6c3fbb8` | Pin the ruff rule set (`lint.select` + `required-version`) so `ruff check` stops meaning something different per ruff release | fork-only for now; `upstream/ruff-rule-pin` on fork is ready to file (PR body below), held until #26/#31 get engagement |
| `64f24fa` | Escape env values in the codex `config.toml` writer (quoted ACP commands emitted invalid TOML) | [PR #34](https://github.com/Intelligent-Internet/zenith/pull/34), filed 2026-07-28 from `upstream/toml-env-escaping`; motivated by #31 but **no code dependency** — applies cleanly to `origin/main`. Upstream variant drops the reviewer assertion (needs #26) |
| `c76b945` | Custom worker ACP command cascades to same-provider validator/reviewer | on hold until #26/#31 get engagement; `upstream/acp-command-cascade` on fork is ready to file (PR body below) |
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

## Bug-hunting heuristic: configuration-variation boundaries

Every serious bug found so far (2026-07-27) lives where a default and an
override can disagree silently — the benchmark environment was almost
certainly default-config and context-clean, the one machine shape where
none of these are observable:

- ACP command cascade (`c76b945`): only fires with a custom worker command
  *and no per-role overrides*. Invisible if every role is set explicitly,
  or nothing is customized.
- codex-acp `-c` overrides (`9b80498`, PR #31): only fires on the npm
  adapter build, which ignores argv `-c` — invisible on whatever build the
  authors ran.
- Terminal-reviewer context injection (`2fa9a62`/`02aaf73`, PR #33): only
  *matters* when the user has global CLAUDE.md/AGENTS.md content worth
  leaking. A bare CI account has nothing to inject, so the reviewer's
  independence looks intact there.

When hunting for the next one, start where an override path exists but was
probably never exercised against a populated environment:

- `_ensure_claude_settings` "respect pre-existing files" path: a
  user-authored `.claude/settings.json` in the workspace silently skips the
  `defaultMode` fix — does every setting combination there still spawn?
- `ZENITH_*` env discovery in `config.py`: every `os.environ.get` with a
  fallback is a default/override pair; check each is actually reachable
  and validated (the reasoning-effort validation exists because one
  wasn't).
- Path relocations: `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, `ZENITH_HOME`,
  XDG-style moves — anything that hardcodes `~/.codex` or `~/.claude`
  instead of resolving the env var is wrong on relocated setups.
- Provider asymmetry: any feature implemented for one provider's adapter
  (claude/codex/hermes) with a "no-op" branch for the others — check the
  no-op is a decision, not an omission.

## Pending PR bodies

Drafted and reviewed, held per the working rules. File from the named branch
with the body below; delete the section once filed.

### `6c3fbb8` — ruff rule-set pin (branch `upstream/ruff-rule-pin`)

Hold until PR #26 or #31 gets maintainer engagement. This one is a shared-config
change that buys upstream more than it buys this fork — the fork controls its own
lock refreshes — so it is the least urgent of the held set. Title:
`chore(lint): pin the ruff rule set so CI stops drifting with the ruff release`

```markdown
## Problem

`[tool.ruff]` in `zenith/pyproject.toml` sets only `target-version` and
`line-length`. It never pins a `select`, so the enabled rule set is whatever
the installed ruff binary happens to default to — and that default changed:
ruff <0.16 enabled ~123 rules, 0.16.0 enables ~831 (`ruff check --show-settings`).

Same tree, same config file, different verdict:

    cd zenith && uv run ruff check .   # ruff 0.15.6 from uv.lock -> All checks passed
    uvx ruff check .                   # ruff 0.16.0             -> Found 62 errors

CI is green today only because `uv.lock` pins ruff 0.15.6 against a `ruff>=0.4`
spec. A single `uv lock --upgrade` — or any contributor with a newer ruff on
`PATH` — pulls 0.16.x and surfaces 62 findings across `src/` and `tests/`,
almost all of it long-standing code that no PR touched. That turns a routine
lock refresh into an unrelated 62-item cleanup, and it makes "does lint pass?"
un-answerable without knowing which ruff someone ran.

## Fix

Make the contract explicit instead of version-dependent:

- `[tool.ruff.lint] select = ["E4", "E7", "E9", "F"]` — ruff's own pre-0.16
  default, written down. No rule changes state, so no existing code is
  affected.
- `required-version = ">=0.15,<0.16"` — a mismatched binary now aborts with a
  clear cause rather than silently linting under a different rule set.

`uv.lock` is deliberately untouched.

## Verification

Same ruff 0.16.0 binary, in isolation:

    ruff check . --isolated --target-version py311 --line-length 100 \
      --select E4,E7,E9,F        -> All checks passed
    ruff check . --isolated --target-version py311 --line-length 100
                                 -> Found 62 errors

With the change in place: `uv run ruff check .` clean, `uv run mypy src` clean
(17 source files), `uv run pytest -q` 294 passed / 7 skipped (pre-existing
real-agent smoke skips).

## Alternative

If you would rather *adopt* the expanded 0.16 rule set than freeze the old one,
that is the opposite change: select the new rules deliberately and fix all 62
findings in one sweep. It is much larger and touches code across the tree, so
it seems worth an issue and a decision first. This PR is the conservative
option — it locks in today's behavior and can be reverted in one line if you
take the other path.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

### `c76b945` — ACP command cascade (branch `upstream/acp-command-cascade`)

Hold until PR #26 or #31 gets maintainer engagement. Title:
`fix(config): custom worker ACP command cascades to same-provider validator/reviewer`

```markdown
## Problem

`HarnessConfig.resolved_validator_acp_command` resolves with a plain or-chain:

    return (
        self.validator_acp_command
        or self.validator_provider.default_worker_acp_command   # always a non-empty string
        or self.resolved_worker_acp_command                     # unreachable
    )

`default_worker_acp_command` is always truthy for every registered provider,
so the third branch — inheriting the worker's command — is dead code. Set a
custom worker command (`ZENITH_WORKER_ACP_COMMAND="claude-agent-acp --model
..."`, a wrapper script, a test mock) with no per-role override, and
validators silently run the stock adapter instead.
`resolved_terminal_reviewer_acp_command` repeats the pattern one level up.
The failure is silent: provider and reasoning-effort cascades resolve
correctly, only the command diverges.

The codebase already contains the correct logic:
`ProviderSelection.resolved_validation_worker_acp_command` (providers.py)
compares provider names — same provider inherits the custom command; a
provider *switch* falls back to that provider's default. But `config.py` is
what `for_role()` consults at dispatch time, so the write side
(`selection.env()`) and the read side (`HarnessConfig.discover()`) of the
same configuration disagree.

## Fix

Make the two `config.py` properties match the `providers.py` cascade:

- explicit `ZENITH_VALIDATOR_ACP_COMMAND` /
  `ZENITH_TERMINAL_REVIEWER_ACP_COMMAND` still win unconditionally;
- same provider as the cascade parent → inherit the parent's resolved
  command;
- different provider → that provider's default command.

No behavior change for setups that set per-role commands explicitly, or that
use provider defaults throughout.

## Tests

- Regression: custom worker command + same-provider validator/reviewer →
  inherited, including through `for_role()` (fails before the fix).
- Provider switch → provider default (pins unchanged behavior).
- Explicit per-role override beats inheritance (fails before the fix).
- Consistency: `ProviderSelection` round-tripped through `env()` must
  resolve identically in `HarnessConfig` (fails before the fix).

`uv run pytest`: 216 passed, 7 skipped (pre-existing real-agent smoke
skips) on top of `main`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```
