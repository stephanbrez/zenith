"""Findings-channel tests.

Pins the two halves of the findings channel: a completed task that
requests attention both clears AND opens an attention item, and the
orchestrator's `file_finding` opens an item that is resolvable only
through decide_attention.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from zenith_harness.config import HarnessConfig
from zenith_harness.controller import ProjectController, ToolError
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
    TerminalReviewHandoff,
    ValidateHandoff,
    ValidationItem,
    WorkHandoff,
)


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
    )


def _tl() -> TaskList:
    return TaskList(
        tasks=[
            _task("w1", "work", ["VAL-001"]),
            _task("v1", "validate", ["VAL-001"], depends_on=["w1"]),
            _task("g1", "gate", ["VAL-001"], depends_on=["v1"]),
        ]
    )


def _seed_project(controller: ProjectController, workspace: Path) -> str:
    controller.start_project("Brief.", str(workspace))
    pid = controller.store.list_projects()[0].id
    contract_dir = controller.store.ensure_contract_dir(pid, "mission-001")
    (contract_dir / "VAL-001.md").write_text("# VAL-001\n\nStatement body.\n")
    return pid


def _happy_responder(req: DispatchRequest) -> NodeHandoff:
    if req.task.type == "work":
        return WorkHandoff(node_id=req.task.id, done=True, report="ok")
    return ValidateHandoff(
        node_id=req.task.id,
        done=True,
        report="audited",
        items=[ValidationItem(item_id="VAL-001", passed=True)],
        passed=True,
    )


class TestDoneWithAttentionClearsAndOpens:
    def test_completed_task_with_finding_clears_and_opens_attention(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        def responder(req: DispatchRequest) -> NodeHandoff:
            if req.task.id == "w1":
                return WorkHandoff(
                    node_id="w1",
                    done=True,
                    report="ok\nFinding: harness emits false measurements",
                    request_attention=True,
                )
            return _happy_responder(req)

        controller = ProjectController(
            config,
            MockDispatcher(responder),
            MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
        )
        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, _tl())

        env = controller.advance_project(pid)
        assert env.state.state == "attention_needed"
        # the task cleared — dependents are unblocked
        assert (
            controller.store.load_task_state(pid, "mission-001").status_of("w1")
            == "cleared"
        )
        items = controller.store.load_attention(pid)
        assert items and items[0].kind == "node_attention"
        assert "Finding: harness emits false measurements" in items[0].report


class TestFileFinding:
    def _running_project(
        self, config: HarnessConfig, workspace: Path
    ) -> tuple[ProjectController, str]:
        controller = ProjectController(
            config,
            MockDispatcher(_happy_responder),
            MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
        )
        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, _tl())
        return controller, pid

    def test_opens_attention_item_with_evidence(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        controller, pid = self._running_project(config, workspace)
        env = controller.file_finding(
            pid,
            evidence="/usr/bin/find -newermt rejects the mandated form:\n$ find ...",
            affects=["VAL-001"],
            detail="contract-mandated timestamp form is invalid on this host",
        )
        assert env.state.state == "attention_needed"
        items = controller.store.load_attention(pid)
        assert items and items[0].kind == "orchestrator_finding"
        assert "affects: VAL-001" in items[0].report
        assert "contract-mandated timestamp form" in items[0].report
        assert "/usr/bin/find -newermt" in items[0].report

    def test_resolved_only_through_decide_attention(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        controller, pid = self._running_project(config, workspace)
        controller.file_finding(
            pid, evidence="e", affects=[], detail="d"
        )
        # dispatching is refused while the finding is open
        env = controller.advance_project(pid)
        assert env.state.state == "attention_needed"
        items = controller.store.load_attention(pid)
        env = controller.decide_attention(
            pid,
            [
                Decision(
                    item_id=items[0].id,
                    action="continue",
                    justification="verified non-issue on second look",
                )
            ],
        )
        assert env.state.state == "mission_running"
        assert controller.store.load_attention(pid) == []

    def test_rejected_outside_mission_running(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        controller = ProjectController(
            config,
            MockDispatcher(_happy_responder),
            MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
        )
        controller.start_project("Brief.", str(workspace))
        pid = controller.store.list_projects()[0].id
        with pytest.raises(ToolError) as ei:
            controller.file_finding(pid, evidence="e", affects=[], detail="d")
        assert ei.value.code == "wrong_state"

    def test_empty_evidence_rejected(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        controller, pid = self._running_project(config, workspace)
        with pytest.raises(ToolError) as ei:
            controller.file_finding(pid, evidence="  ", affects=[], detail="d")
        assert ei.value.code == "missing_evidence"
        assert controller.store.load_attention(pid) == []

    def test_empty_detail_rejected(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        controller, pid = self._running_project(config, workspace)
        with pytest.raises(ToolError) as ei:
            controller.file_finding(pid, evidence="e", affects=[], detail="")
        assert ei.value.code == "missing_detail"


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
