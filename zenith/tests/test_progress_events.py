"""Progress-event tests.

A silent `advance_project` gets aborted by MCP client idle timeouts even
though the wave is healthy. The coordinator now reports state transitions
through an optional `on_event` observer and the server pumps them (plus a
heartbeat) to the client. These tests pin both halves.
"""
from __future__ import annotations

import asyncio
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
    Task,
    TaskList,
    TerminalReviewHandoff,
    ValidateHandoff,
    ValidationItem,
    WorkHandoff,
)
from zenith_harness.server import _run_with_progress


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


def _tl_with_gate() -> TaskList:
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


def _controller(config: HarnessConfig) -> ProjectController:
    return ProjectController(
        config,
        MockDispatcher(_happy_responder),
        MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
    )


class TestCoordinatorEmitsEvents:
    def test_advance_reports_dispatch_outcome_gate_and_attention(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        controller = _controller(config)
        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, _tl_with_gate())

        events: list[str] = []
        env = controller.advance_project(pid, on_event=events.append)

        assert env.state.state == "attention_needed"
        assert "task w1 (work) dispatched" in events
        assert "task w1 cleared" in events
        assert "task v1 (validate) dispatched" in events
        assert "validator v1 finished: 1/1 items passed" in events
        assert "gate g1 cleared" in events
        assert any(e.startswith("attention opened:") for e in events)
        # dispatch precedes outcome; outcome precedes the gate event
        assert events.index("task w1 (work) dispatched") < events.index(
            "task w1 cleared"
        )
        assert events.index("task w1 cleared") < events.index("gate g1 cleared")

    def test_gate_failed_and_task_failed_events(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        def responder(req: DispatchRequest) -> NodeHandoff:
            if req.task.type == "work":
                return WorkHandoff(node_id=req.task.id, done=True, report="ok")
            return ValidateHandoff(
                node_id=req.task.id,
                done=True,
                report="audited",
                items=[ValidationItem(item_id="VAL-001", passed=False)],
                passed=False,
            )

        controller = ProjectController(
            config,
            MockDispatcher(responder),
            MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
        )
        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, _tl_with_gate())

        events: list[str] = []
        controller.advance_project(pid, on_event=events.append)
        assert any(e.startswith("gate g1 failed:") for e in events)

    def test_broken_observer_does_not_break_the_wave(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        controller = _controller(config)
        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, _tl_with_gate())

        def broken(_: str) -> None:
            raise RuntimeError("observer died")

        env = controller.advance_project(pid, on_event=broken)
        assert env.state.state == "attention_needed"

    def test_advance_without_observer_still_works(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        controller = _controller(config)
        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, _tl_with_gate())
        env = controller.advance_project(pid)
        assert env.state.state == "attention_needed"


class _FakeContext:
    def __init__(self) -> None:
        self.infos: list[str] = []
        self.progress_calls: list[float] = []

    async def report_progress(self, progress: float, total: float | None = None):
        self.progress_calls.append(progress)

    async def info(self, message: str) -> None:
        self.infos.append(message)


class TestRunWithProgress:
    def test_forwards_events_and_returns_result(self) -> None:
        ctx = _FakeContext()

        def wave(a: int, b: int, on_event) -> int:
            on_event("first event")
            on_event("second event")
            return a + b

        result = asyncio.run(_run_with_progress(ctx, wave, 2, 3))
        assert result == 5
        assert "first event" in ctx.infos
        assert "second event" in ctx.infos
        assert len(ctx.progress_calls) >= 2

    def test_without_ctx_runs_and_passes_none_observer(self) -> None:
        seen: list[object] = []

        def wave(on_event) -> str:
            seen.append(on_event)
            return "done"

        assert asyncio.run(_run_with_progress(None, wave)) == "done"
        assert seen == [None]

    def test_exception_propagates(self) -> None:
        ctx = _FakeContext()

        def wave(on_event) -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            asyncio.run(_run_with_progress(ctx, wave))


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
