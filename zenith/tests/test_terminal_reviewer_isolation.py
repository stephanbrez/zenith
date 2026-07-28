"""Terminal reviewer ambient-context isolation tests.

The terminal reviewer's system prompt declares the original user request
and the workspace as its only inputs and forbids reading provider skill
directories. These tests pin the runtime side of that contract: for the
claude provider, `session/new` must carry `_meta.claudeCode.options`
disabling filesystem setting sources and skill discovery, so the user's
global CLAUDE.md / settings.json / skills are not injected into the
reviewer's context by `claude-agent-acp` defaults.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from zenith_harness.acp_runner import (
    ACPNodeRunner,
    _cleanup_scoped_codex_home,
    _create_scoped_codex_home,
    _terminal_reviewer_session_meta,
)
from zenith_harness.assets import AssetLoader
from zenith_harness.config import HarnessConfig
from zenith_harness.models import TerminalReviewHandoff
from zenith_harness.providers import PROVIDERS
from zenith_harness.storage import ProjectStore


# ---------------------------------------------------------------------------
# Unit: _terminal_reviewer_session_meta
# ---------------------------------------------------------------------------


def test_session_meta_claude_disables_setting_sources_and_skills():
    meta = _terminal_reviewer_session_meta(PROVIDERS["claude"])
    assert meta is not None
    options = meta["claudeCode"]["options"]
    assert options["settingSources"] == []
    assert options["skills"] == []


@pytest.mark.parametrize("provider_name", ["codex", "hermes"])
def test_session_meta_non_claude_is_none(provider_name: str):
    assert _terminal_reviewer_session_meta(PROVIDERS[provider_name]) is None


# ---------------------------------------------------------------------------
# Wiring: session/new carries the _meta through the real ACP client
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_acp_command() -> str:
    mock = Path(__file__).resolve().parent / "mock_acp_agent.py"
    return f"{sys.executable} {mock}"


@pytest.fixture
def config(harness_home: Path, mock_acp_command: str) -> HarnessConfig:
    bundled = Path(__file__).resolve().parents[1] / "src" / "zenith_harness" / "bundled"
    return HarnessConfig(
        bundled_dir=bundled,
        harness_home=harness_home,
        projects_dir=harness_home / "projects",
        orchestrator_provider_name="claude",
        worker_provider_name="claude",
        worker_acp_command=mock_acp_command,
        validator_provider_name=None,
        validator_acp_command=None,
        terminal_reviewer_provider_name=None,
        # Explicit: the resolution chain prefers the provider's default
        # command ("claude-agent-acp") over an inherited custom worker
        # command, so leaving this None would spawn the real adapter.
        terminal_reviewer_acp_command=mock_acp_command,
    )


def test_run_terminal_review_sends_isolation_meta(
    config: HarnessConfig, workspace: Path, tmp_path: Path
):
    """End-to-end via the mock agent: the reviewer session must be opened
    with settingSources/skills disabled, and the handoff must round-trip.
    """
    store = ProjectStore(config)
    store.create_project("brief", workspace, project_id="p1")
    spawn_ts = "2026-07-27T00-00-00Z"
    report_path = store.terminal_review_path("p1", "mission-001", spawn_ts)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    params_path = tmp_path / "session_params.json"

    os.environ["ZENITH_HANDOFF_PATH"] = str(report_path)
    os.environ["ZENITH_NODE_TYPE"] = "terminal_review"
    os.environ["MOCK_ACP_SESSION_PARAMS_PATH"] = str(params_path)
    try:
        runner = ACPNodeRunner(config=config, loader=AssetLoader(config))

        async def _no_op_server(*args, **kwargs):
            return await asyncio.create_subprocess_exec(
                "sleep", "30",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

        async def _ready_immediately(*args, **kwargs):
            return None

        runner._start_terminal_reviewer_mcp = _no_op_server  # type: ignore[method-assign]
        runner._wait_for_server_ready = _ready_immediately  # type: ignore[method-assign]

        handoff = asyncio.run(
            runner.run_terminal_review(
                project_id="p1",
                mission_id="mission-001",
                spawn_ts=spawn_ts,
                store=store,
            )
        )
    finally:
        for k in (
            "ZENITH_HANDOFF_PATH",
            "ZENITH_NODE_TYPE",
            "MOCK_ACP_SESSION_PARAMS_PATH",
        ):
            os.environ.pop(k, None)

    assert isinstance(handoff, TerminalReviewHandoff)
    assert handoff.done is True

    params = json.loads(params_path.read_text())
    options = params["_meta"]["claudeCode"]["options"]
    assert options["settingSources"] == []
    assert options["skills"] == []


# ---------------------------------------------------------------------------
# Codex: scoped CODEX_HOME (fork-only; no per-session knob exists for codex)
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_codex_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real-looking CODEX_HOME with both operational and ambient files."""
    home = tmp_path / "codex-home"
    home.mkdir()
    (home / "auth.json").write_text('{"token": "t1"}')
    (home / "config.toml").write_text('model = "gpt-5.2-codex"\n')
    (home / "models_cache.json").write_text("{}")
    (home / "installation_id").write_text("abc")
    # Ambient context / prior-mission memory — must NOT be copied.
    (home / "AGENTS.md").write_text("# global rules")
    (home / "rules").mkdir()
    (home / "rules" / "dev-standards.md").write_text("rules")
    (home / "skills" / "my-skill").mkdir(parents=True)
    (home / "memories_1.sqlite").write_text("db")
    (home / "history.jsonl").write_text("{}")
    monkeypatch.setenv("CODEX_HOME", str(home))
    return home


