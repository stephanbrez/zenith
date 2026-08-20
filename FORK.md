# Fork status

This checkout is an **independent line** descended from
[Intelligent-Internet/zenith](https://github.com/Intelligent-Internet/zenith)
(remote `origin`), published at
[stephanbrez/zenith](https://github.com/stephanbrez/zenith) (remote `fork`).
`local/integration` is the durable branch this fork runs. It is not kept in
sync with upstream and is not expected to merge back.

Decided 2026-08-20, superseding the 2026-07-27 fork-primary-but-syncing
posture. Two things forced it. First, upstream engages with small
self-contained fixes and not with design-level work: PR #34 was reviewed and
merged in about a minute, while #26 (33 days) and #31 (25 days) sit at zero
comments and zero reviews. Second, this fork is now far enough ahead that
carrying upstream work costs more than reimplementing it — `0cc7936` had to
fix two defects in upstream PR #36 *as filed*, and `1bc4cb7` deliberately
diverges from this fork's own PR #26. Planned work (additional ACP providers,
alternative orchestrators) is design-level surface that would deepen both
effects.

## Working rules

- Develop on small topic branches off `local/integration`; test with
  `uv run pytest` in `zenith/`; merge fast-forward; push to `fork`.
- Never shape code for upstream mergeability. There is no reconciliation
  obligation and no pending-cherry-pick state.
- Prefer putting new subsystems in **new modules**, so upstream review stays
  legible against the four files that carry most of the delta (`cli.py`,
  `server.py`, `coordinator.py`, `config.py`). This is a preference, not a
  rule — do not contort a design or refactor working code to honor it.
- Keep the delta table below current: add a row when a change merges to
  `local/integration`. The table is a **provenance and rationale record**, not
  a sync ledger — it explains why the fork is the way it is.

## Reviewing upstream

Fetch upstream, never merge it. Read what changed since the last review and
decide case by case whether to reimplement, adapt, or ignore. Upstream fixes
frequently do not apply here: the code path may already be further along, or
the design may be one this fork rejected.

<!-- WATERMARK: bump this SHA on every review, whether or not anything was taken -->
**Last reviewed upstream: `2c26f6a` (2026-08-07)**

```bash
git fetch origin
git log --oneline 2c26f6a..origin/main      # everything since the watermark
```

Bump the watermark line above after each review even when nothing is taken —
it is the only record of what has already been judged, and without it the
next review has no base.

Open upstream PRs are **not** tracked. They may never merge, may be rewritten
in place, and carrying them was the single most expensive thing in the old
process. Read one deliberately if a linked issue looks relevant
(`gh pr view <n> --repo Intelligent-Internet/zenith`), but adopt it as this
fork's own code, with a delta row, not as a subscription.

When taking an idea from upstream, reimplement it against this tree rather
than cherry-picking a patch shaped for a different one. Where a cherry-pick
genuinely is the cheapest path, preserve authorship (`-x`, no
`--reset-author`) and delete the throwaway branch afterwards.

## Contributing upstream

Contributions still go through a pull request from `fork`: the GitHub API
reports pull-only permission on `origin`, so being listed as a contributor
after PR #34 does not grant push or review rights.

**Cut contribution branches from `origin/main`, never from
`local/integration`.** A contribution is an independent piece of work that
happens to also exist here — not an export of the fork line. This is already
the practice: `upstream/ruff-rule-pin` is cut from `origin/main` @ `a21c071`
and carries one file.

Worth offering upstream: self-contained fixes with a clear defect and a test,
which is the shape upstream demonstrably merges. Not worth offering:
anything depending on unmerged work, anything touching the gate/ownership
schema, and anything whose value here depends on the fork's design direction.

## Attribution and license

Upstream is Apache 2.0 and this fork stays Apache 2.0. Three obligations
survive the split and must not be dropped in a cleanup:

- Keep `LICENSE` and the upstream copyright notice intact.
- Keep authorship on commits originating upstream — `git log --format='%an'`
  must keep showing the upstream author, including where upstream itself
  recorded a placeholder (`9ff873d` is authored `Temporary User
  <temp@example.com>`; it is preserved as found, not reassigned).
- Keep a statement of changes (Apache 2.0 §4b). The delta table below is that
  statement.

### 🚫 Never run `ruff format` on this repo

Lint only — `cd zenith && uv run ruff check .`. **Do not run
`ruff format`**, and do not enable format-on-save for this checkout.

This codebase has never been ruff-formatted: `ruff format --check` reports
**42 of 45 files** would be reformatted, and that is equally true at the fork
base (verify with `git show feb1d62:<file> | ruff format --check -`). Neither
CI (`.github/workflows/ci.yml`) nor CONTRIBUTING.md invokes the formatter —
only `ruff check`, `mypy src`, `pytest`. Formatting would rewrite nearly the
whole tree and bury every real change in unrelated churn, for zero gain on a
check nobody runs.

⚠️ This **overrides the general "always run `ruff format`" convention** in
`~/.config/agents/extras/rules/python-guidelines.md`. Formatting is not part
of this project's contract; match the surrounding style by hand instead.

Related: `ruff check` is version-pinned (`6c3fbb8`) — always invoke it as
`uv run ruff check` so it resolves the locked 0.15.6, never `uvx ruff`.

## Delta vs `origin/main`

Newest first. Every row is fork-owned code. "Origin" records where the idea
came from and why the fork carries it — upstream status is history, not a
pending action.

| Commit | Change | Origin |
| --- | --- | --- |
| `2cc3b5b` | `zenith init --scope user` refuses the model, reasoning-effort, and `--log-level`/`--log-file` flags instead of accepting them and writing nothing | Fork-only. **Only half a fork concern**: user scope assembles no `cli_env`, so upstream's own model and effort flags are dropped just as silently there — a contribution candidate if ever cut against upstream's own user-scope code. Sits after the argument checks from `9ff873d` so its `test_user_scope_argument_errors_happen_before_writes` ordering still holds |
| `ff10c54` | Validate Codex managed-block boundaries | Adopted from upstream PR #23, commit 2; now fork-owned |
| `9ff873d` | `zenith init --scope user`: user-scoped MCP registration in `~/.claude.json` / `$CODEX_HOME/config.toml`, host agents/playbooks/prompt, personal `/zenith` skill | Adopted from upstream PR #23, commit 1 (head `3404285`); now fork-owned. Was based on `feb1d62`, i.e. before #17 and #34 — one conflict in `init`, resolved by keeping this fork's model-pin `shadowed`/`discover()` block from `3646100` and dropping its leading `workspace = Path(workspace_dir)` line, which moves past the `--scope user` early return and re-defaults from `"."` to `None`. Authored upstream as `Temporary User <temp@example.com>`, preserved as found. User scope writes no `_forwarded_runtime_env()` and no `cli_env`; see `2cc3b5b` |
| `0cc7936` | Bounded-dispatch fix-ups: reconcile writes the durable markdown mirror (`save_attempt`) instead of only reading the worker's JSON, and an abandoned dispatch thread re-stamps the `.dispatched` markers it owns while it runs | Fork-only, and **both are defects in upstream PR #36 as filed** — verified against `origin/main`, where `_evaluate_gate` cites `attempt_report_path` just the same (so gate reports named an unwritten file for every task that outlived its dispatch wait), and where `attempt_stale_s` measures elapsed time rather than liveness (a worker slower than 6h — the case bounded dispatch exists for — read as lost). Standing evidence that upstream's version of this path is behind ours. The test-fixture half is a genuine fork interaction: #36's tasks named `skill="s"`, which `3ddf1a6`'s validation rejects at `submit_plan` |
| `6873b77` | Bounded dispatch wait: `StepResult.in_progress`, `.dispatched` markers, `ZENITH_DISPATCH_WAIT_S`/`ZENITH_ATTEMPT_STALE_S` | Adopted from upstream PR #36 (head `70993ec`); now fork-owned. Requires `0cc7936`. Reviewed against `6017363`: safe, because the timeout path discards only the dispatch *return value*, so an abandoned thread touches nothing but its own attempt JSON and never `task-state.json`; the next wave sees a fresh marker and skips the task as in-flight rather than stubbing an in-flight validator. Our `81aeffd` heartbeat is now belt-and-braces for `advance_project` but still load-bearing for `end_mission`, which still blocks on terminal review |
| `5121352` | Per-role model pin: `ZENITH_{WORKER,VALIDATOR,TERMINAL_REVIEWER}_MODEL` + `--*-model` flags | Adopted from upstream PR #35, commit 2 (head `f704a8d`); now fork-owned. **Adapted for `9b80498`**: the codex pin is set as an explicit layer-3 `CODEX_CONFIG` key (with `sandbox_mode`/`approval_policy`/`model_reasoning_effort`) instead of riding argv, which the npm codex-acp adapter ignores. Layer 3 rather than layer 2 so the resolved role value outranks an ambient `CODEX_CONFIG` model and one spliced into `ZENITH_*_ACP_COMMAND`, independent of `-c` ordering. Five fork tests cover that channel; the upstream version's tests only reached argv |
| `3646100` | Init resolves every role — flag, then ambient var, then cascade — and writes what it resolved; assets installed for env-resolved roles; foreign-binary warning; `discover()` `ValueError` as a usage error | Adopted from upstream PR #35, commit 1 (head `f704a8d`); now fork-owned. The write-side half this fork already had via `385d0ac` + `1bc4cb7` covers **flags**; this covers the **ambient environment**, which `env()` cannot see. `_write_bootstrap_config` layers `cli_env` over `ProviderSelection.env()`, so resolved values supersede `env()`'s output for the same keys — the two agree by construction on any flag-set lane |
| `1bc4cb7` | Explicit per-role ACP commands/providers always reach the generated config, instead of being deduped against the cascade parent | Fork-only. A deliberate divergence from this fork's own PR #26 as filed: carrying `3646100` made init write *every* resolved role provider, so #26's "unset flags emit no terminal-reviewer keys" test became false here. It is now `test_claude_init_writes_inherited_terminal_reviewer_provider`, asserting the resolved provider is written while an inherited ACP command is still omitted |
| `643d675` | `zenith init --log-level/--log-file` flags persist the log env vars into the generated server config | Fork-only; belongs with the observability commits (`6d618ca`/`6f3cc39`). Reshaped while adopting `3646100`: the log vars live in their own `log_env` rather than the effort dict, leaving `effort_env` and `cli_env = {**effort_env, **model_env, **role_env}` intact — one added dict plus `**log_env` |
| `6c3fbb8` | Pin the ruff rule set (`lint.select` + `required-version`) so `ruff check` stops meaning something different per ruff release | Fork-only. `upstream/ruff-rule-pin` on `fork` holds a contribution-ready version cut from `origin/main` @ `a21c071`; see the pending body below |
| `64f24fa` | Escape env values in the codex `config.toml` writer (quoted ACP commands emitted invalid TOML) | Filed upstream and **merged** as `2c26f6a` (PR #34, 2026-08-07) — the one demonstrated example of what upstream accepts. The test stays forked: upstream's variant drops the reviewer command and documents an `env()` suppression `1bc4cb7` removed |
| `c76b945` | Custom worker ACP command cascades to same-provider validator/reviewer | Fork-only. `upstream/acp-command-cascade` on `fork` holds a contribution-ready version; see the pending body below |
| `02aaf73` | Scoped `CODEX_HOME` for the codex terminal reviewer | Fork-only (builds on `9b80498`) |
| `2fa9a62` | Terminal reviewer: `_meta` settingSources/skills isolation (claude) | Filed upstream as [PR #33](https://github.com/Intelligent-Internet/zenith/pull/33), 2026-07-27; no review |
| `32907a2` | Wave transition events also written to the log | Fork-only (builds on `81aeffd`) |
| `3e3a4d2` | `follow_up` patch op — ownership transfer from cleared work tasks | Fork-only (schema change) |
| `a7c462f` | Findings channel: worker/validator prompt guidance + `file_finding` tool | Fork-only (tool-surface change) |
| `426495b` | `Task.revalidates` — explicit gate revalidation + supersede coverage guard | Fork-only (schema change) |
| `81aeffd` | Progress notifications + heartbeat during blocking waves | Fork-only (builds on `6017363`) |
| `ea38d25` | Orchestrator prompt: digests are hypotheses, not evidence | Filed upstream as [PR #32](https://github.com/Intelligent-Internet/zenith/pull/32), 2026-07-27; no review |
| `3ddf1a6` | Gate checkpoints + skill validation | Adopted from upstream PR #14, which upstream **declined** 2026-07-03 — a design deferral on the gate-checkpoint node ("we might consider removing this type of node"), with no line-level review and no code objection. **Load-bearing here**: the gate half closes a gap in upstream's *own* prompt (it names "checkpoint gate reports" as a distinct shape and forbids relying on stripped runtime fields, but `_gate_report` headed both cases `Gate report from`); the skill half is the only guard against unknown skill names, since `load_skill` is never called on the dispatch path. If upstream ever removes gate checkpoints, that is upstream's roadmap, not a defect report against this fork |
| `6017363` | Wave lock held in worker thread | Adopted from upstream PR #25 (head `4e78f75`); now fork-owned |
| `6d618ca` | `ZENITH_LOG_FILE` durable log | Fork-only |
| `6f3cc39` | Log ACP spawn command + `CODEX_CONFIG` per dispatch | Fork-only |
| `9b80498` | Route codex `-c` overrides through `CODEX_CONFIG` | Filed upstream as [PR #31](https://github.com/Intelligent-Internet/zenith/pull/31), 2026-07-26; no review. Upstream issue #27 describes the same defect |
| `385d0ac` | Wire `--terminal-reviewer-provider`/`acp-command` through to config | Filed upstream as [PR #26](https://github.com/Intelligent-Internet/zenith/pull/26), 2026-07-18; no review. Superseded here by `1bc4cb7` |

Background for the 2026-07-27 changes (`ea38d25`..`32907a2`): findings from a
real end-to-end mission, analyzed and verified against source in
[`zenith-harness-findings.md`](zenith-harness-findings.md) (repo root;
fork-only documentation).

## Bug-hunting heuristic: configuration-variation boundaries

Every serious bug found so far (2026-07-27) lives where a default and an
override can disagree silently — the benchmark environment was almost
certainly default-config and context-clean, the one machine shape where
none of these are observable:

- ACP command cascade (`c76b945`): only fires with a custom worker command
  *and no per-role overrides*. Invisible if every role is set explicitly,
  or nothing is customized.
- codex-acp `-c` overrides (`9b80498`): only fires on the npm adapter build,
  which ignores argv `-c` — invisible on whatever build the authors ran.
- Terminal-reviewer context injection (`2fa9a62`/`02aaf73`): only *matters*
  when the user has global CLAUDE.md/AGENTS.md content worth leaking. A bare
  CI account has nothing to inject, so the reviewer's independence looks
  intact there.

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

## Pending contribution bodies

⚠️ **Decision open** (raised 2026-08-20, unanswered): file these two or drop
the sections. They were held pending engagement on #26/#31, a condition this
fork no longer waits on. PR #34 shows this exact shape gets merged, so the
cost of filing is low — but neither is load-bearing upstream. Delete this
section once resolved.

### `6c3fbb8` — ruff rule-set pin (branch `upstream/ruff-rule-pin`)

Branch is cut from `origin/main` @ `a21c071` and carries only the
`pyproject.toml` change; numbers below are measured on that base — 56
findings, not the 62 seen on `local/integration`, the difference being this
fork's own 6. Title:
`chore(lint): pin the ruff rule set so CI stops drifting with the ruff release`

```markdown
## Problem

`[tool.ruff]` in `zenith/pyproject.toml` sets only `target-version` and
`line-length`. It never pins a `select`, so the enabled rule set is whatever
the installed ruff binary happens to default to — and that default changed:
ruff <0.16 enabled ~123 rules, 0.16.0 enables ~831 (`ruff check --show-settings`).

Same tree, same config file, different verdict:

    cd zenith && uv run ruff check .   # ruff 0.15.6 from uv.lock -> All checks passed
    uvx ruff check .                   # ruff 0.16.0             -> Found 56 errors

CI is green today only because `uv.lock` pins ruff 0.15.6 against a `ruff>=0.4`
spec. A single `uv lock --upgrade` — or any contributor with a newer ruff on
`PATH` — pulls 0.16.x and surfaces 56 findings across `src/` and `tests/`, all
of it long-standing code that no open PR touched. That turns a routine lock
refresh into an unrelated 56-item cleanup, and it makes "does lint pass?"
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
                                 -> Found 56 errors

With the change in place: `uv run ruff check .` clean, `uv run mypy src` clean
(17 source files), `uv run pytest -q` 212 passed / 7 skipped (pre-existing
real-agent smoke skips).

## Alternative

If you would rather *adopt* the expanded 0.16 rule set than freeze the old one,
that is the opposite change: select the new rules deliberately and fix all 56
findings in one sweep. It is much larger and touches code across the tree, so
it seems worth an issue and a decision first. This PR is the conservative
option — it locks in today's behavior and can be reverted in one line if you
take the other path.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

### `c76b945` — ACP command cascade (branch `upstream/acp-command-cascade`)

Title:
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
