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
- Sync upstream with `git sync-upstream` (alias, `--test` to run the checks
  after): it fetches `origin`, refuses unless the working tree is clean and
  HEAD is `local/integration`, and merges `origin/main` in. It never moves a
  branch ref. It replaced `rebuild-integration` on 2026-08-20, which rebuilt
  `local/integration` from `main` + a hardcoded topic-branch list — a model
  that stopped matching reality once commits landed on the branch directly,
  and whose `git branch -f local/integration main` would have discarded every
  commit on the branch (45 at the time) before failing on the deleted
  `stephan/reasoning-effort-cli` its list still named.

### Carried upstream PRs — keep no snapshot branches

Once an upstream PR is cherry-picked onto `local/integration`, the carried
commit is the only copy that matters. **Do not keep a local branch holding
the PR as fetched** — it duplicates a ref that upstream serves on demand,
goes stale silently, and reads like unmerged work. Deleted 2026-07-29:
`pr-14-gate-checkpoints`, `pr-25-wave-lock`, `pr-17`.

Refetch any PR head instead — this always reproduces the exact commit the
cherry-pick came from:

```bash
git fetch origin pull/14/head:pr-14   # PR number → throwaway local branch
```

Currently carried: **#14 → `3ddf1a6`** (declined upstream — a permanent
fork delta, not a pending cherry-pick), **#25 → `6017363`** (still open
upstream), **#35 → `3646100` + `5121352`** (still open upstream; carried
from head `f704a8d`), **#36 → `6873b77`** (still open upstream; carried
from head `70993ec`, fixed up in `0cc7936`), and **#23 → `9ff873d` +
`ff10c54`** (still open upstream; carried from head `3404285`, guarded by
`2cc3b5b`). Patch-ids differ from the PR heads (rebased onto the fork
line); authorship is preserved, so `git log --format='%an'` still shows the
upstream author — including where upstream itself recorded a placeholder
(#23's first commit is authored `Temporary User <temp@example.com>`
upstream; it is carried as found rather than reassigned).

**When a carried PR gets new commits.** Refetch the head, diff it against
what was carried, and take only the delta:

```bash
git fetch origin pull/25/head:pr-25
git log --oneline 4e78f75..pr-25          # 4e78f75 = head at cherry-pick time
git cherry-pick -x <new commits>          # onto a topic branch off local/integration
```

Never re-cherry-pick the whole PR over the carried commit. Record the new
head SHA in the delta row so the next diff has a base. Delete the throwaway
branch afterwards.

**When a carried PR is merged upstream.** The "prefer upstream's variant"
rule applies: drop the fork's copy rather than keep both. On the next sync,
merge `origin/main` into `local/integration` and expect the carried commit
to fall out as already-applied. Where it conflicts, take upstream's side
unless the fork deliberately diverged — if it did, that divergence is now
its own delta row, not a leftover of the cherry-pick. Then update the row
from "Cherry-pick of upstream PR #N" to "merged upstream, local copy
dropped". Precedent: PR #17 (per-role reasoning effort) merged as `a21c071`
and is in `local/integration`; its staging branch was deleted, not kept.

**When a carried PR is declined upstream.** A decline is not a merge and not
a defect report — the "prefer upstream's variant" rule has nothing to prefer,
and the commit will never fall out of a sync. Re-read the maintainer's stated
reason before deciding: a deferral on *upstream's* design roadmap ("we may
remove this") does not transfer to this fork, which runs the code today and
may already depend on it. Keep the commit, move its row from "Cherry-pick of
upstream PR #N" to a permanent fork-only delta, and record in the row *why* it
is load-bearing here — a future sync will otherwise re-open the question with
the reasoning lost. If the decline hints that upstream may delete something
this fork builds on, note it as a tripwire-2 watch item rather than acting on
it. Precedent: PR #14 (`3ddf1a6`), declined 2026-07-03.

Same for a PR **this fork filed**: on merge, delete the branch it was filed
from — locally *and* on `fork` — since upstream now serves the content.
Deleted 2026-08-19 after PR #34 merged: `upstream/toml-env-escaping` (both
copies), plus `stephan/reasoning-effort-cli`, a leftover staging branch for
work that had already landed via PR #17.

Check state with `gh pr view <n> --repo Intelligent-Internet/zenith`, not
with a local branch's position.

### 🚫 Never run `ruff format` on this repo

Lint only — `cd zenith && uv run ruff check .`. **Do not run
`ruff format`**, and do not enable format-on-save for this checkout.

This codebase has never been ruff-formatted: `ruff format --check` reports
**42 of 45 files** would be reformatted, and that is equally true at the fork
base (verify with `git show feb1d62:<file> | ruff format --check -`). Neither
CI (`.github/workflows/ci.yml`) nor CONTRIBUTING.md invokes the formatter —
only `ruff check`, `mypy src`, `pytest`. Formatting would rewrite nearly the
whole tree, bury every real change in unrelated churn, and guarantee conflicts
on the next upstream cherry-pick — for zero gain on a check nobody runs.