def test_scoped_codex_home_non_codex_is_none():
    assert _create_scoped_codex_home(PROVIDERS["claude"]) is None
    assert _create_scoped_codex_home(PROVIDERS["hermes"]) is None


def test_scoped_codex_home_copies_operational_files_only(fake_codex_home: Path):
    scoped = _create_scoped_codex_home(PROVIDERS["codex"])
    assert scoped is not None
    try:
        present = sorted(p.name for p in scoped.iterdir())
        assert present == [
            "auth.json",
            "config.toml",
            "installation_id",
            "models_cache.json",
        ]
        assert (scoped / "auth.json").read_text() == '{"token": "t1"}'
    finally:
        _cleanup_scoped_codex_home(scoped)
    assert not scoped.exists()


def test_scoped_codex_home_writes_back_refreshed_auth(fake_codex_home: Path):
    scoped = _create_scoped_codex_home(PROVIDERS["codex"])
    assert scoped is not None
    # Simulate a mid-session token refresh in the scoped home.
    (scoped / "auth.json").write_text('{"token": "t2-refreshed"}')
    _cleanup_scoped_codex_home(scoped)
    assert (fake_codex_home / "auth.json").read_text() == '{"token": "t2-refreshed"}'
    assert not scoped.exists()


def test_scoped_codex_home_missing_real_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """No real CODEX_HOME → empty scoped home, codex first-run semantics."""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "does-not-exist"))
    scoped = _create_scoped_codex_home(PROVIDERS["codex"])
    assert scoped is not None
    try:
        assert list(scoped.iterdir()) == []
    finally:
        _cleanup_scoped_codex_home(scoped)
    assert not scoped.exists()


def test_run_terminal_review_codex_gets_scoped_home(
    config: HarnessConfig,
    workspace: Path,
    tmp_path: Path,
    fake_codex_home: Path,
    mock_acp_command: str,
):
    """Wiring: with a codex reviewer the agent's CODEX_HOME is a scoped
    copy (auth present, AGENTS.md absent), and it is removed afterwards.
    """
    from dataclasses import replace

    codex_config = replace(
        config,
        worker_provider_name="codex",
        terminal_reviewer_acp_command=mock_acp_command,
    )
    store = ProjectStore(codex_config)
    store.create_project("brief", workspace, project_id="p1")
    spawn_ts = "2026-07-27T00-00-00Z"
    report_path = store.terminal_review_path("p1", "mission-001", spawn_ts)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    env_path = tmp_path / "env_seen.json"

    os.environ["ZENITH_HANDOFF_PATH"] = str(report_path)
    os.environ["ZENITH_NODE_TYPE"] = "terminal_review"
    os.environ["MOCK_ACP_ENV_DUMP_PATH"] = str(env_path)
    try:
        runner = ACPNodeRunner(config=codex_config, loader=AssetLoader(codex_config))

        async def _no_op_server(*args, **kwargs):
            return await asyncio.create_subprocess_exec(
                "sleep", "30",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

        async def _ready_immediately(*args, **kwargs):
            return None

        runner._start_terminal_reviewer_mcp = _no_op_server  # type: ignore[method-assign]
        runner._wait_for_server_ready = _ready_immediately  # type: ignore[method-assign]

        handoff = asyncio.run(
            runner.run_terminal_review(
                project_id="p1",
                mission_id="mission-001",
                spawn_ts=spawn_ts,
                store=store,
            )
        )
    finally:
        for k in (
            "ZENITH_HANDOFF_PATH",
            "ZENITH_NODE_TYPE",
            "MOCK_ACP_ENV_DUMP_PATH",
        ):
            os.environ.pop(k, None)

    assert isinstance(handoff, TerminalReviewHandoff)
    env_seen = json.loads(env_path.read_text())
    scoped_home = Path(env_seen["CODEX_HOME"])
    assert scoped_home != fake_codex_home
    assert env_seen["CODEX_HOME_HAD_AUTH"] is True
    assert env_seen["CODEX_HOME_HAD_AGENTS_MD"] is False
    # Scoped home is removed after the session.
    assert not scoped_home.exists()
