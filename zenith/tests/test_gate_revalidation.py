"""Gate revalidation tests (`Task.revalidates`).

Pins the closure-path fix: a remediated mission must be able to seal
without `continue` on a failed gate, while the superseded dissent stays
visible in the gate record and live dissent still blocks. Also pins the
gate-supersede coverage guard that closes the dissent-laundering loophole.
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
from zenith_harness.task_validation import check_revalidates


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


def _seed_project(controller: ProjectController, workspace: Path) -> str:
    controller.start_project("Brief.", str(workspace))
    pid = controller.store.list_projects()[0].id
    contract_dir = controller.store.ensure_contract_dir(pid, "mission-001")
    (contract_dir / "VAL-001.md").write_text("# VAL-001\n\nStatement body.\n")
    return pid


def _initial_tl() -> TaskList:
    return TaskList(
        tasks=[
            _task("w1", "work", ["VAL-001"]),
            _task("v1", "validate", ["VAL-001"], depends_on=["w1"]),
            _task("g1", "gate", ["VAL-001"], depends_on=["v1"]),
        ]
    )


def _remediation_patch() -> TaskListPatch:
    """The canonical post-dissent remediation: targetless fix task, a
    revalidating lane over the corrected artifact, and a superseding gate
    that keeps the dissenting lane upstream."""
    return TaskListPatch(
        add=[
            _task("w-fix", "work", [], depends_on=[]),
            _task(
                "v2",
                "validate",
                ["VAL-001"],
                depends_on=["w-fix"],
                revalidates=["v1"],
            ),
            _task("g2", "gate", ["VAL-001"], depends_on=["v1", "v2"]),
        ],
        supersede={"g1": "g2"},
    )


class _VerdictBook:
    """Responder whose validator verdicts are keyed by node id."""

    def __init__(self, verdicts: dict[str, bool]):
        self.verdicts = verdicts

    def __call__(self, req: DispatchRequest) -> NodeHandoff:
        if req.task.type == "work":
            return WorkHandoff(node_id=req.task.id, done=True, report="ok")
        passed = self.verdicts[req.task.id]
        return ValidateHandoff(
            node_id=req.task.id,
            done=True,
            report="audited",
            items=[ValidationItem(item_id="VAL-001", passed=passed)],
            passed=passed,
        )


class TestRemediatedMissionSeals:
    def test_revalidated_dissent_clears_gate_without_continue_on_failure(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        controller = ProjectController(
            config,
            MockDispatcher(_VerdictBook({"v1": False, "v2": True})),
            MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
        )
        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, _initial_tl())

        env = controller.advance_project(pid)
        assert env.state.state == "attention_needed"
        items = controller.store.load_attention(pid)
        assert items and items[0].kind == "gate_failed"
        assert "dissent: v1" in items[0].report

        # remediation lands via patch — never `continue` on the failed gate
        env = controller.decide_attention(
            pid,
            [
                Decision(
                    item_id=items[0].id,
                    action="patch",
                    patch=_remediation_patch(),
                    justification="defect fixed; v2 re-audits and supersedes v1",
                )
            ],
        )
        assert env.state.state == "mission_running"

        env = controller.advance_project(pid)
        assert env.state.state == "attention_needed"
        items = controller.store.load_attention(pid)
        assert items and items[0].kind == "gate_checkpoint"
        report = items[0].report
        # the gate record still shows the original failure, marked superseded
        assert "superseded verdicts (historical, not blocking):" in report
        assert "- v1: VAL-001=failed (superseded by revalidation)" in report
        assert "superseded: VAL-001" in report
        # and the passing verdict is live
        assert "cleared: True" in report

        env = controller.decide_attention(
            pid, [Decision(item_id=items[0].id, action="continue")]
        )
        env = controller.advance_project(pid)
        env = controller.end_mission(pid)
        assert env.state.state == "done"

    def test_live_dissent_from_revalidating_lane_still_fails(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        controller = ProjectController(
            config,
            MockDispatcher(_VerdictBook({"v1": False, "v2": False})),
            MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
        )
        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, _initial_tl())

        controller.advance_project(pid)
        items = controller.store.load_attention(pid)
        controller.decide_attention(
            pid,
            [
                Decision(
                    item_id=items[0].id,
                    action="patch",
                    patch=_remediation_patch(),
                )
            ],
        )
        controller.advance_project(pid)
        items = controller.store.load_attention(pid)
        assert items and items[0].kind == "gate_failed"
        # v2's dissent is live; v1's is superseded and must not be cited
        assert "dissent: v2" in items[0].report
        assert "dissent: v1" not in items[0].report

    def test_parallel_lane_without_revalidates_still_blocks(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        """Latest-wins must never be inferred: a second passing lane that
        does not declare `revalidates` leaves the first dissent live."""
        controller = ProjectController(
            config,
            MockDispatcher(_VerdictBook({"v1": False, "v2": True})),
            MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
        )
        pid = _seed_project(controller, workspace)
        tl = TaskList(
            tasks=[
                _task("w1", "work", ["VAL-001"]),
                _task("v1", "validate", ["VAL-001"], depends_on=["w1"]),
                _task("v2", "validate", ["VAL-001"], depends_on=["w1"]),
                _task("g1", "gate", ["VAL-001"], depends_on=["v1", "v2"]),
            ]
        )
        controller.submit_plan(pid, tl)
        controller.advance_project(pid)
        items = controller.store.load_attention(pid)
        assert items and items[0].kind == "gate_failed"
        assert "dissent: v1" in items[0].report


class TestCheckRevalidates:
    def _tl(self, *tasks: Task) -> TaskList:
        return TaskList(tasks=list(tasks))

    def test_clean_declaration_passes(self) -> None:
        tl = self._tl(
            _task("v1", "validate", ["VAL-001"]),
            _task("v2", "validate", ["VAL-001"], revalidates=["v1"]),
        )
        assert check_revalidates(tl) == []

    def test_on_non_validate_rejected(self) -> None:
        tl = self._tl(
            _task("v1", "validate", ["VAL-001"]),
            _task("w1", "work", ["VAL-001"], revalidates=["v1"]),
        )
        assert [e.code for e in check_revalidates(tl)] == [
            "revalidates_on_non_validate"
        ]

    def test_self_reference_rejected(self) -> None:
        tl = self._tl(
            _task("v1", "validate", ["VAL-001"], revalidates=["v1"]),
        )
        assert [e.code for e in check_revalidates(tl)] == ["revalidates_self"]

    def test_unknown_task_rejected(self) -> None:
        tl = self._tl(
            _task("v2", "validate", ["VAL-001"], revalidates=["ghost"]),
        )
        assert [e.code for e in check_revalidates(tl)] == [
            "revalidates_unknown_task"
        ]

    def test_non_validate_target_rejected(self) -> None:
        tl = self._tl(
            _task("w1", "work", ["VAL-001"]),
            _task("v2", "validate", ["VAL-001"], revalidates=["w1"]),
        )
        assert [e.code for e in check_revalidates(tl)] == [
            "revalidates_non_validate_task"
        ]

    def test_disjoint_targets_rejected(self) -> None:
        tl = self._tl(
            _task("v1", "validate", ["VAL-002"]),
            _task("v2", "validate", ["VAL-001"], revalidates=["v1"]),
        )
        assert [e.code for e in check_revalidates(tl)] == [
            "revalidates_without_shared_target"
        ]


class TestGateSupersedeCoverageGuard:
    def _base(self) -> tuple[TaskList, TaskStateFile]:
        tl = TaskList(
            tasks=[
                _task("w1", "work", ["VAL-001"]),
                _task("v1", "validate", ["VAL-001"], depends_on=["w1"]),
                _task("g1", "gate", ["VAL-001"], depends_on=["v1"]),
            ]
        )
        state = TaskStateFile()
        state.set_status("w1", "cleared")
        state.set_status("v1", "cleared")
        state.set_status("g1", "failed")
        return tl, state

    def test_supersede_gate_dropping_targets_rejected(self) -> None:
        tl, state = self._base()
        patch = TaskListPatch(
            add=[_task("g2", "gate", ["VAL-002"], depends_on=["v1"])],
            supersede={"g1": "g2"},
        )
        _, _, _, errors = apply_patch(
            tl, state, {"VAL-001", "VAL-002"}, patch
        )
        assert "gate_supersede_drops_targets" in [e.code for e in errors]

    def test_supersede_gate_with_non_gate_rejected(self) -> None:
        tl, state = self._base()
        patch = TaskListPatch(
            add=[_task("v9", "validate", ["VAL-001"], depends_on=["w1"])],
            supersede={"g1": "v9"},
        )
        _, _, _, errors = apply_patch(tl, state, {"VAL-001"}, patch)
        assert "gate_superseded_by_non_gate" in [e.code for e in errors]

    def test_supersede_gate_keeping_targets_allowed(self) -> None:
        tl, state = self._base()
        patch = TaskListPatch(
            add=[_task("g2", "gate", ["VAL-001"], depends_on=["v1"])],
            supersede={"g1": "g2"},
        )
        _, _, _, errors = apply_patch(tl, state, {"VAL-001"}, patch)
        assert errors == []


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
