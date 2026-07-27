from __future__ import annotations

import secrets

from .models import (
    AttentionItemInternal,
    Task,
    TerminalReviewHandoff,
    ValidateHandoff,
    WorkHandoff,
)


def _new_id(prefix: str) -> str:
    return f"att-{prefix}-{secrets.token_hex(3)}"


def _handoff_report(task: Task, handoff: WorkHandoff | ValidateHandoff) -> str:
    lines = [
        f"Task report from {task.id}",
        f"type: {task.type}",
        f"done: {handoff.done}",
        f"request_attention: {handoff.request_attention}",
        "",
        "report:",
        handoff.report or "(empty)",
    ]
    if isinstance(handoff, ValidateHandoff):
        lines.extend(
            [
                "",
                f"passed: {handoff.passed}",
                "items:",
            ]
        )
        if handoff.items:
            lines.extend(
                f"- {item.item_id}: {'passed' if item.passed else 'failed'}"
                for item in handoff.items
            )
        else:
            lines.append("- (none)")
    return "\n".join(lines)


def node_failed(
    mission_id: str,
    task: Task,
    handoff: WorkHandoff,
) -> AttentionItemInternal:
    return AttentionItemInternal(
        id=_new_id(task.id),
        kind="node_failed",
        mission_id=mission_id,
        node_id=task.id,
        report=_handoff_report(task, handoff),
    )


def node_attention(
    mission_id: str,
    task: Task,
    handoff: WorkHandoff | ValidateHandoff,
) -> AttentionItemInternal:
    return AttentionItemInternal(
        id=_new_id(task.id),
        kind="node_attention",
        mission_id=mission_id,
        node_id=task.id,
        report=_handoff_report(task, handoff),
    )


def _validator_summary_lines(
    targets: list[str],
    validator_verdicts: dict[str, dict[str, bool]],
    missing_items: dict[str, list[str]] | None = None,
    superseded_verdicts: dict[str, dict[str, bool]] | None = None,
) -> list[str]:
    """Human-readable per-validator summary for the gate report."""
    summary: list[str] = []
    target_set = set(targets)
    missing_items = missing_items or {}
    superseded_verdicts = superseded_verdicts or {}
    for vid in sorted(validator_verdicts):
        verdicts = validator_verdicts[vid]
        covered = [t for t in targets if t in verdicts]
        if not covered:
            summary.append(f"- {vid}: 0/{len(target_set)} covered")
            continue
        passed = sum(1 for t in covered if verdicts[t])
        miss_set = set(missing_items.get(vid, []))
        sup_set = set(superseded_verdicts.get(vid, {}))
        flags: list[str] = []
        dissenting = [
            t
            for t in covered
            if not verdicts[t] and t not in miss_set and t not in sup_set
        ]
        missing = [t for t in covered if t in miss_set and t not in sup_set]
        superseded = [t for t in covered if t in sup_set]
        if dissenting:
            flags.append(f"dissenting: {', '.join(dissenting)}")
        if missing:
            flags.append(f"missing: {', '.join(missing)}")
        if superseded:
            flags.append(f"superseded: {', '.join(superseded)}")
        flag_text = f" ({'; '.join(flags)})" if flags else ""
        summary.append(
            f"- {vid}: {passed}/{len(covered)} passed over {len(target_set)} target(s){flag_text}"
        )
    return summary


