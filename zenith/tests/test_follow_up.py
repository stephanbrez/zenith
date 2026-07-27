"""`follow_up` patch-op tests.

Pins the legal ownership-transfer path from a cleared work task: history
stays byte-identical, coverage accepts the new owner without a
duplicate-owner error, and the guards mirror supersede's.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from zenith_harness.config import HarnessConfig
from zenith_harness.controller import ProjectController
from zenith_harness.dispatcher import (
    DispatchRequest,
    MockDispatcher,
    MockTerminalReviewer,
    NodeHandoff,
)
from zenith_harness.models import (
    Decision,
    Task,
    TaskList,
    TaskListPatch,
    TaskStateFile,
    TerminalReviewHandoff,
    ValidateHandoff,
    ValidationItem,
    WorkHandoff,
)
from zenith_harness.task_list_patch import apply_patch


@pytest.fixture
def config(harness_home: Path) -> HarnessConfig:
    bundled = Path(__file__).resolve().parents[1] / "src" / "zenith_harness" / "bundled"
    return HarnessConfig(
        bundled_dir=bundled,
        harness_home=harness_home,
        projects_dir=harness_home / "projects",
        orchestrator_provider_name="claude",
        worker_provider_name="claude",
        worker_acp_command=None,
        validator_provider_name=None,
        validator_acp_command=None,
        terminal_reviewer_provider_name=None,
        terminal_reviewer_acp_command=None,
        max_parallel_nodes=1,
    )


def _task(
    tid: str,
    ttype: str,
    targets: list[str],
    depends_on: list[str] | None = None,
    revalidates: list[str] | None = None,
) -> Task:
    skill = None
    if ttype != "gate":
        skill = (
            "scrutiny-validator"
            if ttype == "validate"
            else "engineering-mission-playbook"
        )
    return Task(
        id=tid,
        type=ttype,  # type: ignore[arg-type]
        body="" if ttype == "gate" else "body",
        targets=targets,
        skill=skill,
        depends_on=depends_on or [],
        revalidates=revalidates or [],
    )


def _base_tl() -> TaskList:
    return TaskList(
        tasks=[
            _task("w1", "work", ["VAL-001"]),
            _task("v1", "validate", ["VAL-001"], depends_on=["w1"]),
            _task("g1", "gate", ["VAL-001"], depends_on=["v1"]),
        ]
    )


def _cleared_state(gate_status: str = "failed") -> TaskStateFile:
    state = TaskStateFile()
    state.set_status("w1", "cleared")
    state.set_status("v1", "cleared")
    state.set_status("g1", gate_status)
    return state


def _follow_up_patch() -> TaskListPatch:
    return TaskListPatch(
        add=[_task("w2", "work", ["VAL-001"])],
        follow_up={"w1": "w2"},
    )


class TestApplyFollowUp:
    def test_transfers_ownership_without_touching_history(self) -> None:
        tl, state = _base_tl(), _cleared_state()
        patched_tl, patched_state, _, errors = apply_patch(
            tl, state, {"VAL-001"}, _follow_up_patch()
        )
        assert errors == []
        # cleared task untouched: same status, provenance recorded out-of-band
        assert patched_state.status_of("w1") == "cleared"
        assert patched_state.followed_up_by_of("w1") == "w2"
        assert patched_state.status_of("w2") == "pending"
        # the old task object itself is byte-identical
        old = next(t for t in patched_tl.tasks if t.id == "w1")
        assert old == next(t for t in tl.tasks if t.id == "w1")
        # depends_on is NOT rewritten — v1 still depends on w1
        v1 = next(t for t in patched_tl.tasks if t.id == "v1")
        assert v1.depends_on == ["w1"]

    def test_coverage_accepts_single_new_owner(self) -> None:
        """Without follow_up this exact patch trips over_covered_assertion."""
        tl, state = _base_tl(), _cleared_state()
        bare_add = TaskListPatch(add=[_task("w2", "work", ["VAL-001"])])
        _, _, _, errors = apply_patch(tl, state, {"VAL-001"}, bare_add)
        assert "over_covered_assertion" in [e.code for e in errors]

        _, _, _, errors = apply_patch(tl, state, {"VAL-001"}, _follow_up_patch())
        assert errors == []

    def test_partial_transfer_keeps_untouched_targets_owned(self) -> None:
        tl = TaskList(
            tasks=[
                _task("w1", "work", ["VAL-001", "VAL-002"]),
                _task("v1", "validate", ["VAL-001", "VAL-002"], depends_on=["w1"]),
            ]
        )
        state = TaskStateFile()
        state.set_status("w1", "cleared")
        state.set_status("v1", "cleared")
        patch = TaskListPatch(
            add=[_task("w2", "work", ["VAL-001"])],
            follow_up={"w1": "w2"},
        )
        _, patched_state, _, errors = apply_patch(
            tl, state, {"VAL-001", "VAL-002"}, patch
        )
        # VAL-001 moved to w2; VAL-002 still owned by w1 — no uncovered error
        assert errors == []
        assert patched_state.followed_up_by_of("w1") == "w2"


class TestFollowUpGuards:
    def test_requires_cleared(self) -> None:
        tl = _base_tl()
        state = TaskStateFile()
        state.set_status("w1", "pending")
        _, _, _, errors = apply_patch(tl, state, {"VAL-001"}, _follow_up_patch())
        assert "follow_up_requires_cleared" in [e.code for e in errors]

    def test_rejects_running(self) -> None:
        tl = _base_tl()
        state = TaskStateFile()
        state.set_status("w1", "running")
        _, _, _, errors = apply_patch(tl, state, {"VAL-001"}, _follow_up_patch())
        assert "follow_up_requires_cleared" in [e.code for e in errors]

    def test_rejects_sealed_subgraph(self) -> None:
        tl, state = _base_tl(), _cleared_state(gate_status="cleared")
        _, _, _, errors = apply_patch(tl, state, {"VAL-001"}, _follow_up_patch())
        assert "follow_up_inside_sealed_subgraph" in [e.code for e in errors]

    def test_rejects_non_work_source(self) -> None:
        tl, state = _base_tl(), _cleared_state()
        patch = TaskListPatch(
            add=[_task("v2", "validate", ["VAL-001"], depends_on=["w1"])],
            follow_up={"v1": "v2"},
        )
        _, _, _, errors = apply_patch(tl, state, {"VAL-001"}, patch)
        assert "follow_up_non_work" in [e.code for e in errors]

    def test_rejects_non_work_target(self) -> None:
        tl, state = _base_tl(), _cleared_state()
        patch = TaskListPatch(
            add=[_task("v9", "validate", ["VAL-001"], depends_on=["w1"])],
            follow_up={"w1": "v9"},
        )
        _, _, _, errors = apply_patch(tl, state, {"VAL-001"}, patch)
        assert "follow_up_target_non_work" in [e.code for e in errors]

    def test_rejects_unknown_ids_and_self(self) -> None:
        tl, state = _base_tl(), _cleared_state()
        patch = TaskListPatch(follow_up={"ghost": "w1"})
        _, _, _, errors = apply_patch(tl, state, {"VAL-001"}, patch)
        assert "unknown_follow_up_target" in [e.code for e in errors]

        patch = TaskListPatch(follow_up={"w1": "ghost"})
        _, _, _, errors = apply_patch(tl, state, {"VAL-001"}, patch)
        assert "follow_up_new_id_unknown" in [e.code for e in errors]

        patch = TaskListPatch(follow_up={"w1": "w1"})
        _, _, _, errors = apply_patch(tl, state, {"VAL-001"}, patch)
        assert "follow_up_self" in [e.code for e in errors]

    def test_rejects_disjoint_targets(self) -> None:
        tl, state = _base_tl(), _cleared_state()
        patch = TaskListPatch(
            add=[_task("w2", "work", [])],
            follow_up={"w1": "w2"},
        )
        _, _, _, errors = apply_patch(tl, state, {"VAL-001"}, patch)
        assert "follow_up_without_shared_target" in [e.code for e in errors]

    def test_rejects_overlap_with_retire_ops(self) -> None:
        tl, state = _base_tl(), _cleared_state()
        patch = TaskListPatch(
            add=[_task("w2", "work", ["VAL-001"])],
            follow_up={"w1": "w2"},
            cancel=["w1"],
        )
        _, _, _, errors = apply_patch(tl, state, {"VAL-001"}, patch)
        assert "follow_up_retire_overlap" in [e.code for e in errors]


class TestFollowUpEndToEnd:
    def test_full_remediation_flow_reaches_done(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        """Gate fails on dissent -> one patch hands ownership to a real,
        acceptance-bearing fix task, adds a revalidating lane, and re-gates.
        The mission seals with no `continue` on a failure and no targetless
        workaround task."""
        verdicts = {"v1": False, "v2": True}

        def responder(req: DispatchRequest) -> NodeHandoff:
            if req.task.type == "work":
                return WorkHandoff(node_id=req.task.id, done=True, report="ok")
            passed = verdicts[req.task.id]
            return ValidateHandoff(
                node_id=req.task.id,
                done=True,
                report="audited",
                items=[ValidationItem(item_id="VAL-001", passed=passed)],
                passed=passed,
            )

        controller = ProjectController(
            config,
            MockDispatcher(responder),
            MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
        )
        controller.start_project("Brief.", str(workspace))
        pid = controller.store.list_projects()[0].id
        contract_dir = controller.store.ensure_contract_dir(pid, "mission-001")
        (contract_dir / "VAL-001.md").write_text("# VAL-001\n\nStatement.\n")
        controller.submit_plan(pid, _base_tl())

        controller.advance_project(pid)
        items = controller.store.load_attention(pid)
        assert items and items[0].kind == "gate_failed"

        attempts_dir = Path(
            controller.store.attempt_report_path(
                pid, "mission-001", "x", "x"
            )
        ).parent.parent
        before = {
            p: p.read_bytes() for p in sorted(attempts_dir.rglob("*.json"))
        }

        patch = TaskListPatch(
            add=[
                _task("w2", "work", ["VAL-001"]),
                _task(
                    "v2",
                    "validate",
                    ["VAL-001"],
                    depends_on=["w2"],
                    revalidates=["v1"],
                ),
                _task("g2", "gate", ["VAL-001"], depends_on=["v1", "v2"]),
            ],
            follow_up={"w1": "w2"},
            supersede={"g1": "g2"},
        )
        env = controller.decide_attention(
            pid,
            [
                Decision(
                    item_id=items[0].id,
                    action="patch",
                    patch=patch,
                    justification="w2 takes over VAL-001; v2 re-audits",
                )
            ],
        )
        assert env.state.state == "mission_running"

        # cleared task's attempts are byte-identical after the patch
        after = {
            p: p.read_bytes() for p in sorted(attempts_dir.rglob("*.json"))
        }
        assert before == after
        assert (
            controller.store.load_task_state(pid, "mission-001").status_of("w1")
            == "cleared"
        )

        controller.advance_project(pid)
        items = controller.store.load_attention(pid)
        assert items and items[0].kind == "gate_checkpoint"
        controller.decide_attention(
            pid, [Decision(item_id=items[0].id, action="continue")]
        )
        controller.advance_project(pid)
        env = controller.end_mission(pid)
        assert env.state.state == "done"

        # provenance survives on disk across reloads
        reloaded = controller.store.load_task_state(pid, "mission-001")
        assert reloaded.followed_up_by_of("w1") == "w2"


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
