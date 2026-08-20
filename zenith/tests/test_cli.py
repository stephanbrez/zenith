"""CLI integration tests — init / list-projects / show-project / install-skills."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

from zenith_harness.cli import cli
from zenith_harness.config import HarnessConfig


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def _scrub_ambient_role_env(monkeypatch) -> None:
    """Init reads ambient ZENITH_* role settings when resolving a lane, so a
    developer's exported pin, provider or command would otherwise leak into
    these
    assertions. Tests that want one set it themselves.
    """
    for role in ("WORKER", "VALIDATOR", "TERMINAL_REVIEWER"):
        for suffix in ("MODEL", "PROVIDER", "ACP_COMMAND", "REASONING_EFFORT"):
            monkeypatch.delenv(f"ZENITH_{role}_{suffix}", raising=False)


@pytest.fixture
def env(harness_home: Path, workspace: Path, monkeypatch) -> dict[str, str]:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.chdir(workspace)
    return {"ZENITH_HOME": str(harness_home)}


def _expected_mcp_server_args() -> list[str]:
    zenith_root = Path(__file__).resolve().parents[1]
    return [
        "run",
        "--project",
        str(zenith_root),
        "zenith-server",
        "--mode",
        "orchestrator",
    ]


def _tree_snapshot(root: Path) -> dict[str, tuple[str, int, bytes]]:
    snapshot: dict[str, tuple[str, int, bytes]] = {}
    for path in (root, *sorted(root.rglob("*"))):
        relative = str(path.relative_to(root))
        kind = "directory" if path.is_dir() else "file"
        content = b"" if path.is_dir() else path.read_bytes()
        snapshot[relative] = (kind, stat.S_IMODE(path.stat().st_mode), content)
    return snapshot


class TestInit:
    def test_stages_host_agent_surface_only(
        self, runner: CliRunner, workspace: Path, env: dict[str, str]
    ) -> None:
        """`zenith init` writes MCP config + provider agents + orchestrator prompt
        but does NOT create the project bucket or workspace shims — those are
        created by `start_project` at the first MCP call."""
        result = runner.invoke(
            cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"]
        )
        assert result.exit_code == 0, result.output
        # Workspace stays clean of .zenith/ — bucket lives under ZENITH_HOME.
        assert not (workspace / ".zenith").exists()
        # No symlink shims either — start_project handles them.
        assert not (workspace / "AGENTS.md").exists()
        # MCP config + .claude/agents/ are written.
        assert (workspace / ".mcp.json").exists()
        mcp = json.loads((workspace / ".mcp.json").read_text())
        assert "zenith" in mcp["mcpServers"]
        server = mcp["mcpServers"]["zenith"]
        assert server["command"] == "uv"
        assert server["args"] == _expected_mcp_server_args()

    def test_init_does_not_touch_gitignore(
        self, runner: CliRunner, workspace: Path, env: dict[str, str]
    ) -> None:
        gitignore = workspace / ".gitignore"
        gitignore.write_text("node_modules/\n")
        original = gitignore.read_text()
        r = runner.invoke(
            cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"]
        )
        assert r.exit_code == 0, r.output
        assert gitignore.read_text() == original

    def test_idempotent(
        self, runner: CliRunner, workspace: Path, env: dict[str, str]
    ) -> None:
        for _ in range(2):
            r = runner.invoke(
                cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"]
            )
            assert r.exit_code == 0, r.output
        # .mcp.json preserved across reruns.
        assert (workspace / ".mcp.json").exists()

    def test_codex_writes_codex_config(
        self, runner: CliRunner, workspace: Path, env: dict[str, str]
    ) -> None:
        r = runner.invoke(cli, ["init", "--workspace-dir", str(workspace), "--agent", "codex"])
        assert r.exit_code == 0, r.output
        config_path = workspace / ".codex" / "config.toml"
        assert config_path.exists()
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        server = config["mcp_servers"]["zenith"]
        assert server["command"] == "uv"
        assert server["args"] == _expected_mcp_server_args()
        assert f"Initialized v5 project workspace at {workspace}" in r.output
        assert "Start your agent from the initialized project workspace" in r.output
        assert (
            "First read .codex/orchestrator_prompt.md and treat it as your primary role, "
            "then use Zenith to run this mission." in r.output
        )

    def test_claude_init_writes_reasoning_effort_env(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ZENITH_WORKER_REASONING_EFFORT", "high")
        monkeypatch.setenv("ZENITH_VALIDATOR_REASONING_EFFORT", "medium")
        monkeypatch.setenv("ZENITH_TERMINAL_REVIEWER_REASONING_EFFORT", "low")

        r = runner.invoke(cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"])
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        assert server_env["ZENITH_WORKER_REASONING_EFFORT"] == "high"
        assert server_env["ZENITH_VALIDATOR_REASONING_EFFORT"] == "medium"
        assert server_env["ZENITH_TERMINAL_REVIEWER_REASONING_EFFORT"] == "low"

    def test_codex_init_writes_reasoning_effort_env(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ZENITH_WORKER_REASONING_EFFORT", "high")
        monkeypatch.setenv("ZENITH_VALIDATOR_REASONING_EFFORT", "medium")
        monkeypatch.setenv("ZENITH_TERMINAL_REVIEWER_REASONING_EFFORT", "low")

        r = runner.invoke(cli, ["init", "--workspace-dir", str(workspace), "--agent", "codex"])
        assert r.exit_code == 0, r.output

        config = tomllib.loads(
            (workspace / ".codex" / "config.toml").read_text(encoding="utf-8")
        )
        server_env = config["mcp_servers"]["zenith"]["env"]
        assert server_env["ZENITH_WORKER_REASONING_EFFORT"] == "high"
        assert server_env["ZENITH_VALIDATOR_REASONING_EFFORT"] == "medium"
        assert server_env["ZENITH_TERMINAL_REVIEWER_REASONING_EFFORT"] == "low"

    def test_codex_init_escapes_quoted_acp_commands(
        self, runner: CliRunner, workspace: Path, env: dict[str, str]
    ) -> None:
        """Quoted ACP commands must survive into config.toml as valid TOML.

        `-c key="value"` is the supported splice shape for codex config, so
        every role's command can carry double quotes. Interpolating them raw
        terminates the TOML string early and corrupts the managed block.
        """
        worker_cmd = 'codex-acp -c model="gpt-5.6-luna"'
        validator_cmd = 'codex-acp -c model="gpt-5.6-terra"'
        reviewer_cmd = 'codex-acp -c model="gpt-5.6-sol"'

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "codex",
                "--worker-acp-command",
                worker_cmd,
                "--validator-acp-command",
                validator_cmd,
                "--terminal-reviewer-acp-command",
                reviewer_cmd,
            ],
        )
        assert r.exit_code == 0, r.output

        # Parsing at all is the regression guard — this raises before the fix.
        config = tomllib.loads(
            (workspace / ".codex" / "config.toml").read_text(encoding="utf-8")
        )
        server_env = config["mcp_servers"]["zenith"]["env"]
        assert server_env["ZENITH_WORKER_ACP_COMMAND"] == worker_cmd
        assert server_env["ZENITH_VALIDATOR_ACP_COMMAND"] == validator_cmd
        assert server_env["ZENITH_TERMINAL_REVIEWER_ACP_COMMAND"] == reviewer_cmd

    def test_init_reasoning_effort_flags_override_env(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ZENITH_WORKER_REASONING_EFFORT", "xhigh")

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--worker-reasoning-effort",
                "max",
                "--validator-reasoning-effort",
                "medium",
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        # Flag beats the inherited shell env.
        assert server_env["ZENITH_WORKER_REASONING_EFFORT"] == "max"
        assert server_env["ZENITH_VALIDATOR_REASONING_EFFORT"] == "medium"
        assert "ZENITH_TERMINAL_REVIEWER_REASONING_EFFORT" not in server_env

    def test_init_invalid_inherited_effort_env_fails_despite_flag(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Flags override valid inherited settings; a broken env var is still a
        # hard error — the same validation would raise at server launch, so
        # masking it at init would only defer the failure.
        monkeypatch.setenv("ZENITH_WORKER_REASONING_EFFORT", "turbo")

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--worker-reasoning-effort",
                "max",
            ],
        )
        # A complaint about the caller's environment, reported the way a bad
        # flag is rather than as a traceback.
        assert r.exit_code == 2, r.output
        assert "ZENITH_WORKER_REASONING_EFFORT" in r.output

    def test_claude_init_writes_model_flags(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--worker-model",
                "sonnet",
                "--validator-model",
                "opus",
                "--terminal-reviewer-model",
                "claude-opus-5[1m]",
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        assert server_env["ZENITH_WORKER_MODEL"] == "sonnet"
        assert server_env["ZENITH_VALIDATOR_MODEL"] == "opus"
        assert server_env["ZENITH_TERMINAL_REVIEWER_MODEL"] == "claude-opus-5[1m]"

    def test_init_does_not_bake_ambient_model_pins_into_the_workspace(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The pin a shell happens to carry says nothing about which provider it
        # was chosen for. Forwarding it would make a leftover codex pin durable
        # in a claude workspace and hand it to claude-agent-acp as
        # ANTHROPIC_MODEL — the cross-provider landing _inherited_model exists
        # to prevent. Ambient pins are honored only by a server the user
        # launches from that same shell; init never writes them down.
        monkeypatch.setenv("ZENITH_WORKER_MODEL", "gpt-5.5-codex")
        monkeypatch.setenv("ZENITH_VALIDATOR_MODEL", "gpt-5.5-codex")
        monkeypatch.setenv("ZENITH_TERMINAL_REVIEWER_MODEL", "gpt-5.5-codex")

        r = runner.invoke(cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"])
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        assert "ZENITH_WORKER_MODEL" not in server_env
        assert "ZENITH_VALIDATOR_MODEL" not in server_env
        assert "ZENITH_TERMINAL_REVIEWER_MODEL" not in server_env

    def test_init_model_flags_override_env(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Scrubbed so an exported pin in the developer's own shell cannot leak
        # in through _forwarded_runtime_env() and break the "not in" assert.
        for var in (
            "ZENITH_VALIDATOR_MODEL",
            "ZENITH_TERMINAL_REVIEWER_MODEL",
        ):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("ZENITH_WORKER_MODEL", "sonnet")

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--worker-model",
                "opus",
                "--validator-model",
                "claude-opus-5[1m]",
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        # Flag beats the inherited shell env.
        assert server_env["ZENITH_WORKER_MODEL"] == "opus"
        assert server_env["ZENITH_VALIDATOR_MODEL"] == "claude-opus-5[1m]"
        assert "ZENITH_TERMINAL_REVIEWER_MODEL" not in server_env

    def test_init_invalid_inherited_model_env_fails_when_no_flag_replaces_it(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Unreplaced, the broken pin still reaches a server launched from this
        # shell, so init refuses rather than deferring the failure.
        monkeypatch.setenv("ZENITH_WORKER_MODEL", "opus; touch /tmp/pwned")

        r = runner.invoke(
            cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"]
        )
        assert r.exit_code == 2, r.output
        assert "ZENITH_WORKER_MODEL" in r.output

    def test_init_ignores_an_invalid_inherited_model_env_a_flag_replaces(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Diverges from the reasoning-effort contract on purpose. An effort var
        # is forwarded into the workspace, so a broken one stays live; a model
        # pin is not, and the flag's value is what every server started from
        # this workspace will read. Failing on a value init has already decided
        # to ignore would be a dead end for the user.
        monkeypatch.setenv("ZENITH_WORKER_MODEL", "opus; touch /tmp/pwned")

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--worker-model",
                "sonnet",
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        assert server_env["ZENITH_WORKER_MODEL"] == "sonnet"
        # The caller's environment is left as it was found.
        assert os.environ["ZENITH_WORKER_MODEL"] == "opus; touch /tmp/pwned"

    def test_init_rejects_model_flag_with_shell_metacharacters(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        for var in (
            "ZENITH_WORKER_MODEL",
            "ZENITH_VALIDATOR_MODEL",
            "ZENITH_TERMINAL_REVIEWER_MODEL",
        ):
            monkeypatch.delenv(var, raising=False)

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "codex",
                "--worker-model",
                'gpt-5.5"; rm -rf /; #',
            ],
        )

        # A flag value lands in the same shell command line as the env var, so
        # it gets the same validation instead of being written out verbatim —
        # but reported as a usage error naming the flag the user actually
        # typed, not a traceback naming an env var they never set.
        assert r.exit_code == 2
        assert "--worker-model" in r.output
        assert "ZENITH_WORKER_MODEL" not in r.output
        assert not (workspace / ".codex" / "config.toml").exists()

    def test_init_rejects_empty_model_flag(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # An inherited pin the user is trying to clear must not be silently
        # forwarded as if they had said nothing.
        monkeypatch.setenv("ZENITH_WORKER_MODEL", "sonnet")

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--worker-model",
                "",
            ],
        )

        assert r.exit_code == 2
        assert "--worker-model" in r.output

    def test_init_warns_when_model_pin_targets_hermes(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        for var in (
            "ZENITH_WORKER_MODEL",
            "ZENITH_VALIDATOR_MODEL",
            "ZENITH_TERMINAL_REVIEWER_MODEL",
        ):
            monkeypatch.delenv(var, raising=False)

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "hermes",
                "--worker-model",
                "some-model",
            ],
        )
        assert r.exit_code == 0, r.output

        # hermes takes no model selection, so the pin is a no-op. Init still
        # succeeds — but silently discarding what the user typed is the bug.
        assert "warning" in r.output.lower()
        assert "--worker-model" in r.output
        assert "hermes" in r.output

    def test_init_persists_terminal_reviewer_provider(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ZENITH_TERMINAL_REVIEWER_PROVIDER", raising=False)
        monkeypatch.delenv("ZENITH_TERMINAL_REVIEWER_ACP_COMMAND", raising=False)

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--terminal-reviewer-provider",
                "codex",
                "--terminal-reviewer-acp-command",
                "codex-acp",
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        # Accepted-and-discarded is worse than rejected: the flag reads as
        # configured while every terminal review runs on the validator's
        # provider instead.
        assert server_env["ZENITH_TERMINAL_REVIEWER_PROVIDER"] == "codex"
        assert server_env["ZENITH_TERMINAL_REVIEWER_ACP_COMMAND"] == "codex-acp"

    def test_init_warns_when_model_flag_targets_hermes(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "hermes",
                "--worker-model",
                "some-model",
            ],
        )
        assert r.exit_code == 0, r.output

        assert "warning" in r.output.lower()
        assert "--worker-model" in r.output
        assert "hermes" in r.output

    def test_init_warns_when_a_pinned_lane_launches_a_custom_command(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Provider-specific treatment (ANTHROPIC_MODEL for claude, `-c model=`
        # for codex) is applied for the provider the lane dispatches as, while
        # the command is configured independently — point at the mismatch
        # instead of letting the pin vanish into a binary that never reads it.
        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--terminal-reviewer-acp-command",
                "codex-acp",
                "--terminal-reviewer-model",
                "opus",
            ],
        )
        assert r.exit_code == 0, r.output

        assert "warning" in r.output.lower()
        assert "terminal reviewer" in r.output
        assert "codex-acp" in r.output

    def test_init_does_not_warn_when_the_command_is_the_providers_own_default(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Spelling out the default a lane would have used anyway is not a
        # mismatch. Warning here would train the user to ignore the warning
        # above, which is the one that means something.
        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--worker-acp-command",
                "claude-agent-acp",
                "--worker-model",
                "opus",
            ],
        )
        assert r.exit_code == 0, r.output

        assert "warning" not in r.output.lower()

    def test_init_installs_assets_for_a_validator_resolved_from_the_environment(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The reviewer is pinned elsewhere, so it cannot mask the gap by
        # inheriting the validator's provider: a config naming a codex
        # validator must come with codex agents and skills on disk.
        monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "codex")

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--terminal-reviewer-provider",
                "claude",
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        assert server_env["ZENITH_VALIDATOR_PROVIDER"] == "codex"
        assert (workspace / ".codex" / "agents").is_dir()

    def test_init_terminal_reviewer_inherits_the_validator_not_the_worker(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Matches for_role("terminal_reviewer"), which falls back to the
        # validator. Init now WRITES this provider unconditionally, so a wrong
        # inheritance here cannot be corrected by the runtime chain — the
        # written value wins.
        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--validator-provider",
                "codex",
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        assert server_env["ZENITH_TERMINAL_REVIEWER_PROVIDER"] == "codex"

    def test_init_command_flag_beats_ambient_command_env(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Same precedence claim the provider flags carry, for commands.
        monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "claude")
        monkeypatch.setenv("ZENITH_VALIDATOR_ACP_COMMAND", "stale-agent-acp")

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--validator-acp-command",
                "claude-agent-acp --lane validate",
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        assert server_env["ZENITH_VALIDATOR_ACP_COMMAND"] == "claude-agent-acp --lane validate"

    def test_init_drops_an_ambient_command_whose_provider_it_discarded(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Init sets the worker provider itself, so a shell that was talking
        # about a different provider must not get to set the worker's command.
        # Keeping half of a stale pair manufactures a claude lane that launches
        # codex-acp: no sandbox flags, no codex env, and a claude-only ACP mode
        # id sent to codex — durably, in the config init just wrote.
        monkeypatch.setenv("ZENITH_WORKER_PROVIDER", "codex")
        monkeypatch.setenv("ZENITH_WORKER_ACP_COMMAND", "codex-acp")

        r = runner.invoke(cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"])
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        assert server_env["ZENITH_WORKER_PROVIDER"] == "claude"
        assert server_env.get("ZENITH_WORKER_ACP_COMMAND") != "codex-acp"

    def test_init_keeps_an_ambient_command_paired_with_its_provider(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The other half of the pairing rule: exported together, they describe
        # one coherent lane, and dropping the command would send it back to the
        # worker's binary at runtime — the original defect.
        monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "codex")
        monkeypatch.setenv("ZENITH_VALIDATOR_ACP_COMMAND", "codex-acp --lane validate")

        r = runner.invoke(cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"])
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        assert server_env["ZENITH_VALIDATOR_PROVIDER"] == "codex"
        assert server_env["ZENITH_VALIDATOR_ACP_COMMAND"] == "codex-acp --lane validate"

    def test_init_warns_about_a_foreign_command(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The mismatch is a hazard on its own: sandbox flags, the codex config
        # flags and the ACP session mode all key on provider.name, so a model
        # pin is incidental to it and the warning is not gated on one.
        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--worker-acp-command",
                "codex-acp",
            ],
        )
        assert r.exit_code == 0, r.output

        assert "warning" in r.output.lower()
        assert "codex-acp" in r.output

    @pytest.mark.parametrize(
        "command",
        ["claude-agent-acp --verbose", "/usr/local/bin/claude-agent-acp"],
    )
    def test_init_does_not_warn_for_the_providers_own_binary(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
        command: str,
    ) -> None:
        # An absolute path or extra arguments still run claude-agent-acp. The
        # question is which binary runs, not whether the string matches.
        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--worker-acp-command",
                command,
            ],
        )
        assert r.exit_code == 0, r.output

        assert "warning" not in r.output.lower()

    def test_init_summary_reports_the_resolved_roles(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The summary is the only thing most users read; it must not contradict
        # the config written one line earlier.
        monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "codex")

        r = runner.invoke(cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"])
        assert r.exit_code == 0, r.output

        assert "validator=codex" in r.output

    def test_init_warns_when_ambient_provider_env_makes_the_lane_hermes(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # An ambient role provider is resolved AND written, so the warning
        # describes the workspace init produced rather than the shell it ran
        # in. Asserting the written value is the point: the host agent is
        # normally launched later, from a different shell.
        monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "hermes")

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--validator-model",
                "opus",
            ],
        )
        assert r.exit_code == 0, r.output

        assert "warning" in r.output.lower()
        assert "--validator-model" in r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        assert server_env["ZENITH_VALIDATOR_PROVIDER"] == "hermes"

    def test_init_provider_flag_beats_ambient_provider_env(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # A stale export must not overrule what the user typed, and a typo in
        # it must not fail an init that never consults it.
        monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "clyde")

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--validator-provider",
                "claude",
                "--validator-model",
                "opus",
            ],
        )
        assert r.exit_code == 0, r.output
        assert "warning" not in r.output.lower()

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        assert server_env["ZENITH_VALIDATOR_PROVIDER"] == "claude"
        assert server_env["ZENITH_VALIDATOR_MODEL"] == "opus"

    def test_init_does_not_warn_when_ambient_provider_env_rescues_the_lane(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Mirror case: the reviewer lane resolves to claude, so the pin is
        # honored and warning about it would be a lie. The rescue has to be
        # written down for that to stay true after init exits.
        monkeypatch.setenv("ZENITH_TERMINAL_REVIEWER_PROVIDER", "claude")

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "hermes",
                "--terminal-reviewer-model",
                "opus",
            ],
        )
        assert r.exit_code == 0, r.output

        assert "--terminal-reviewer-model" not in r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        assert server_env["ZENITH_TERMINAL_REVIEWER_PROVIDER"] == "claude"
        assert server_env["ZENITH_TERMINAL_REVIEWER_MODEL"] == "opus"

    def test_written_config_reproduces_init_resolution_in_a_clean_environment(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The seam every other test in this file stops short of.

        Init resolves lanes; the server resolves them again from the written
        config, in a later process launched from a different shell. Every
        divergence between those two resolvers is a bug that per-lane
        assertions on init's output cannot see, so this drives the real
        `discover() + for_role()` over exactly what init wrote.
        """
        # Validator lands on a different provider than the worker, so the
        # worker's pin must not reach it; the reviewer lands back on the
        # worker's provider, so it must jump the gap and pick the pin up.
        # Both role settings that init can only learn from the environment are
        # exercised — a provider and a command.
        monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "codex")
        monkeypatch.setenv("ZENITH_VALIDATOR_ACP_COMMAND", "codex-acp --lane validate")

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--worker-model",
                "opus",
                "--worker-reasoning-effort",
                "max",
                "--terminal-reviewer-provider",
                "claude",
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]

        # Stand in for the later launch: nothing survives but the file.
        for var in list(os.environ):
            if var.startswith("ZENITH_") or var == "ANTHROPIC_MODEL":
                monkeypatch.delenv(var, raising=False)
        for key, value in server_env.items():
            monkeypatch.setenv(key, value)

        config = HarnessConfig.discover()

        worker = config.for_role("worker")
        assert worker.worker_provider_name == "claude"
        assert worker.worker_model == "opus"
        assert worker.worker_reasoning_effort == "max"
        assert worker.resolved_worker_acp_command == "claude-agent-acp"

        validator = config.for_role("validator")
        assert validator.worker_provider_name == "codex"
        assert validator.worker_model is None
        assert validator.resolved_worker_acp_command == "codex-acp --lane validate"
        # Provider-neutral vocabulary, so this one does inherit across the gap.
        assert validator.worker_reasoning_effort == "max"

        reviewer = config.for_role("terminal_reviewer")
        assert reviewer.worker_provider_name == "claude"
        assert reviewer.worker_model == "opus"

    def test_init_installs_assets_for_terminal_reviewer_provider(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ZENITH_TERMINAL_REVIEWER_PROVIDER", raising=False)

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--terminal-reviewer-provider",
                "codex",
            ],
        )
        assert r.exit_code == 0, r.output

        # The reviewer really runs codex-acp now, so it needs the same asset
        # surface --validator-provider codex would have installed.
        assert (workspace / ".codex" / "agents").is_dir()

    def test_init_rejects_unknown_ambient_terminal_reviewer_provider_before_writing(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The flags carry a click.Choice, but an exported var does not — and it
        # is read late, so a typo used to raise ValueError only after the config
        # had been written, leaving a half-initialized workspace behind.
        monkeypatch.setenv("ZENITH_TERMINAL_REVIEWER_PROVIDER", "clyde")

        r = runner.invoke(
            cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"]
        )

        assert r.exit_code != 0
        assert "clyde" in r.output
        assert "ZENITH_TERMINAL_REVIEWER_PROVIDER" in r.output
        assert not (workspace / ".mcp.json").exists()

    def test_init_error_names_the_variable_that_supplied_the_bad_provider(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ZENITH_TERMINAL_REVIEWER_PROVIDER", raising=False)
        # The terminal lane inherits this name, but blaming
        # ZENITH_TERMINAL_REVIEWER_PROVIDER sends the user hunting for a
        # variable they never set.
        monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "clyde")

        r = runner.invoke(
            cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"]
        )

        assert r.exit_code != 0
        assert "ZENITH_VALIDATOR_PROVIDER" in r.output
        assert "ZENITH_TERMINAL_REVIEWER_PROVIDER" not in r.output
        assert not (workspace / ".mcp.json").exists()

    def test_init_validates_validator_provider_even_when_terminal_is_explicit(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "clyde")

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--terminal-reviewer-provider",
                "codex",
            ],
        )

        # An explicit terminal provider must not mask a broken validator lane:
        # without this the typo detonates mid-mission at the first validate
        # dispatch instead of at init.
        assert r.exit_code != 0
        assert "ZENITH_VALIDATOR_PROVIDER" in r.output
        assert not (workspace / ".mcp.json").exists()

    def test_claude_init_log_flags_write_env(
        self, runner: CliRunner, workspace: Path, env: dict[str, str]
    ) -> None:
        log_path = workspace / "logs" / "zenith.log"
        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--log-level",
                "info",
                "--log-file",
                str(log_path),
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        # Level is normalized to upper case; path is resolved.
        assert server_env["ZENITH_LOG_LEVEL"] == "INFO"
        assert server_env["ZENITH_LOG_FILE"] == str(log_path.resolve())

    def test_codex_init_log_flags_write_env(
        self, runner: CliRunner, workspace: Path, env: dict[str, str]
    ) -> None:
        log_path = workspace / "logs" / "zenith.log"
        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "codex",
                "--log-level",
                "DEBUG",
                "--log-file",
                str(log_path),
            ],
        )
        assert r.exit_code == 0, r.output

        config = tomllib.loads(
            (workspace / ".codex" / "config.toml").read_text(encoding="utf-8")
        )
        server_env = config["mcp_servers"]["zenith"]["env"]
        assert server_env["ZENITH_LOG_LEVEL"] == "DEBUG"
        assert server_env["ZENITH_LOG_FILE"] == str(log_path.resolve())

    def test_init_forwards_inherited_log_env_without_flags(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ZENITH_LOG_LEVEL", "INFO")
        monkeypatch.setenv("ZENITH_LOG_FILE", "/var/log/zenith.log")

        r = runner.invoke(cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"])
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        # Forwarded verbatim — the shell already resolved what it wanted.
        assert server_env["ZENITH_LOG_LEVEL"] == "INFO"
        assert server_env["ZENITH_LOG_FILE"] == "/var/log/zenith.log"

    def test_init_log_flags_override_inherited_env(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ZENITH_LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("ZENITH_LOG_FILE", "/elsewhere/old.log")
        log_path = workspace / "logs" / "zenith.log"

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--log-level",
                "warning",
                "--log-file",
                str(log_path),
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        assert server_env["ZENITH_LOG_LEVEL"] == "WARNING"
        assert server_env["ZENITH_LOG_FILE"] == str(log_path.resolve())

    def test_init_rejects_unknown_log_level(
        self, runner: CliRunner, workspace: Path, env: dict[str, str]
    ) -> None:
        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--log-level",
                "verbose",
            ],
        )
        assert r.exit_code != 0
        assert "--log-level" in r.output

    def test_init_does_not_warn_for_supported_provider_pin(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        for var in (
            "ZENITH_WORKER_MODEL",
            "ZENITH_VALIDATOR_MODEL",
            "ZENITH_TERMINAL_REVIEWER_MODEL",
        ):
            monkeypatch.delenv(var, raising=False)

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--worker-model",
                "opus",
            ],
        )
        assert r.exit_code == 0, r.output
        assert "warning" not in r.output.lower()

    def test_claude_init_writes_runtime_validator_env_names(
        self, runner: CliRunner, workspace: Path, env: dict[str, str]
    ) -> None:
        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--validator-provider",
                "codex",
                "--validator-acp-command",
                "custom-validator-acp",
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text())
        mcp_env = mcp["mcpServers"]["zenith"]["env"]
        assert mcp_env["ZENITH_VALIDATOR_PROVIDER"] == "codex"
        assert mcp_env["ZENITH_VALIDATOR_ACP_COMMAND"] == "custom-validator-acp"
        assert "ZENITH_VALIDATION_WORKER_PROVIDER" not in mcp_env
        assert "ZENITH_VALIDATION_WORKER_ACP_COMMAND" not in mcp_env

    def test_claude_init_forwards_only_allowed_model_env(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.z.ai/api/anthropic")
        monkeypatch.setenv("ANTHROPIC_MODEL", "glm-5.2[1m]")
        monkeypatch.setenv("ZAI_API_KEY", "zai-test-key")
        monkeypatch.setenv("DATABASE_URL", "postgres://should-not-forward")

        r = runner.invoke(cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"])
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text())
        mcp_env = mcp["mcpServers"]["zenith"]["env"]
        assert mcp_env["ANTHROPIC_BASE_URL"] == "https://api.z.ai/api/anthropic"
        assert mcp_env["ANTHROPIC_MODEL"] == "glm-5.2[1m]"
        assert mcp_env["ZAI_API_KEY"] == "zai-test-key"
        assert "DATABASE_URL" not in mcp_env

    def test_claude_init_writes_terminal_reviewer_env_names(
        self, runner: CliRunner, workspace: Path, env: dict[str, str]
    ) -> None:
        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--terminal-reviewer-provider",
                "codex",
                "--terminal-reviewer-acp-command",
                "custom-tr-acp",
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text())
        mcp_env = mcp["mcpServers"]["zenith"]["env"]
        assert mcp_env["ZENITH_TERMINAL_REVIEWER_PROVIDER"] == "codex"
        assert mcp_env["ZENITH_TERMINAL_REVIEWER_ACP_COMMAND"] == "custom-tr-acp"

    def test_claude_init_writes_inherited_terminal_reviewer_provider(
        self, runner: CliRunner, workspace: Path, env: dict[str, str]
    ) -> None:
        """An unset reviewer provider is written as whatever it resolved to.

        Init resolves every role and stages the result, so a config can be
        read without replaying the cascade. The ACP command is still omitted:
        it is taken only from a flag or from an environment pair, and the
        read side re-derives an inherited command from the lane above.
        """
        r = runner.invoke(
            cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"]
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text())
        mcp_env = mcp["mcpServers"]["zenith"]["env"]
        assert mcp_env["ZENITH_TERMINAL_REVIEWER_PROVIDER"] == "claude"
        assert mcp_env["ZENITH_VALIDATOR_PROVIDER"] == "claude"
        assert "ZENITH_TERMINAL_REVIEWER_ACP_COMMAND" not in mcp_env

    def test_explicit_role_acp_commands_survive_matching_parent(
        self, runner: CliRunner, workspace: Path, env: dict[str, str]
    ) -> None:
        """A command passed per role is persisted even when it equals its
        cascade parent's.

        Inherited values are deduped against the parent (worker → validator
        → terminal reviewer) because the read side re-derives them. An
        *explicit* flag must not be swallowed by that dedup: the generated
        config is what the user inspects, and a hand-edit of the parent's
        command would otherwise silently retarget the child role.
        """
        worker_cmd = "claude-agent-acp --model opus"
        shared_cmd = "claude-agent-acp --model sonnet"

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--worker-acp-command",
                worker_cmd,
                "--validator-acp-command",
                shared_cmd,
                "--terminal-reviewer-acp-command",
                shared_cmd,
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text())
        mcp_env = mcp["mcpServers"]["zenith"]["env"]
        assert mcp_env["ZENITH_WORKER_ACP_COMMAND"] == worker_cmd
        assert mcp_env["ZENITH_VALIDATOR_ACP_COMMAND"] == shared_cmd
        # Fails before the fix — identical to the validator's, so dropped.
        assert mcp_env["ZENITH_TERMINAL_REVIEWER_ACP_COMMAND"] == shared_cmd

    def test_explicit_role_providers_survive_matching_parent(
        self, runner: CliRunner, workspace: Path, env: dict[str, str]
    ) -> None:
        """Same rule for the per-role provider flags, so the two stay
        consistent: naming the worker's own provider explicitly still
        records it."""
        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--validator-provider",
                "claude",
                "--terminal-reviewer-provider",
                "claude",
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text())
        mcp_env = mcp["mcpServers"]["zenith"]["env"]
        assert mcp_env["ZENITH_VALIDATOR_PROVIDER"] == "claude"
        assert mcp_env["ZENITH_TERMINAL_REVIEWER_PROVIDER"] == "claude"

    def test_generated_env_resolves_same_reviewer_command_at_dispatch(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Writing the explicit command changes the config, not dispatch.

        Both configs — the minimal one (reviewer inherited) and the explicit
        one — must resolve to the same command through `for_role`, proving
        the fix is additive rather than a behavior change.
        """
        worker_cmd = "claude-agent-acp --model opus"
        shared_cmd = "claude-agent-acp --model sonnet"

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--worker-acp-command",
                worker_cmd,
                "--validator-acp-command",
                shared_cmd,
                "--terminal-reviewer-acp-command",
                shared_cmd,
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text())
        mcp_env = mcp["mcpServers"]["zenith"]["env"]

        for key, value in mcp_env.items():
            monkeypatch.setenv(key, value)
        explicit = HarnessConfig.discover()

        # The pre-fix config: reviewer command omitted, inherited instead.
        monkeypatch.delenv("ZENITH_TERMINAL_REVIEWER_ACP_COMMAND")
        inherited = HarnessConfig.discover()

        assert (
            explicit.for_role("terminal_reviewer").worker_acp_command
            == inherited.for_role("terminal_reviewer").worker_acp_command
            == shared_cmd
        )

    def test_init_env_round_trips_without_shedding_keys(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A selection rebuilt from the generated env re-emits the same keys.

        `HarnessConfig.provider_selection` reconstructs a `ProviderSelection`
        from the env vars; every command it carries came from an explicit
        var, so none may be dropped on the way back out.
        """
        shared_cmd = "claude-agent-acp --model sonnet"
        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--worker-acp-command",
                "claude-agent-acp --model opus",
                "--validator-acp-command",
                shared_cmd,
                "--terminal-reviewer-acp-command",
                shared_cmd,
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text())
        mcp_env = mcp["mcpServers"]["zenith"]["env"]
        for key, value in mcp_env.items():
            monkeypatch.setenv(key, value)

        round_tripped = HarnessConfig.discover().provider_selection.env()
        assert round_tripped["ZENITH_TERMINAL_REVIEWER_ACP_COMMAND"] == shared_cmd
        assert round_tripped["ZENITH_VALIDATOR_ACP_COMMAND"] == shared_cmd

    def test_three_distinct_providers_all_env_written(
        self, runner: CliRunner, workspace: Path, env: dict[str, str]
    ) -> None:
        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--validator-provider",
                "codex",
                "--terminal-reviewer-provider",
                "hermes",
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text())
        mcp_env = mcp["mcpServers"]["zenith"]["env"]
        assert mcp_env["ZENITH_ORCHESTRATOR_PROVIDER"] == "claude"
        assert mcp_env["ZENITH_WORKER_PROVIDER"] == "claude"
        assert mcp_env["ZENITH_VALIDATOR_PROVIDER"] == "codex"
        assert mcp_env["ZENITH_TERMINAL_REVIEWER_PROVIDER"] == "hermes"
    @pytest.mark.parametrize("agent", ["claude", "codex", "hermes"])
    def test_explicit_project_scope_matches_default(
        self,
        runner: CliRunner,
        tmp_path: Path,
        env: dict[str, str],
        agent: str,
    ) -> None:
        default_workspace = tmp_path / "default"
        explicit_workspace = tmp_path / "explicit"
        default_workspace.mkdir()
        explicit_workspace.mkdir()

        default_result = runner.invoke(
            cli,
            ["init", "--workspace-dir", str(default_workspace), "--agent", agent],
        )
        explicit_result = runner.invoke(
            cli,
            [
                "init",
                "--scope",
                "project",
                "--workspace-dir",
                str(explicit_workspace),
                "--agent",
                agent,
            ],
        )
        assert default_result.exit_code == 0, default_result.output
        assert explicit_result.exit_code == 0, explicit_result.output

        def files(root: Path) -> dict[str, bytes]:
            return {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }

        assert files(default_workspace) == files(explicit_workspace)
        assert default_result.output.replace(str(default_workspace), "<workspace>") == (
            explicit_result.output.replace(str(explicit_workspace), "<workspace>")
        )


