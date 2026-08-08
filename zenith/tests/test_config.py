"""Harness configuration defaults."""
from __future__ import annotations

from pathlib import Path

import pytest

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


_EFFORT_ENV_VARS = (
    "ZENITH_WORKER_REASONING_EFFORT",
    "ZENITH_VALIDATOR_REASONING_EFFORT",
    "ZENITH_TERMINAL_REVIEWER_REASONING_EFFORT",
)


_MODEL_ENV_VARS = (
    "ZENITH_WORKER_MODEL",
    "ZENITH_VALIDATOR_MODEL",
    "ZENITH_TERMINAL_REVIEWER_MODEL",
)


def _clear_effort_env(monkeypatch) -> None:
    for var in _EFFORT_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _clear_model_env(monkeypatch) -> None:
    for var in _MODEL_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


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


def test_discover_reasoning_effort_defaults_to_none(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_effort_env(monkeypatch)

    config = HarnessConfig.discover()

    assert config.worker_reasoning_effort is None
    assert config.validator_reasoning_effort is None
    assert config.terminal_reviewer_reasoning_effort is None


def test_discover_reasoning_effort_per_role(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    monkeypatch.setenv("ZENITH_WORKER_REASONING_EFFORT", "high")
    monkeypatch.setenv("ZENITH_VALIDATOR_REASONING_EFFORT", "medium")
    monkeypatch.setenv("ZENITH_TERMINAL_REVIEWER_REASONING_EFFORT", "max")

    config = HarnessConfig.discover()

    assert config.worker_reasoning_effort == "high"
    assert config.validator_reasoning_effort == "medium"
    assert config.terminal_reviewer_reasoning_effort == "max"


def test_discover_invalid_reasoning_effort_rejected(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_effort_env(monkeypatch)
    # Not silently ignored: the value lands in a shell command line, and a
    # typo'd downgrade would silently keep spending xhigh.
    monkeypatch.setenv("ZENITH_VALIDATOR_REASONING_EFFORT", "extra-high")

    with pytest.raises(ValueError, match="ZENITH_VALIDATOR_REASONING_EFFORT"):
        HarnessConfig.discover()


def test_for_role_reasoning_effort_cascade(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_effort_env(monkeypatch)
    monkeypatch.setenv("ZENITH_WORKER_REASONING_EFFORT", "medium")

    config = HarnessConfig.discover()

    # Unset roles inherit down the same chain as providers/commands:
    # terminal_reviewer -> validator -> worker.
    assert config.for_role("worker").worker_reasoning_effort == "medium"
    assert config.for_role("validator").worker_reasoning_effort == "medium"
    assert config.for_role("terminal_reviewer").worker_reasoning_effort == "medium"


def test_for_role_reasoning_effort_explicit_override_wins(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_effort_env(monkeypatch)
    monkeypatch.setenv("ZENITH_WORKER_REASONING_EFFORT", "xhigh")
    monkeypatch.setenv("ZENITH_VALIDATOR_REASONING_EFFORT", "low")

    config = HarnessConfig.discover()

    assert config.for_role("worker").worker_reasoning_effort == "xhigh"
    assert config.for_role("validator").worker_reasoning_effort == "low"
    # terminal_reviewer falls back to the validator setting first.
    assert config.for_role("terminal_reviewer").worker_reasoning_effort == "low"


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


def test_validator_inherits_custom_worker_command_same_provider(
    monkeypatch,
    harness_home: Path,
) -> None:
    """A custom worker command cascades to a same-provider validator.

    Regression: the or-chain preferred the provider default (always
    truthy) over inheritance, so validators silently ran the stock
    adapter while workers ran the custom command (model flags, wrapper
    scripts, mocks).
    """
    selection = ProviderSelection(
        orchestrator=get_provider("claude"),
        worker=get_provider("claude"),
        worker_acp_command="claude-agent-acp --model custom",
    )

    config = _apply_selection_env(monkeypatch, harness_home, selection)

    assert (
        config.resolved_validator_acp_command
        == "claude-agent-acp --model custom"
    )
    assert (
        config.resolved_terminal_reviewer_acp_command
        == "claude-agent-acp --model custom"
    )
    # for_role is the dispatch-time consumer of the cascade.
    assert (
        config.for_role("validator").worker_acp_command
        == "claude-agent-acp --model custom"
    )
    assert (
        config.for_role("terminal_reviewer").worker_acp_command
        == "claude-agent-acp --model custom"
    )


def test_validator_provider_switch_uses_provider_default(
    monkeypatch,
    harness_home: Path,
) -> None:
    """A different validator provider must NOT inherit the worker command."""
    selection = ProviderSelection(
        orchestrator=get_provider("claude"),
        worker=get_provider("claude"),
        worker_acp_command="claude-agent-acp --model custom",
        validation_worker=get_provider("codex"),
    )

    config = _apply_selection_env(monkeypatch, harness_home, selection)

    assert config.resolved_validator_acp_command == "codex-acp"
    # Reviewer cascades from the validator (same provider as validator).
    assert config.resolved_terminal_reviewer_acp_command == "codex-acp"


def test_explicit_validator_command_beats_inheritance(
    monkeypatch,
    harness_home: Path,
) -> None:
    selection = ProviderSelection(
        orchestrator=get_provider("claude"),
        worker=get_provider("claude"),
        worker_acp_command="claude-agent-acp --model custom",
        validation_worker=get_provider("claude"),
        validation_worker_acp_command="claude-agent-acp --model validator",
    )

    config = _apply_selection_env(monkeypatch, harness_home, selection)

    assert (
        config.resolved_validator_acp_command
        == "claude-agent-acp --model validator"
    )
    # Reviewer inherits the validator's explicit command, not the worker's.
    assert (
        config.resolved_terminal_reviewer_acp_command
        == "claude-agent-acp --model validator"
    )


def test_config_resolution_matches_provider_selection(
    monkeypatch,
    harness_home: Path,
) -> None:
    """config.py and providers.py implement the same cascade — the read
    side of env() must resolve identically to the write side.
    """
    cases = [
        ProviderSelection(
            orchestrator=get_provider("claude"),
            worker=get_provider("claude"),
            worker_acp_command="claude-agent-acp --model custom",
        ),
        ProviderSelection(
            orchestrator=get_provider("claude"),
            worker=get_provider("claude"),
            worker_acp_command="claude-agent-acp --model custom",
            validation_worker=get_provider("codex"),
        ),
        ProviderSelection(
            orchestrator=get_provider("claude"),
            worker=get_provider("codex"),
            worker_acp_command="codex-acp -c model=\"custom\"",
            terminal_reviewer=get_provider("claude"),
        ),
    ]
    for selection in cases:
        config = _apply_selection_env(monkeypatch, harness_home, selection)
        assert (
            config.resolved_validator_acp_command
            == selection.resolved_validation_worker_acp_command
        ), selection
        assert (
            config.resolved_terminal_reviewer_acp_command
            == selection.resolved_terminal_reviewer_acp_command
        ), selection

def test_discover_model_defaults_to_none(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_model_env(monkeypatch)

    config = HarnessConfig.discover()

    # None means "whatever the provider picks" — no pin.
    assert config.worker_model is None
    assert config.validator_model is None
    assert config.terminal_reviewer_model is None


def test_discover_model_per_role(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    monkeypatch.setenv("ZENITH_WORKER_MODEL", "opus")
    monkeypatch.setenv("ZENITH_VALIDATOR_MODEL", "claude-opus-5[1m]")
    monkeypatch.setenv("ZENITH_TERMINAL_REVIEWER_MODEL", "gpt-5.5")

    config = HarnessConfig.discover()

    assert config.worker_model == "opus"
    assert config.validator_model == "claude-opus-5[1m]"
    assert config.terminal_reviewer_model == "gpt-5.5"


def test_discover_model_with_shell_metacharacters_rejected(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_model_env(monkeypatch)
    # The resolved value is spliced into a shell command line for codex
    # (`-c model="..."`), so anything that could break out of the quotes is
    # rejected at discovery rather than executed.
    monkeypatch.setenv("ZENITH_WORKER_MODEL", 'opus"; rm -rf /; #')

    with pytest.raises(ValueError, match="ZENITH_WORKER_MODEL"):
        HarnessConfig.discover()


def test_discover_model_with_trailing_newline_rejected(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_model_env(monkeypatch)
    # `$` matches before a trailing newline, so a pattern anchored with it
    # would accept "opus\n" — which then gets written into .codex/config.toml
    # as an unescaped newline inside a TOML basic string and corrupts the file.
    monkeypatch.setenv("ZENITH_WORKER_MODEL", "opus\n")

    with pytest.raises(ValueError, match="ZENITH_WORKER_MODEL"):
        HarnessConfig.discover()


def test_for_role_model_cascade(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_model_env(monkeypatch)
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ZENITH_WORKER_MODEL", "opus")

    config = HarnessConfig.discover()

    # Same inheritance chain as providers/commands/effort:
    # terminal_reviewer -> validator -> worker.
    assert config.for_role("worker").worker_model == "opus"
    assert config.for_role("validator").worker_model == "opus"
    assert config.for_role("terminal_reviewer").worker_model == "opus"


def _clear_provider_env(monkeypatch) -> None:
    for var in (
        "ZENITH_WORKER_PROVIDER",
        "ZENITH_VALIDATOR_PROVIDER",
        "ZENITH_TERMINAL_REVIEWER_PROVIDER",
    ):
        monkeypatch.delenv(var, raising=False)


def test_for_role_model_does_not_cascade_across_providers(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_model_env(monkeypatch)
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ZENITH_WORKER_PROVIDER", "codex")
    monkeypatch.setenv("ZENITH_WORKER_MODEL", "gpt-5.5")
    monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "claude")

    config = HarnessConfig.discover()

    # Reasoning efforts are provider-neutral vocabulary, so they cascade freely.
    # Model ids are not: inheriting the codex worker's pin would hand
    # ANTHROPIC_MODEL="gpt-5.5" to a claude validator and break every
    # validation session. An unpinned role on a different provider falls back
    # to that provider's own default instead.
    assert config.for_role("worker").worker_model == "gpt-5.5"
    assert config.for_role("validator").worker_model is None
    assert config.for_role("terminal_reviewer").worker_model is None


def test_for_role_model_cascades_when_provider_matches(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_model_env(monkeypatch)
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ZENITH_WORKER_PROVIDER", "claude")
    monkeypatch.setenv("ZENITH_WORKER_MODEL", "opus")
    # Spelling the provider out explicitly must not defeat inheritance.
    monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "claude")

    config = HarnessConfig.discover()

    assert config.for_role("validator").worker_model == "opus"
    assert config.for_role("terminal_reviewer").worker_model == "opus"


def test_for_role_model_explicit_pin_survives_provider_switch(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_model_env(monkeypatch)
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ZENITH_WORKER_PROVIDER", "codex")
    monkeypatch.setenv("ZENITH_WORKER_MODEL", "gpt-5.5")
    monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "claude")
    monkeypatch.setenv("ZENITH_VALIDATOR_MODEL", "opus")

    config = HarnessConfig.discover()

    # Only inheritance is provider-gated; a pin set for this role is obeyed.
    assert config.for_role("validator").worker_model == "opus"


def test_for_role_terminal_reviewer_model_does_not_inherit_across_providers(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_model_env(monkeypatch)
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ZENITH_WORKER_PROVIDER", "claude")
    monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "claude")
    monkeypatch.setenv("ZENITH_VALIDATOR_MODEL", "opus")
    monkeypatch.setenv("ZENITH_TERMINAL_REVIEWER_PROVIDER", "codex")

    config = HarnessConfig.discover()

    # The validator's claude pin must not reach a codex terminal reviewer.
    assert config.for_role("terminal_reviewer").worker_model is None


def test_for_role_terminal_reviewer_explicit_model_beats_validator_pin(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_model_env(monkeypatch)
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ZENITH_WORKER_MODEL", "sonnet")
    monkeypatch.setenv("ZENITH_VALIDATOR_MODEL", "opus")
    monkeypatch.setenv("ZENITH_TERMINAL_REVIEWER_MODEL", "claude-opus-5[1m]")

    config = HarnessConfig.discover()

    # Precedence within the chain: own pin first, then validator, then worker.
    assert config.for_role("terminal_reviewer").worker_model == "claude-opus-5[1m]"


def test_for_role_model_explicit_override_wins(
    monkeypatch,
    harness_home: Path,
) -> None:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.delenv("ZENITH_PROJECT_BUCKET_DIR", raising=False)
    _clear_model_env(monkeypatch)
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ZENITH_WORKER_MODEL", "sonnet")
    monkeypatch.setenv("ZENITH_VALIDATOR_MODEL", "opus")

    config = HarnessConfig.discover()

    assert config.for_role("worker").worker_model == "sonnet"
    assert config.for_role("validator").worker_model == "opus"
    # terminal_reviewer falls back to the validator setting first.
    assert config.for_role("terminal_reviewer").worker_model == "opus"