def _gate_report(
    gate: Task,
    *,
    cleared: bool,
    reason: str = "",
    failed_items: list[str] | None = None,
    validator_verdicts: dict[str, dict[str, bool]] | None = None,
    missing_items: dict[str, list[str]] | None = None,
    superseded_verdicts: dict[str, dict[str, bool]] | None = None,
) -> str:
    failed_items = failed_items or []
    validator_verdicts = validator_verdicts or {}
    missing_items = missing_items or {}
    superseded_verdicts = superseded_verdicts or {}
    title = (
        f"Gate checkpoint from {gate.id}"
        if cleared
        else f"Gate report from {gate.id}"
    )
    lines = [title]
    if cleared:
        lines.append(
            "checkpoint: passing gate already cleared; continue acknowledges "
            "the checkpoint and does not clear a failed task or gate"
        )
    lines.extend(
        [
            f"cleared: {cleared}",
            f"targets: {', '.join(gate.targets) if gate.targets else '(none)'}",
        ]
    )
    if reason:
        lines.append(f"reason: {reason}")
    if failed_items:
        lines.append(f"failed_items: {', '.join(failed_items)}")
    lines.extend(["", "validator summary:"])
    summary = _validator_summary_lines(
        gate.targets, validator_verdicts, missing_items, superseded_verdicts
    )
    lines.extend(summary or ["- (no validator verdicts)"])
    if superseded_verdicts:
        lines.extend(["", "superseded verdicts (historical, not blocking):"])
        for vid in sorted(superseded_verdicts):
            for tgt in sorted(superseded_verdicts[vid]):
                verdict = "passed" if superseded_verdicts[vid][tgt] else "failed"
                lines.append(
                    f"- {vid}: {tgt}={verdict} (superseded by revalidation)"
                )
    return "\n".join(lines)


def gate_failed(
    mission_id: str,
    gate: Task,
    reason: str,
    *,
    failed_items: list[str] | None = None,
    validator_verdicts: dict[str, dict[str, bool]] | None = None,
    missing_items: dict[str, list[str]] | None = None,
    superseded_verdicts: dict[str, dict[str, bool]] | None = None,
) -> AttentionItemInternal:
    failed_items = failed_items or []
    validator_verdicts = validator_verdicts or {}
    missing_items = missing_items or {}
    return AttentionItemInternal(
        id=_new_id(gate.id),
        kind="gate_failed",
        mission_id=mission_id,
        node_id=gate.id,
        report=_gate_report(
            gate,
            cleared=False,
            reason=reason,
            failed_items=failed_items,
            validator_verdicts=validator_verdicts,
            missing_items=missing_items,
            superseded_verdicts=superseded_verdicts,
        ),
    )


def gate_checkpoint(
    mission_id: str,
    gate: Task,
    *,
    validator_verdicts: dict[str, dict[str, bool]] | None = None,
    superseded_verdicts: dict[str, dict[str, bool]] | None = None,
) -> AttentionItemInternal:
    validator_verdicts = validator_verdicts or {}
    return AttentionItemInternal(
        id=_new_id(gate.id),
        kind="gate_checkpoint",
        mission_id=mission_id,
        node_id=gate.id,
        report=_gate_report(
            gate,
            cleared=True,
            validator_verdicts=validator_verdicts,
            superseded_verdicts=superseded_verdicts,
        ),
    )


def orchestrator_finding(
    mission_id: str,
    *,
    evidence: str,
    affects: list[str],
    detail: str,
) -> AttentionItemInternal:
    """Orchestrator-originated discovery, entering the normal attention loop.

    Not a bypass: the item is resolved only through decide_attention with a
    recorded justification, exactly like runtime-raised items.
    """
    lines = [
        "Orchestrator finding",
        f"affects: {', '.join(affects) if affects else '(unspecified)'}",
        f"detail: {detail}",
        "",
        "evidence:",
        evidence,
    ]
    return AttentionItemInternal(
        id=_new_id("finding"),
        kind="orchestrator_finding",
        mission_id=mission_id,
        report="\n".join(lines),
    )


def terminal_review(
    mission_id: str,
    review: TerminalReviewHandoff,
) -> AttentionItemInternal:
    return AttentionItemInternal(
        id=_new_id("terminal-review"),
        kind="terminal_review",
        mission_id=mission_id,
        report=review.report or "(empty)",
    )


__all__ = [
    "node_failed",
    "node_attention",
    "gate_failed",
    "gate_checkpoint",
    "terminal_review",
]
