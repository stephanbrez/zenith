# Zenith harness findings — from mission `20260726T194641Z` (urun-cli explainer page)

**Audience:** an agent working on Zenith itself. Zenith lives at
`/Users/stephan/.local/src/zenith/zenith` (package root `src/zenith_harness/`). This file is written
from outside that repo and all line numbers were read on 2026-07-27; re-verify before editing.

**Where these came from.** One real engineering mission was run end to end through Zenith in
orchestrator mode: 63 `VAL-*` contract assertions, 18 tasks, 8 work tasks, 6 validation lanes, 2 gates
(one superseded), 3 attention cycles, ~7 hours wall clock. It completed successfully (`state: done`,
terminal review found no gaps), so none of these are speculative — each one forced a manual
orchestrator workaround that the harness should have handled itself.

Priority order: **#1 and #4 first** (#1 is a correctness bug in the closure path; #4 makes every long
mission look broken), then **#2**, then **#3**.

---

## #1 — A remediated mission cannot seal: gate dissent has no generation concept

**Severity: correctness bug in the closure path.**

### Symptom

After a validator failed some targets, the defects were fixed and a *new* validator lane re-audited
the corrected artifact and passed all of them. The gate still failed, permanently, citing the original
lane's dissent. No patch could clear it.

Observed gate report:

```
reason: failed items: VAL-ACC-001 (dissent: V-SCRUTINY), VAL-ACC-003 (dissent: V-SCRUTINY),
                      VAL-ACC-005 (dissent: V-SCRUTINY)
validator summary:
  V-SCRUTINY:    6/9 passed  (dissenting: VAL-ACC-001, VAL-ACC-003, VAL-ACC-005)
  V-SCRUTINY-2:  3/3 passed  (the same three targets, re-audited after the fix)
```

### Root cause

`src/zenith_harness/coordinator.py`, `_evaluate_gate` (defined at line 475, called at 472):

```python
item_passed[tgt] = all(validator_verdicts[vid][tgt] for vid in covering)
```

`covering` is every validate task transitively upstream of the gate that was authored with that target
(`_upstream_validators`, line 589). Aggregation is pure AND with **no notion of recency, artifact
revision, or supersession**. Once any validator has ever reported `False` for a target, that target can
never pass, because the failing verdict stays in `covering` forever.

`attention.py:92` has the same shape for the flag string:

```python
dissenting = [t for t in covered if not verdicts[t] and t not in miss_set]
```

