"""Harness configuration defaults."""
from __future__ import annotations

from pathlib import Path

from zenith_harness.config import HarnessConfig
from zenith_harness.providers import ProviderSelection, get_provider

_PROVIDER_ENV_KEYS = (
    "ZENITH_ORCHESTRATOR_PROVIDER",
    "ZENITH_WORKER_PROVIDER",
    "ZENITH_WORKER_ACP_COMMAND",
    "ZENITH_VALIDATOR_PROVIDER",
    "ZENITH_VALIDATOR_ACP_COMMAND",
    "ZENITH_TERMINAL_REVIEWER_PROVIDER",
    "ZENITH_TERMINAL_REVIEWER_ACP_COMMAND",
)


def _apply_selection_env(
    monkeypatch, harness_home: Path, selection: ProviderSelection
) -> HarnessConfig:
    """Write selection.env() to a clean environment and re-discover from it."""
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    for key in _PROVIDER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in selection.env().items():
        monkeypatch.setenv(key, value)
    return HarnessConfig.discover()


def test_discover_defaults_to_four_parallel_nodes(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECTS_DIR", raising=False)
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    monkeypatch.delenv("ZENITH_MAX_PARALLEL_NODES", raising=False)

    config = HarnessConfig.discover()

    assert config.max_parallel_nodes == 4


def test_discover_explicit_one_uses_serial_parallelism(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    monkeypatch.setenv("ZENITH_MAX_PARALLEL_NODES", "1")

    config = HarnessConfig.discover()

    assert config.max_parallel_nodes == 1


def test_discover_invalid_parallelism_falls_back_to_default(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    monkeypatch.setenv("ZENITH_MAX_PARALLEL_NODES", "not-an-int")

    config = HarnessConfig.discover()

    assert config.max_parallel_nodes == 4


def test_terminal_reviewer_selection_round_trips_through_env(
    monkeypatch,
    harness_home: Path,
) -> None:
    """A distinct terminal reviewer written by env() is read back intact."""
    selection = ProviderSelection(
        orchestrator=get_provider("claude"),
        worker=get_provider("claude"),
        terminal_reviewer=get_provider("codex"),
        terminal_reviewer_acp_command="custom-tr-acp",
    )

    config = _apply_selection_env(monkeypatch, harness_home, selection)

    assert config.terminal_reviewer_provider.name == "codex"
    assert config.resolved_terminal_reviewer_acp_command == "custom-tr-acp"


def test_terminal_reviewer_cascades_to_validator_after_round_trip(
    monkeypatch,
    harness_home: Path,
) -> None:
    """With no explicit terminal reviewer, discover() falls back to the validator.

    env() omits the terminal-reviewer vars because they match the validator
    (the cascade parent); the read side must reconstruct the same resolution.
    """
    selection = ProviderSelection(
        orchestrator=get_provider("claude"),
        worker=get_provider("claude"),
        validation_worker=get_provider("codex"),
    )

    assert "ZENITH_TERMINAL_REVIEWER_PROVIDER" not in selection.env()

    config = _apply_selection_env(monkeypatch, harness_home, selection)

    assert config.terminal_reviewer_provider_name is None
    assert config.terminal_reviewer_provider.name == "codex"