⚠️ This **overrides the general "always run `ruff format`" convention** in
`~/.config/agents/extras/rules/python-guidelines.md`. Formatting is not part
of this project's contract; match the surrounding style by hand instead.

Related: `ruff check` is version-pinned (`6c3fbb8`) — always invoke it as
`uv run ruff check` so it resolves the locked 0.15.6, never `uvx ruff`.

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
| `2cc3b5b` | `zenith init --scope user` refuses the model, reasoning-effort, and `--log-level`/`--log-file` flags instead of accepting them and writing nothing | fork-only, and **only half a fork concern**: user scope assembles no `cli_env`, so upstream's own model and effort flags are dropped just as silently there. Offer upstream if #23 gets engagement — the fork-specific part is just the two log flags. Sits after #23's own argument checks so its `test_user_scope_argument_errors_happen_before_writes` ordering still holds |
| `ff10c54` | Cherry-pick of upstream [PR #23](https://github.com/Intelligent-Internet/zenith/pull/23), commit 2 (validate Codex managed-block boundaries) | open upstream since 2026-07-20; carried from head `3404285`. Applied clean |
| `9ff873d` | Cherry-pick of upstream [PR #23](https://github.com/Intelligent-Internet/zenith/pull/23), commit 1 (`zenith init --scope user`: user-scoped MCP registration in `~/.claude.json` / `$CODEX_HOME/config.toml`, host agents/playbooks/prompt, personal `/zenith` skill) | open upstream since 2026-07-20; carried from head `3404285`. Based on `feb1d62`, i.e. before #17 and #34 — one conflict in `init`, resolved by keeping this fork's model-pin `shadowed`/`discover()` block from `3646100` and dropping its leading `workspace = Path(workspace_dir)` line, which #23 moves past the `--scope user` early return and re-defaults from `"."` to `None`. Authored upstream as `Temporary User <temp@example.com>` — that is the identity in `b2bc962`, preserved as found. User scope writes no `_forwarded_runtime_env()` and no `cli_env`; see `2cc3b5b` |
| `0cc7936` | Bounded-dispatch fix-ups: reconcile writes the durable markdown mirror (`save_attempt`) instead of only reading the worker's JSON, and an abandoned dispatch thread re-stamps the `.dispatched` markers it owns while it runs | fork-only, but **both are defects in PR #36 as filed, not fork interactions** — verified against `origin/main`, where `_evaluate_gate` cites `attempt_report_path` just the same (so gate reports named an unwritten file for every task that outlived its dispatch wait), and where `attempt_stale_s` measures elapsed time rather than liveness (a worker slower than 6h — the case bounded dispatch exists for — read as lost). Offer upstream if #36 ever gets engagement. The test-fixture half *is* a fork interaction: #36's tasks named `skill="s"`, which the carried #14 validation rejects at `submit_plan` |
| `6873b77` | Cherry-pick of upstream [PR #36](https://github.com/Intelligent-Internet/zenith/pull/36) (bounded dispatch wait: `StepResult.in_progress`, `.dispatched` markers, `ZENITH_DISPATCH_WAIT_S`/`ZENITH_ATTEMPT_STALE_S`) | open upstream since 2026-08-12; carried from head `70993ec`. Fixed up in `0cc7936` — do not carry it without those. Reviewed against the carried #25 (`6017363`): safe, because the timeout path discards only the dispatch *return value*, so an abandoned thread touches nothing but its own attempt JSON and never `task-state.json`; the next wave sees a fresh marker and skips the task as in-flight rather than stubbing an in-flight validator, which was #25's failure mode. Our `81aeffd` heartbeat is now belt-and-braces for `advance_project` but still load-bearing for `end_mission`, which still blocks on terminal review |
| `5121352` | Cherry-pick of upstream [PR #35](https://github.com/Intelligent-Internet/zenith/pull/35), commit 2 (per-role model pin: `ZENITH_{WORKER,VALIDATOR,TERMINAL_REVIEWER}_MODEL` + `--*-model` flags) | open upstream since 2026-08-09; carried from head `f704a8d`. **Adapted for #31**, which the PR body anticipated: the codex pin is set as an explicit layer-3 `CODEX_CONFIG` key (with `sandbox_mode`/`approval_policy`/`model_reasoning_effort`) instead of riding argv, which the npm codex-acp adapter ignores. Layer 3 rather than layer 2 so the resolved role value outranks an ambient `CODEX_CONFIG` model and one spliced into `ZENITH_*_ACP_COMMAND`, independent of `-c` ordering in the command string. Five fork tests cover that channel; the PR's own tests only reached argv |
| `3646100` | Cherry-pick of upstream [PR #35](https://github.com/Intelligent-Internet/zenith/pull/35), commit 1 (init resolves every role — flag, then ambient var, then cascade — and writes what it resolved; assets installed for env-resolved roles; foreign-binary warning; `discover()` `ValueError` as a usage error) | open upstream since 2026-08-09; carried from head `f704a8d`. The write-side half this fork already had via #26 + `1bc4cb7` covers **flags**; this covers the **ambient environment**, which `env()` cannot see. `_write_bootstrap_config` layers `cli_env` over `ProviderSelection.env()`, so the resolved values supersede env()'s output for the same keys — the two agree by construction on any flag-set lane |
| `1bc4cb7` | Explicit per-role ACP commands/providers always reach the generated config, instead of being deduped against the cascade parent | not filed (depends on PR #26 — `origin/main`'s `env()` has no `ZENITH_TERMINAL_REVIEWER_*` keys to fix). Carrying #35 (`3646100`) made init write *every* resolved role provider, so the "unset flags emit no terminal-reviewer keys" test filed with #26 became false here: it is now `test_claude_init_writes_inherited_terminal_reviewer_provider`, asserting the resolved provider is written while an inherited ACP command is still omitted. A deliberate divergence from #26 as filed — restore it only if upstream rejects #35's always-write direction |
| `643d675` | `zenith init --log-level/--log-file` flags persist the log env vars into the generated server config | not filed; belongs with the observability commits (`6d618ca`/`6f3cc39`) if those are ever filed. Reshaped while carrying #35: the log vars moved out of the renamed effort dict into their own `log_env`, leaving upstream's `effort_env` and its `cli_env = {**effort_env, **model_env, **role_env}` line intact. The delta at that spot is now one added dict plus `**log_env` — keep it that way, so the next sync of `init` does not conflict over a name this fork chose |
| `6c3fbb8` | Pin the ruff rule set (`lint.select` + `required-version`) so `ruff check` stops meaning something different per ruff release | fork-only for now; `upstream/ruff-rule-pin` on fork is ready to file (PR body below), held until #26/#31 get engagement |
| `64f24fa` | Escape env values in the codex `config.toml` writer (quoted ACP commands emitted invalid TOML) | **merged upstream** as `2c26f6a` ([PR #34](https://github.com/Intelligent-Internet/zenith/pull/34), 2026-08-07); `cli.py` fell out as already-applied on the sync merge. The test stays forked: upstream's variant drops the reviewer command (needs #26) and documents an `env()` suppression this fork removed in `1bc4cb7` |
| `c76b945` | Custom worker ACP command cascades to same-provider validator/reviewer | on hold until #26/#31 get engagement; `upstream/acp-command-cascade` on fork is ready to file (PR body below) |
| `02aaf73` | Scoped `CODEX_HOME` for the codex terminal reviewer | not filed (depends on PR #31) |
| `2fa9a62` | Terminal reviewer: `_meta` settingSources/skills isolation (claude) | [PR #33](https://github.com/Intelligent-Internet/zenith/pull/33), filed 2026-07-27 |
| `32907a2` | Wave transition events also written to the log | not filed (depends on progress notifications) |
| `3e3a4d2` | `follow_up` patch op — ownership transfer from cleared work tasks | fork-only (schema change) |
| `a7c462f` | Findings channel: worker/validator prompt guidance + `file_finding` tool | fork-only (tool-surface change) |
| `426495b` | `Task.revalidates` — explicit gate revalidation + supersede coverage guard | fork-only (schema change) |
| `81aeffd` | Progress notifications + heartbeat during blocking waves | not filed (depends on PR #25) |
| `ea38d25` | Orchestrator prompt: digests are hypotheses, not evidence | [PR #32](https://github.com/Intelligent-Internet/zenith/pull/32), filed 2026-07-27 |
| `3ddf1a6` | Cherry-pick of upstream [PR #14](https://github.com/Intelligent-Internet/zenith/pull/14) (gate checkpoints + skill validation) | **declined upstream** 2026-07-03 — design deferral on the gate-checkpoint node ("we might consider removing this type of node"), with no line-level review and no code objection; PR left open at head `5aca97c`. **Kept fork-only, permanently** — see the declined-PR rule above. The gate half closes a gap in upstream's *own* prompt (it names "checkpoint gate reports" as a distinct shape and forbids relying on stripped runtime fields, but `_gate_report` headed both cases `Gate report from`); the skill half is the only guard against unknown skill names, since `load_skill` is never called on the dispatch path |
| `6017363` | Cherry-pick of upstream [PR #25](https://github.com/Intelligent-Internet/zenith/pull/25) (wave lock held in worker thread) | open upstream since 2026-07-11; carried from head `4e78f75` (last upstream activity 2026-07-11) |
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

Branch is cut from `origin/main` @ `a21c071` (not `feb1d62` like the older held
branches) and carries only the `pyproject.toml` change; numbers below are
measured on that base — 56 findings, not the 62 seen on `local/integration`,
the difference being this fork's own 6. Hold until PR #26 or #31 gets maintainer
engagement. This one is a shared-config change that buys upstream more than it
buys this fork — the fork controls its own lock refreshes — so it is the least
urgent of the held set. Title:
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