Note this is *not* fixable by patching: `task_list_patch.py:236` rejects `supersede` on a cleared task
("sealed evidence"), so the failing validator cannot be removed from the graph after it has cleared.
The only exit the design leaves is `decide_attention(action="continue")` on the gate — which is
precisely the action the orchestrator playbook warns against ("do not use `continue` to skip …
unresolved gate dissent"). The orchestrator is forced to choose between an unsealable mission and
violating its own guidance.

### Recommended change

Add an **explicit revalidation declaration**, not inferred supersession.

1. `models.py` — add to `Task` (fields currently at lines 50–88):

   ```python
   revalidates: list[str] = Field(
       default_factory=list,
       description=(
           "Validate tasks only. Task ids whose verdicts this lane supersedes for the "
           "targets both cover. Use when re-validating an artifact after remediation."
       ),
   )
   ```

2. `coordinator.py::_evaluate_gate` — filter `covering` per target before the AND:

   ```python
   superseded = {
       old for vid in covering for old in (by_id[vid].revalidates or [])
       if tgt in by_id[vid].targets
   }
   effective = [vid for vid in covering if vid not in superseded]
   item_passed[tgt] = all(validator_verdicts[vid][tgt] for vid in effective)
   ```

3. `_GateResult` — carry `superseded_verdicts: dict[str, dict[str, bool]]` so the seal record still
   shows the original failure *and* its remediation. Sealing must not erase that a target once failed.

4. Split the failure reason into **live dissent** vs **superseded dissent**. Right now the orchestrator
   cannot tell from the report whether a dissent is current or historical; that distinction is the
   whole decision.

5. `task_validation.py` — validate that `revalidates` only appears on `type == "validate"`, references
   existing task ids, does not name itself, and that the revalidating task shares at least one target
   with each task it supersedes.

### Deliberately rejected alternative

Do **not** infer supersession from timestamps or artifact content hashes. AND-across-independent-
perspectives is the correct default for genuinely parallel lanes (in this mission, `V-VISUAL` and
`V-CONTENT-*` legitimately co-covered nothing, but a future plan may have two lanes audit one target
from different angles, and "latest wins" would silently discard one). Only an explicit declaration
should override AND.

### Acceptance criteria

- A mission where lane A fails target T, remediation lands, and lane B (`revalidates: [A]`) passes T,
  reaches `done` **without** any `continue` on the gate.
- The sealed gate record still contains lane A's failing verdict, marked superseded.
- A gate with a live (non-superseded) dissent still fails.

---

## #2 — Findings that don't block the finder have no channel (the fix is at the reporting layer)

**Severity: latency + wasted task cycles. Do not "fix" this with a plan-amendment tool — see below.**

### Symptom

A worker (`W-GFX`) discovered that the shared evidence harness produced ~85 false measurements per
viewport width, which made a *downstream* assertion (`VAL-GFX-009`) unjudgeable. It reported this
correctly and completely — with `request_attention: false`, because the defect did not block its own
assigned work. It was done, so nothing opened.

The orchestrator therefore knew about a defect invalidating a contract evidence field for roughly two
hours but had no way to act on it, because plan changes require an open attention item. It sat in a
report until a later task (`W-POLISH`) tripped over the same defect and *was* blocked — costing a full
task cycle plus a remediation task plus a re-validation lane.

### Root cause

Attention is keyed to **blockage**, not to **findings**. In the worker/validator result models
(`models.py`, roughly lines 310–350) `done` and `request_attention` are separate booleans, but the
surrounding flow treats attention as the "I am stuck / I failed" path. A task that completes
successfully while discovering something that invalidates *another* task's premise has nowhere to put
it except prose in its handoff, which nothing acts on.

### Recommended change

1. **Decouple `request_attention` from `done` end to end.** A task reporting `done: true` *and*
   `request_attention: true` should clear normally **and** open an attention item the orchestrator must
   decide. Verify the coordinator and dispatcher honour that combination rather than treating attention
   as implying failure — the models already allow it (`models.py:334` has `done: bool = True` alongside
   `request_attention: bool = False`), so this may be flow/handling only.

2. **Give the finding a small structured shape** so it is actionable rather than prose, e.g.
   `finding: {affects: list[str], kind: "evidence_defect" | "contract_defect" | "guidance_defect" |
   "other", detail: str}` where `affects` names contract assertion ids or task ids. The orchestrator
   can then route it without re-reading the whole report.

3. **Add `file_finding(project_id, evidence, affects, detail)` for orchestrator-originated
   discoveries.** In this mission the orchestrator independently verified that `/usr/bin/find` rejects
   the timestamp form its own contract mandated — hard evidence, no channel. This tool must open an
   attention item **on the orchestrator itself**, which it then resolves through `decide_attention`
   with a justification like any other item. It enters the loop; it does not bypass it.

### Explicitly rejected: an `amend_plan` tool

An earlier version of this finding proposed `amend_plan(project_id, patch, justification)` callable in
`mission_running`. **That was wrong and should not be reintroduced.** `decide_attention` is not
plumbing — it is a forcing function with three properties an amendment tool destroys:

- **Every plan change is anchored to evidence.** Patches arrive as responses to a failed task, gate
  report, or validator verdict. Free amendment lets the orchestrator reshape the plan from
  speculation, which is exactly what "patch the earliest invalid artifact" is designed to prevent —
  that instruction presupposes evidence showing *which* artifact is invalid.
- **It preserves the audit chain.** `evidence → decision → patch → revalidation` is readable after the
  fact. Amendments produce plan mutations with no evidentiary parent, and justification degrades from
  a response into self-report.
- **It removes the friction that keeps scope honest.** If tasks can be added and retargeted freely,
  the cheapest escape from an inconvenient assertion stops being "fix the work" and becomes "adjust
  the plan."

The real defect was **latency in surfacing findings**, not inability to change the plan. Fix it at the
reporting layer; the amendment layer costs most of what makes the harness worth running.

### Acceptance criteria

- A task can report `done: true, request_attention: true` and produce both a cleared task and an
  attention item.
- `file_finding` creates an attention item that cannot be resolved except through `decide_attention`.
- No code path allows a task-list mutation without an attention item and a recorded justification.

---

## #3 — Cleared tasks cannot hand off ownership of their assertions

**Severity: ergonomics, but it pushes toward an anti-pattern the playbook forbids.**

### Symptom

Three assertions owned by an already-cleared task needed further work. `task_list_patch.py:236`:

```
Cleared tasks: rejected — sealed evidence.
```

Correct for history, but there is no way to move *ownership*. Expressing "these three assertions need
more work, owned by a new task" required three moving parts: a targetless remediation task
(`W-FIX-CLAIMS`, no targets, so coverage validation stayed satisfied), a separate new validate lane,
and superseding the pending gate to depend on it. One idea, three artifacts, and the targetless task is
not acceptance-bearing so the audit trail is weaker than it looks.

The invariant "exactly one active non-superseded work owner per assertion" needs a legal way to
transfer ownership once tasks start clearing. Without it, the path of least resistance is to pile fixes
onto whichever task is still open — the exact anti-pattern the playbook forbids ("do not create
another fix task when the earliest invalid artifact should be patched").

### Recommended change

Add a fourth `TaskListPatch` op (`models.py:103` defines `TaskListPatch`; `task_list_patch.py:88`
implements `apply_patch`):

```
follow_up: dict[str, str]   # cleared_task_id -> new_task_id
```

Semantics:

- The cleared task and all its attempts stay **immutable** in history — nothing is rewritten.
- Ownership of the intersecting targets transfers to the new task.
- Coverage validation counts the new task as the active owner (so declaring the new task's `targets`
  does not trip the duplicate-owner check).
- The old task records `followed_up_by: <new_id>` for provenance.
- Downstream `depends_on` is **not** rewritten (unlike `supersede`) — the cleared task really did run,
  and its dependents were satisfied by it.

Reject `follow_up` on running tasks and on any task inside a sealed subgraph, mirroring the existing
`supersede` guards.

### Acceptance criteria

- After `follow_up`, the cleared task's attempts are byte-identical and its status still reads cleared.
- Coverage validation passes with the new task owning the transferred targets and no duplicate-owner
  error.
- A gate downstream of the new task evaluates against the new task's verdicts.

---

## #4 — `advance_project` emits nothing and gets killed by client idle timeouts

**Severity: makes every long mission look broken.**

### Symptom

`advance_project` was aborted **ten times** in one mission, each after ~1800–2500s:

```
MCP server "zenith" tool "advance_project" sent no response or progress for 1800s; aborting.
```

The runtime survives every abort — the server is a separate process, so tasks keep running,
completions land, and attempt reports get written. But the orchestrator loses the return value each
time, has to `inspect_project` and re-attach, and cannot distinguish "worker thinking" from "worker
wedged."

That ambiguity caused a real misdiagnosis in this mission: the orchestrator concluded two workers were
severed by the aborts and nearly killed live work. They were simply slow (one task legitimately took
~68 minutes). The misleading signals were near-zero CPU (the worker is blocked on the model API) and no
file writes for 10+ minutes (read-only source auditing writes nothing).

### Root cause

The dispatch loop is silent for its entire duration. Tools are registered in `server.py`
(`advance_project` at line 187); nothing reports progress while stepping.

### Recommended change

1. **Emit a progress/log notification on every state transition** — task dispatched, task cleared, task
   failed, gate evaluated, attention opened. FastMCP supports progress reporting on the tool context;
   this resets any client's idle timer and fixes **every** client rather than one config file. This
   alone closes the issue.

2. **Add a non-blocking mode.** `advance_project(project_id, mode="dispatch")` returns as soon as
   runnable work is dispatched, paired with `wait_for_change(project_id, timeout_s)` for long-polling.
   This suits clients that would rather own the wait loop.

3. **Document the fallback, don't rely on it.** A per-server `"timeout"` in `.mcp.json` works but is
   read at session start, so it cannot rescue a session already in progress;
   `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT=0` disables globally. Put both in the README as mitigations, not
   as the fix.

### Acceptance criteria

- A mission with a 60-minute worker task completes a single `advance_project` call without a client
  idle-timeout abort.
- The orchestrator can distinguish a working task from a wedged one from notifications alone, without
  inspecting process CPU or filesystem mtimes.

---

## #5 — Prompt change: orchestrator-authored research digests are unvalidated

**Not a code change. This is the highest-leverage item in the file per unit of effort.**

### What happened

During planning the orchestrator wrote a 20-section, citation-backed source digest
(`research/urun-cli-facts.md`) from parallel investigation subagents, and workers wrote the deliverable
from it. **Four of its factual claims were wrong**, and three of those propagated onto the delivered
page before the accuracy lane caught them:

| Digest claimed | Source actually said |
|---|---|
| 11 modules import `errors` | 14 |
| scratch installs into a **hardlink copy** of the venv | "recursively copied **(without hardlinks)**", uses `cp -a` |
| the import gate checks **every** module-level import | it has explicit exclusions |
| **Ruff only** is the linter | markdownlint-cli2, actionlint and gitleaks also run |

Every error was an **absolute**: *only, every, never, all*. The pattern is that a digest paraphrasing
investigation summaries sharpens hedged findings into confident claims, and downstream agents treat it
as authoritative because it is citation-shaped.

No validation lane catches this by construction: content lanes judge whether a point is *explained*,
and the accuracy lane audits the *deliverable* against source — not the intermediate digest. Zenith
cannot structurally validate free text, so this belongs in the prompt.

### Recommended prompt change

In the orchestrator prompt's memory/durable-artifact section, add roughly:

> Investigation digests are **hypotheses, not evidence**. When you write a research or facts artifact
> from subagent reports, (a) state each claim with the `file:line` that supports it, (b) never
> introduce an absolute (*only, every, never, all, sole*) that a subagent did not explicitly verify —
> prefer the source's own wording over your paraphrase, and (c) put a standing warning at the head of
> the file instructing readers to verify before use. Workers must be told the digest is a starting map
> and that the source wins on any disagreement; when a worker corrects it, fold the correction in
> immediately and record it.

The mission's own `AGENTS.md` already carried rule (c)-like guidance and workers *did* correct the
digest twice unprompted — that mechanism works. What was missing was (b): a rule against manufacturing
absolutes in the first place.

---

## Note on this file's location

This lives in `/Users/stephan/.local/src/urun-cli-explore` beside the mission's deliverable
`index.html`. It is documentation, not a runtime dependency of that page, so it does not affect the
page's self-containment (the mission's `VAL-PAGE-010` verdict concerned stray *runtime* artifacts such
as screenshots and reports). Zenith work belongs in the Zenith repo; nothing here should be applied to
`urun-cli-explore` or to the read-only `urun-cli` source.