@pytest.fixture
def user_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    return home


class TestUserScopeInit:
    def test_claude_installs_user_config_and_assets_without_freezing_model(
        self,
        runner: CliRunner,
        workspace: Path,
        user_home: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config_path = user_home / ".claude.json"
        config_path.write_text(
            json.dumps(
                {
                    "theme": "dark",
                    "projects": {"/existing": {"allowedTools": ["Read"]}},
                    "mcpServers": {
                        "other": {"command": "other-server"},
                        "zenith": {"command": "old-zenith"},
                    },
                },
                indent=2,
            )
            + "\n"
        )
        monkeypatch.setenv("ANTHROPIC_MODEL", "must-not-be-persisted")
        monkeypatch.setenv("ZAI_API_KEY", "must-not-be-persisted")

        result = runner.invoke(cli, ["init", "--scope", "user", "--agent", "claude"])
        assert result.exit_code == 0, result.output

        config = json.loads(config_path.read_text())
        assert config["theme"] == "dark"
        assert config["projects"]["/existing"]["allowedTools"] == ["Read"]
        assert config["mcpServers"]["other"]["command"] == "other-server"
        server = config["mcpServers"]["zenith"]
        assert server["command"] == "uv"
        assert server["args"] == _expected_mcp_server_args()
        assert server["env"]["ZENITH_ORCHESTRATOR_PROVIDER"] == "claude"
        assert "ANTHROPIC_MODEL" not in server["env"]
        assert "ZAI_API_KEY" not in server["env"]

        claude_root = user_home / ".claude"
        assert (claude_root / "orchestrator_prompt.md").exists()
        assert (claude_root / "agents" / "investigator.md").exists()
        assert (claude_root / "skills" / "engineering-mission-playbook" / "SKILL.md").exists()
        skill = (claude_root / "skills" / "zenith" / "SKILL.md").read_text()
        assert "name: zenith" in skill
        assert str(claude_root / "orchestrator_prompt.md") in skill
        assert "Do not run workspace initialization" in skill
        assert not (workspace / ".mcp.json").exists()
        assert not (workspace / ".claude").exists()
        assert "Restart Claude Code or start a new session" in result.output

        first_config = config_path.read_bytes()
        first_skill = (claude_root / "skills" / "zenith" / "SKILL.md").read_bytes()
        rerun = runner.invoke(cli, ["init", "--scope", "user", "--agent", "claude"])
        assert rerun.exit_code == 0, rerun.output
        assert config_path.read_bytes() == first_config
        assert (claude_root / "skills" / "zenith" / "SKILL.md").read_bytes() == first_skill

    def test_claude_config_dir_override_and_invalid_config_are_safe(
        self,
        runner: CliRunner,
        user_home: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config_root = user_home / "custom claude"
        config_root.mkdir()
        config_path = config_root / ".claude.json"
        original = '{"mcpServers": []}\n'
        config_path.write_text(original)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_root))

        result = runner.invoke(cli, ["init", "--scope", "user", "--agent", "claude"])
        assert result.exit_code != 0
        assert "mcpServers must be an object" in result.output
        assert config_path.read_text() == original
        assert not (config_root / "skills").exists()
        assert not (config_root / "agents").exists()

        config_path.write_text("not json\n")
        malformed = runner.invoke(
            cli, ["init", "--scope", "user", "--agent", "claude"]
        )
        assert malformed.exit_code != 0
        assert config_path.read_text() == "not json\n"
        assert not (config_root / "skills").exists()

        config_path.write_text('{"theme": "light"}\n')
        success = runner.invoke(cli, ["init", "--scope", "user", "--agent", "claude"])
        assert success.exit_code == 0, success.output
        config = json.loads(config_path.read_text())
        assert config["theme"] == "light"
        assert config["mcpServers"]["zenith"]["command"] == "uv"
        assert (config_root / "skills" / "zenith" / "SKILL.md").exists()
        assert (config_root / "agents" / "investigator.md").exists()

    def test_codex_preserves_preferences_and_adopts_existing_server(
        self,
        runner: CliRunner,
        workspace: Path,
        user_home: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        codex_root = user_home / "custom codex"
        codex_root.mkdir()
        monkeypatch.setenv("CODEX_HOME", str(codex_root))
        monkeypatch.setenv("ANTHROPIC_MODEL", "must-not-be-persisted")
        config_path = codex_root / "config.toml"
        config_path.write_text(
            'model = "user-model"\n'
            'model_reasoning_effort = "low"\n'
            'sandbox_mode = "workspace-write"\n'
            "\n"
            "[features]\n"
            "memories = false\n"
            "\n"
            "[mcp_servers.other]\n"
            'command = "other-server"\n'
            "\n"
            "[mcp_servers.zenith]\n"
            'command = "old-zenith"\n'
            "\n"
            "[mcp_servers.zenith.env]\n"
            'OLD = "value"\n'
        )
        sibling_skill = codex_root / "skills" / "personal" / "SKILL.md"
        sibling_skill.parent.mkdir(parents=True)
        sibling_skill.write_text("personal skill\n")
        sibling_agent = codex_root / "agents" / "personal.toml"
        sibling_agent.parent.mkdir(parents=True)
        sibling_agent.write_text('name = "personal"\n')

        custom_home = user_home / 'state with "quotes" and ünicode'
        result = runner.invoke(
            cli,
            [
                "init",
                "--scope",
                "user",
                "--agent",
                "codex",
                "--zenith-home",
                str(custom_home),
            ],
        )
        assert result.exit_code == 0, result.output

        text = config_path.read_text()
        config = tomllib.loads(text)
        assert config["model"] == "user-model"
        assert config["model_reasoning_effort"] == "low"
        assert config["sandbox_mode"] == "workspace-write"
        assert config["features"]["memories"] is False
        assert config["mcp_servers"]["other"]["command"] == "other-server"
        server = config["mcp_servers"]["zenith"]
        assert server["command"] == "uv"
        assert server["args"] == _expected_mcp_server_args()
        assert server["env"]["ZENITH_HOME"] == str(custom_home.resolve())
        assert "ANTHROPIC_MODEL" not in server["env"]
        assert text.count("[mcp_servers.zenith]") == 1
        assert text.count("[mcp_servers.zenith.env]") == 1
        assert 'model = "gpt-5.5"' not in text
        assert 'model_reasoning_effort = "xhigh"' not in text

        assert (codex_root / "orchestrator_prompt.md").exists()
        assert (codex_root / "agents" / "investigator.toml").exists()
        skill_path = codex_root / "skills" / "zenith" / "SKILL.md"
        assert str(codex_root / "orchestrator_prompt.md") in skill_path.read_text()
        assert not (workspace / ".codex").exists()
        assert sibling_skill.read_text() == "personal skill\n"
        assert sibling_agent.read_text() == 'name = "personal"\n'

        first = config_path.read_bytes()
        rerun = runner.invoke(
            cli,
            [
                "init",
                "--scope",
                "user",
                "--agent",
                "codex",
                "--zenith-home",
                str(custom_home),
            ],
        )
        assert rerun.exit_code == 0, rerun.output
        assert config_path.read_bytes() == first

    def test_codex_replaces_valid_managed_block_by_line_and_preserves_mode(
        self,
        runner: CliRunner,
        user_home: Path,
        env: dict[str, str],
    ) -> None:
        codex_root = user_home / ".codex"
        codex_root.mkdir()
        config_path = codex_root / "config.toml"
        config_path.write_text(
            'model = "user-model"\n'
            "\n"
            "[features]\n"
            "memories = false\n"
            "\n"
            "  # BEGIN zenith  \n"
            "[mcp_servers.zenith]\n"
            'command = "old-zenith"\n'
            "\n"
            "[mcp_servers.zenith.env]\n"
            'OLD = "value"\n'
            "\t# END zenith\t\n"
            "\n"
            "[mcp_servers.after]\n"
            'command = "after"\n'
        )
        config_path.chmod(0o640)

        result = runner.invoke(cli, ["init", "--scope", "user", "--agent", "codex"])
        assert result.exit_code == 0, result.output
        first = config_path.read_bytes()
        config = tomllib.loads(first.decode())
        assert config["model"] == "user-model"
        assert config["features"]["memories"] is False
        assert config["mcp_servers"]["zenith"]["command"] == "uv"
        assert config["mcp_servers"]["after"]["command"] == "after"
        assert first.count(b"# BEGIN zenith") == 1
        assert first.count(b"# END zenith") == 1
        assert stat.S_IMODE(config_path.stat().st_mode) == 0o640

        rerun = runner.invoke(cli, ["init", "--scope", "user", "--agent", "codex"])
        assert rerun.exit_code == 0, rerun.output
        assert config_path.read_bytes() == first
        assert stat.S_IMODE(config_path.stat().st_mode) == 0o640

    @pytest.mark.parametrize(
        "zenith_header, env_header",
        [
            ('[mcp_servers."zenith"]', '[mcp_servers."zenith".env]'),
            ("[mcp_servers.zenith] # old server", "[mcp_servers.zenith.env] # old env"),
        ],
    )
    def test_codex_adopts_equivalent_unmanaged_zenith_tables(
        self,
        runner: CliRunner,
        user_home: Path,
        env: dict[str, str],
        zenith_header: str,
        env_header: str,
    ) -> None:
        codex_root = user_home / ".codex"
        codex_root.mkdir()
        config_path = codex_root / "config.toml"
        config_path.write_text(
            'title = "contains # BEGIN zenith but is not a boundary"\n'
            "# # END zenith is part of a longer comment\n\n"
            '[mcp_servers.before]\ncommand = "before"\n\n'
            'marker_text = "prefix # END zenith suffix"\n\n'
            f'{zenith_header}\ncommand = "old"\n\n'
            f'{env_header}\nOLD = "value"\n\n'
            '[mcp_servers.after]\ncommand = "after"\n'
        )
        config_path.chmod(0o600)

        result = runner.invoke(cli, ["init", "--scope", "user", "--agent", "codex"])
        assert result.exit_code == 0, result.output
        text = config_path.read_text()
        config = tomllib.loads(text)
        assert config["title"] == "contains # BEGIN zenith but is not a boundary"
        assert config["mcp_servers"]["before"]["command"] == "before"
        assert config["mcp_servers"]["before"]["marker_text"] == "prefix # END zenith suffix"
        assert config["mcp_servers"]["after"]["command"] == "after"
        assert config["mcp_servers"]["zenith"]["command"] == "uv"
        assert text.count("[mcp_servers.zenith]") == 1
        assert "# # END zenith is part of a longer comment" in text
        assert stat.S_IMODE(config_path.stat().st_mode) == 0o600

        first = config_path.read_bytes()
        rerun = runner.invoke(cli, ["init", "--scope", "user", "--agent", "codex"])
        assert rerun.exit_code == 0, rerun.output
        assert config_path.read_bytes() == first
        assert stat.S_IMODE(config_path.stat().st_mode) == 0o600

    def test_codex_invalid_toml_does_not_mutate_assets(
        self,
        runner: CliRunner,
        user_home: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        codex_root = user_home / ".codex"
        codex_root.mkdir()
        config_path = codex_root / "config.toml"
        content = "not = [valid\n"
        config_path.write_text(content)
        monkeypatch.setenv("CODEX_HOME", str(codex_root))

        result = runner.invoke(cli, ["init", "--scope", "user", "--agent", "codex"])
        assert result.exit_code != 0
        assert "invalid Codex config" in result.output
        assert config_path.read_text() == content
        assert not (codex_root / "skills").exists()
        assert not (codex_root / "agents").exists()

    @pytest.mark.parametrize(
        "markers",
        [
            pytest.param(("# BEGIN zenith",), id="begin-only"),
            pytest.param(("# END zenith",), id="end-only"),
            pytest.param(("# END zenith", "# BEGIN zenith"), id="reversed"),
            pytest.param(
                ("# BEGIN zenith", "# BEGIN zenith", "# END zenith"),
                id="duplicate-begin",
            ),
            pytest.param(
                ("# BEGIN zenith", "# END zenith", "# END zenith"),
                id="duplicate-end",
            ),
            pytest.param(
                ("# BEGIN zenith", "# END zenith", "# BEGIN zenith", "# END zenith"),
                id="two-blocks",
            ),
            pytest.param(
                ("# BEGIN zenith", "# BEGIN zenith", "# END zenith", "# END zenith"),
                id="nested",
            ),
            pytest.param(
                (
                    "# BEGIN zenith",
                    "# BEGIN zenith",
                    "# END zenith",
                    "# BEGIN zenith",
                    "# END zenith",
                    "# END zenith",
                ),
                id="overlapping",
            ),
        ],
    )
    def test_codex_rejects_malformed_managed_blocks_without_user_tree_mutation(
        self,
        runner: CliRunner,
        user_home: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
        markers: tuple[str, ...],
    ) -> None:
        codex_root = user_home / ".codex"
        codex_root.mkdir()
        config_path = codex_root / "config.toml"
        content = 'theme = "dark"\n' + "\n".join(markers) + "\n# keep me\n"
        config_path.write_text(content)
        config_path.chmod(0o640)
        monkeypatch.setenv("CODEX_HOME", str(codex_root))
        existing_agent = codex_root / "agents" / "personal.toml"
        existing_agent.parent.mkdir()
        existing_agent.write_text('name = "personal"\n')
        existing_skill = codex_root / "skills" / "personal" / "SKILL.md"
        existing_skill.parent.mkdir(parents=True)
        existing_skill.write_text("personal skill\n")
        shared_skill = user_home / ".agents" / "skills" / "personal" / "SKILL.md"
        shared_skill.parent.mkdir(parents=True)
        shared_skill.write_text("shared personal skill\n")
        before = _tree_snapshot(user_home)

        result = runner.invoke(cli, ["init", "--scope", "user", "--agent", "codex"])
        assert result.exit_code != 0
        assert "malformed Zenith managed block" in result.output
        assert _tree_snapshot(user_home) == before

    @pytest.mark.parametrize("order", [("claude", "codex"), ("codex", "claude")])
    def test_claude_and_codex_user_installs_coexist(
        self,
        runner: CliRunner,
        user_home: Path,
        env: dict[str, str],
        order: tuple[str, str],
    ) -> None:
        first = runner.invoke(cli, ["init", "--scope", "user", "--agent", order[0]])
        assert first.exit_code == 0, first.output
        shared_root = user_home / ".agents" / "skills"
        shared_before = {
            str(path.relative_to(shared_root)): path.read_bytes()
            for path in shared_root.rglob("*")
            if path.is_file()
        }

        for agent in order[1:]:
            result = runner.invoke(cli, ["init", "--scope", "user", "--agent", agent])
            assert result.exit_code == 0, result.output

        claude = json.loads((user_home / ".claude.json").read_text())
        codex = tomllib.loads((user_home / ".codex" / "config.toml").read_text())
        assert claude["mcpServers"]["zenith"]["env"]["ZENITH_WORKER_PROVIDER"] == "claude"
        assert codex["mcp_servers"]["zenith"]["env"]["ZENITH_WORKER_PROVIDER"] == "codex"
        assert (user_home / ".claude" / "skills" / "zenith" / "SKILL.md").exists()
        assert (user_home / ".codex" / "skills" / "zenith" / "SKILL.md").exists()
        assert (user_home / ".agents" / "skills" / "scrutiny-validator" / "SKILL.md").exists()
        shared_after = {
            str(path.relative_to(shared_root)): path.read_bytes()
            for path in shared_root.rglob("*")
            if path.is_file()
        }
        assert shared_after == shared_before

    def test_user_scope_argument_errors_happen_before_writes(
        self,
        runner: CliRunner,
        workspace: Path,
        user_home: Path,
        env: dict[str, str],
    ) -> None:
        conflicting = runner.invoke(
            cli,
            [
                "init",
                "--scope",
                "user",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "codex",
            ],
        )
        assert conflicting.exit_code != 0
        assert "--workspace-dir cannot be used with --scope user" in conflicting.output

        unsupported = runner.invoke(
            cli, ["init", "--scope", "user", "--agent", "hermes"]
        )
        assert unsupported.exit_code != 0
        assert "use --scope project for hermes" in unsupported.output
        assert list(user_home.iterdir()) == []

    @pytest.mark.parametrize(
        ("flag", "value"),
        [
            ("--worker-reasoning-effort", "high"),
            ("--validator-model", "gpt-5.5"),
            ("--log-level", "DEBUG"),
            ("--log-file", "zenith.log"),
        ],
    )
    def test_user_scope_rejects_flags_it_would_not_persist(
        self,
        runner: CliRunner,
        user_home: Path,
        env: dict[str, str],
        flag: str,
        value: str,
    ) -> None:
        # These flags only ever reach the config through cli_env, which user
        # scope does not write. Silently accepting one would report success
        # while the setting vanished, so init must refuse before writing.
        result = runner.invoke(
            cli, ["init", "--scope", "user", "--agent", "codex", flag, value]
        )
        assert result.exit_code != 0
        assert f"{flag} cannot be used with --scope user" in result.output
        assert list(user_home.iterdir()) == []

    def test_registered_command_launches_from_another_workspace(
        self,
        runner: CliRunner,
        user_home: Path,
        env: dict[str, str],
        tmp_path: Path,
    ) -> None:
        result = runner.invoke(cli, ["init", "--scope", "user", "--agent", "codex"])
        assert result.exit_code == 0, result.output
        config = tomllib.loads((user_home / ".codex" / "config.toml").read_text())
        server = config["mcp_servers"]["zenith"]
        unrelated = tmp_path / "unrelated workspace"
        unrelated.mkdir()

        launched = subprocess.run(
            [server["command"], *server["args"], "--help"],
            cwd=unrelated,
            env={**os.environ, **server["env"]},
            text=True,
            capture_output=True,
            check=False,
        )
        assert launched.returncode == 0, launched.stderr
        assert "Zenith MCP Server" in launched.stdout
        assert not (unrelated / ".codex").exists()
        assert not (unrelated / ".zenith").exists()


class TestListProjects:
    def test_empty(self, runner: CliRunner, env: dict[str, str]) -> None:
        r = runner.invoke(cli, ["list-projects"])
        assert r.exit_code == 0
        assert "No projects" in r.output

    def test_after_creation(
        self, runner: CliRunner, workspace: Path, harness_home: Path, env: dict[str, str]
    ) -> None:
        from zenith_harness.config import HarnessConfig
        from zenith_harness.storage import ProjectStore

        ProjectStore(HarnessConfig.discover()).create_project(
            "brief", workspace, project_id="proj-x"
        )
        r = runner.invoke(cli, ["list-projects"])
        assert "proj-x" in r.output


class TestShowProject:
    def test_unknown_id(self, runner: CliRunner, env: dict[str, str]) -> None:
        r = runner.invoke(cli, ["show-project", "ghost"])
        assert r.exit_code != 0
        assert "not found" in r.output.lower()
