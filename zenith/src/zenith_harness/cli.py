from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import tomllib
from pathlib import Path

import click

from .assets import AssetLoader, iter_skill_directories
from .config import VALID_REASONING_EFFORTS, HarnessConfig, validate_model_id
from .envelope import render_task_list
from .providers import (
    ProviderDefinition,
    ProviderSelection,
    default_worker_provider_name,
    get_provider,
    provider_names_for_role,
)
from .storage import ProjectStore

# UI validation only — server-side _configure_logging falls back to WARNING on
# anything getattr(logging, ...) does not know.
VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

RUNTIME_ENV_FORWARD_ALLOWLIST = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
    "CLAUDE_CODE_EFFORT_LEVEL",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS",
    "CLAUDE_CODE_SUBAGENT_MODEL",
    "GLM_API_KEY",
    "GLM_BASE_URL",
    "MAX_THINKING_TOKENS",
    "ZENITH_LOG_LEVEL",
    "ZENITH_LOG_FILE",
    "ZENITH_WORKER_REASONING_EFFORT",
    "ZENITH_VALIDATOR_REASONING_EFFORT",
    "ZENITH_TERMINAL_REVIEWER_REASONING_EFFORT",
    # Deliberately absent: ZENITH_{WORKER,VALIDATOR,TERMINAL_REVIEWER}_MODEL.
    # See the model_env comment in `init` — an ambient model pin carries no
    # record of the provider it was chosen for, so forwarding it into a
    # workspace config lands it on whatever provider that workspace uses.
    "ZAI_API_KEY",
    "ZAI_BASE_URL",
)

USER_SCOPE_ORCHESTRATORS = ("claude", "codex")


def _validate_model_flag(ctx, param, value):
    """Click callback for the --*-model flags.

    The env vars are validated at `discover()`; flags need the same check but
    reported as a usage error against the option the user actually typed. An
    explicit empty string is rejected rather than dropped, because it reads as
    "run this lane unpinned" and does not do that: a same-provider lane still
    inherits the pin above it, and there is no flag that expresses "unpinned".
    Refusing is honest; silently accepting a no-op would not be.
    """
    if value is None:
        return None
    if not value:
        raise click.BadParameter("model pin cannot be empty", ctx=ctx, param=param)
    try:
        return validate_model_id(value, env_var=param.name)
    except ValueError:
        raise click.BadParameter(
            f"{value!r} is not a valid model identifier; "
            "allowed characters are letters, digits, and ._:/@[]-",
            ctx=ctx,
            param=param,
        ) from None


@click.group()
def cli() -> None:
    """Zenith CLI — set up + inspect long-running coding projects."""


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--agent",
    type=click.Choice(provider_names_for_role("orchestrator")),
    default=None,
    help="Convenience: sets orchestrator+worker provider in one shot.",
)
@click.option(
    "--orchestrator-provider",
    type=click.Choice(provider_names_for_role("orchestrator")),
    default=None,
)
@click.option(
    "--worker-provider",
    type=click.Choice(provider_names_for_role("worker")),
    default=None,
)
@click.option("--worker-acp-command", default=None)
@click.option("--validator-provider", type=click.Choice(provider_names_for_role("worker")), default=None)
@click.option("--validator-acp-command", default=None)
@click.option("--terminal-reviewer-provider", type=click.Choice(provider_names_for_role("worker")), default=None)
@click.option("--terminal-reviewer-acp-command", default=None)
@click.option("--worker-reasoning-effort", type=click.Choice(VALID_REASONING_EFFORTS), default=None)
@click.option("--validator-reasoning-effort", type=click.Choice(VALID_REASONING_EFFORTS), default=None)
@click.option("--terminal-reviewer-reasoning-effort", type=click.Choice(VALID_REASONING_EFFORTS), default=None)
@click.option("--worker-model", default=None, callback=_validate_model_flag,
              help="Model pin for worker lanes (e.g. opus, gpt-5.5).")
@click.option("--validator-model", default=None, callback=_validate_model_flag,
              help="Model pin for the validation gate; falls back to the worker pin.")
@click.option("--terminal-reviewer-model", default=None, callback=_validate_model_flag,
              help="Model pin for terminal review; falls back to the validator pin.")
@click.option(
    "--log-level",
    type=click.Choice(VALID_LOG_LEVELS, case_sensitive=False),
    default=None,
    help="Persist ZENITH_LOG_LEVEL into the generated server config.",
)
@click.option(
    "--log-file",
    type=click.Path(),
    default=None,
    help="Persist ZENITH_LOG_FILE (durable Zenith log path) into the generated server config.",
)
@click.option("--zenith-home", type=click.Path(), default=None)
@click.option(
    "--scope",
    type=click.Choice(("project", "user")),
    default="project",
    show_default=True,
    help="Install into one project or the current user's host configuration.",
)
@click.option("--workspace-dir", "workspace_dir", type=click.Path(exists=True), default=None)
def init(
    agent: str | None,
    orchestrator_provider: str | None,
    worker_provider: str | None,
    worker_acp_command: str | None,
    validator_provider: str | None,
    validator_acp_command: str | None,
    terminal_reviewer_provider: str | None,
    terminal_reviewer_acp_command: str | None,
    worker_reasoning_effort: str | None,
    validator_reasoning_effort: str | None,
    terminal_reviewer_reasoning_effort: str | None,
    worker_model: str | None,
    validator_model: str | None,
    terminal_reviewer_model: str | None,
    log_level: str | None,
    log_file: str | None,
    zenith_home: str | None,
    scope: str,
    workspace_dir: str | None,
) -> None:
    """Initialize Zenith's host-agent surface.

    Project scope (the default) stages MCP config and assets in one workspace.
    User scope registers Zenith and installs its assets once for every workspace
    in Claude Code or Codex. In both scopes, the project bucket is created lazily
    by `start_project` at the first MCP call.
    """
    # discover() validates the ambient ZENITH_* settings. Its ValueError is a
    # user-facing complaint about the caller's environment, not a harness
    # fault, so it gets the same treatment as a bad flag rather than a
    # traceback.
    #
    # A model pin that a flag replaces is exempt. Ambient pins are never
    # written (see model_env below), so a broken one still deserves to stop
    # init — it would reach a server launched from this same shell. But once a
    # flag supplies that role's pin, the written config overrides the ambient
    # value for every server this workspace starts, and failing on it would
    # block an init that already ignores it. Restored immediately: the
    # environment belongs to the caller.
    shadowed = {
        var: os.environ.pop(var)
        for var, flag_value in (
            ("ZENITH_WORKER_MODEL", worker_model),
            ("ZENITH_VALIDATOR_MODEL", validator_model),
            ("ZENITH_TERMINAL_REVIEWER_MODEL", terminal_reviewer_model),
        )
        if flag_value and var in os.environ
    }
    try:
        config = HarnessConfig.discover()
    except ValueError as exc:
        raise click.UsageError(str(exc)) from None
    finally:
        os.environ.update(shadowed)
    loader = AssetLoader(config)
    selection = _resolve_selection(
        agent=agent,
        orchestrator=orchestrator_provider,
        worker=worker_provider,
        worker_acp_command=worker_acp_command,
        validator=validator_provider,
        validator_acp_command=validator_acp_command,
        terminal_reviewer=terminal_reviewer_provider,
        terminal_reviewer_acp_command=terminal_reviewer_acp_command,
    )

    if scope == "user":
        if workspace_dir is not None:
            raise click.UsageError("--workspace-dir cannot be used with --scope user")
        if selection.orchestrator.name not in USER_SCOPE_ORCHESTRATORS:
            supported = ", ".join(USER_SCOPE_ORCHESTRATORS)
            raise click.UsageError(
                f"--scope user supports these orchestrators: {supported}; "
                f"use --scope project for {selection.orchestrator.name}"
            )
        # User scope writes only the provider selection and storage paths — it
        # deliberately persists no model, no reasoning effort, and no ambient
        # runtime env, so a host config installed once cannot freeze settings
        # for every workspace. The flags below feed exactly that omitted set
        # (see cli_env in the project branch), so accepting them here would
        # take a flag and write nothing. Refuse instead of dropping silently.
        ignored = [
            flag
            for flag, value in (
                ("--worker-reasoning-effort", worker_reasoning_effort),
                ("--validator-reasoning-effort", validator_reasoning_effort),
                ("--terminal-reviewer-reasoning-effort", terminal_reviewer_reasoning_effort),
                ("--worker-model", worker_model),
                ("--validator-model", validator_model),
                ("--terminal-reviewer-model", terminal_reviewer_model),
                ("--log-level", log_level),
                ("--log-file", log_file),
            )
            if value
        ]
        if ignored:
            raise click.UsageError(
                f"{', '.join(ignored)} cannot be used with --scope user; "
                "user scope persists no model, reasoning effort, or logging "
                "setting — pass these per workspace with --scope project, or "
                "export the matching ZENITH_* variable for the host session"
            )
        storage_env = _storage_env(
            zenith_home=zenith_home,
            workspace=Path.cwd(),
            selection=selection,
        )
        _write_user_bootstrap_config(selection, storage_env)
        _setup_user_provider_assets(loader, selection.orchestrator)
        _echo_user_next_steps(selection)
        return

    workspace = Path(workspace_dir or ".").resolve()

    # 1) MCP / Codex config
    storage_env = _storage_env(zenith_home=zenith_home, workspace=workspace, selection=selection)
    # Flags are sugar for the corresponding ZENITH_* env vars and win over
    # valid inherited shell settings. An invalid effort value already in the
    # environment still fails fast at discover() above — flags override
    # settings, they don't mask broken ones (the same validation would raise
    # at server launch anyway).
    effort_env = {
        var: value
        for var, value in (
            ("ZENITH_WORKER_REASONING_EFFORT", worker_reasoning_effort),
            ("ZENITH_VALIDATOR_REASONING_EFFORT", validator_reasoning_effort),
            ("ZENITH_TERMINAL_REVIEWER_REASONING_EFFORT", terminal_reviewer_reasoning_effort),
        )
        if value
    }
    # Observability flags, kept in their own dict rather than folded into
    # effort_env: they are process-wide settings rather than per-role ones, and
    # keeping them separate leaves effort_env identical to upstream's.
    log_env = {
        var: value
        for var, value in (
            ("ZENITH_LOG_LEVEL", log_level.upper() if log_level else None),
            (
                "ZENITH_LOG_FILE",
                str(Path(log_file).expanduser().resolve()) if log_file else None,
            ),
        )
        if value
    }
    # Model pins take the flags but NOT the ambient env, which is where they
    # part company with the reasoning efforts above. An effort is
    # provider-neutral vocabulary, so forwarding an inherited one into the
    # workspace is safe. A model id is not: an ambient ZENITH_WORKER_MODEL
    # arrives with no record of which provider it was chosen for, so baking it
    # into this workspace lands a leftover `gpt-5.5-codex` on a claude lane as
    # ANTHROPIC_MODEL — the exact cross-provider landing `_inherited_model`
    # refuses to make inside a single config. Pins therefore enter a workspace
    # only through the flags, checked below against the provider resolved for
    # that lane. An ambient ZENITH_*_MODEL still reaches a server the user
    # launches from that same shell; init just does not make it durable.
    #
    # ANTHROPIC_MODEL is the exception, and it is deliberate: it is a
    # provider-scoped variable rather than a lane-scoped one, it is the
    # documented way to pin claude globally, and it stays in the forward
    # allowlist above. So a workspace inited from a shell that exported it does
    # carry it, and an "unpinned" claude lane runs on it — see the note on
    # HarnessConfig.worker_model.
    #
    # Click has no Choice to validate an open-ended model id against, so the
    # flags carry _validate_model_flag, which applies the same check discover()
    # applies to the env vars.
    model_env = {
        var: value
        for var, value in (
            ("ZENITH_WORKER_MODEL", worker_model),
            ("ZENITH_VALIDATOR_MODEL", validator_model),
            ("ZENITH_TERMINAL_REVIEWER_MODEL", terminal_reviewer_model),
        )
        if value
    }
    # Resolve every role the way the server will, then stage what was
    # resolved. These vars are not in RUNTIME_ENV_FORWARD_ALLOWLIST and
    # ProviderSelection.env() emits a role provider only when it differs from
    # the worker, so an ambient ZENITH_VALIDATOR_PROVIDER used to inform init's
    # diagnostics while never reaching the config init wrote. The two answers
    # could then disagree in both directions: a warning about a hermes
    # validator whose written config said claude, and silence in the mirror
    # case. Writing the resolved value closes that gap — the host agent is
    # usually launched later, from a different shell, and reads only what is
    # written here.
    #
    # Precedence per role: explicit flag, then the ambient var, then inherit
    # down the chain (worker -> validator -> terminal reviewer). The flag wins
    # so an explicit `--validator-provider claude` is never overruled by a
    # stale export.
    def _ambient(var: str) -> str | None:
        return os.environ.get(var) or None

    def _pick(*candidates: tuple[str | None, str]) -> tuple[str, str]:
        """First candidate with a value, paired with where it came from."""
        for value, source in candidates:
            if value:
                return value, source
        raise AssertionError("the final candidate must always carry a value")

    # The worker is the exception: it is the only role with a default of its
    # own (`--agent`, then default_worker_provider_name), and ProviderSelection
    # has always written ZENITH_WORKER_PROVIDER unconditionally. Init therefore
    # sets the worker rather than inheriting it, and an ambient
    # ZENITH_WORKER_PROVIDER does not survive `zenith init`. The other two
    # roles have no default but the lane above them, which is why they consult
    # the environment.
    worker_provider_name, worker_source = selection.worker.name, "--worker-provider"
    validator_provider_name, validator_source = _pick(
        (validator_provider, "--validator-provider"),
        (_ambient("ZENITH_VALIDATOR_PROVIDER"), "ZENITH_VALIDATOR_PROVIDER"),
        (worker_provider_name, worker_source),
    )
    terminal_reviewer_provider_name, terminal_source = _pick(
        (terminal_reviewer_provider, "--terminal-reviewer-provider"),
        (_ambient("ZENITH_TERMINAL_REVIEWER_PROVIDER"), "ZENITH_TERMINAL_REVIEWER_PROVIDER"),
        (validator_provider_name, validator_source),
    )

    # An ACP command names a binary, so it is the most provider-specific value
    # in the config — more so than a model id. It is therefore taken from the
    # environment only for a lane whose *provider* also came from the
    # environment, so the pair stays together. Take one without the other and
    # init manufactures the mismatch it warns about below: with
    # `ZENITH_WORKER_PROVIDER=codex ZENITH_WORKER_ACP_COMMAND=codex-acp` in the
    # shell, `zenith init --agent claude` sets the worker provider itself (see
    # above) and would otherwise pair claude with codex-acp — permanently, and
    # in the config it just wrote. A lane whose provider init chose gets its
    # command from the flag or from that provider's default, never from a
    # shell that was talking about some other provider.
    #
    # Honoring the paired case still fixes the original defect: an exported
    # ZENITH_VALIDATOR_ACP_COMMAND used to inform nothing and never be written,
    # so the lane silently fell back to the worker's command at runtime.
    def _role_command(
        flag_value: str | None, var: str, provider_source: str
    ) -> str | None:
        if flag_value:
            return flag_value
        return _ambient(var) if provider_source == var.replace("_ACP_COMMAND", "_PROVIDER") else None

    role_command = {
        var: value
        for var, value in (
            (
                "ZENITH_WORKER_ACP_COMMAND",
                _role_command(worker_acp_command, "ZENITH_WORKER_ACP_COMMAND", worker_source),
            ),
            (
                "ZENITH_VALIDATOR_ACP_COMMAND",
                _role_command(
                    validator_acp_command, "ZENITH_VALIDATOR_ACP_COMMAND", validator_source
                ),
            ),
            (
                "ZENITH_TERMINAL_REVIEWER_ACP_COMMAND",
                _role_command(
                    terminal_reviewer_acp_command,
                    "ZENITH_TERMINAL_REVIEWER_ACP_COMMAND",
                    terminal_source,
                ),
            ),
        )
        if value
    }
    role_env = {
        "ZENITH_VALIDATOR_PROVIDER": validator_provider_name,
        "ZENITH_TERMINAL_REVIEWER_PROVIDER": terminal_reviewer_provider_name,
        **role_command,
    }
    # `_write_bootstrap_config` layers cli_env over `ProviderSelection.env()`,
    # so these resolved values supersede what env() emits for the same keys.
    # env() already writes every *explicitly set* role provider and command
    # (see providers.py — an inherited value is suppressed, a typed one is
    # not), and for a flag-set lane both sides agree by construction. What is
    # added here is the lane resolved from the ambient environment, which env()
    # cannot see at all.
    cli_env = {**effort_env, **model_env, **role_env, **log_env}

    # Resolved before anything is written: the flags carry a click.Choice, but
    # an ambient ZENITH_*_PROVIDER does not, and these names are dereferenced
    # late — the terminal one at asset install, the validator one not until the
    # first validate dispatch mid-mission. A typo should stop init, blamed on
    # whatever actually supplied it. A flag that beat the ambient var means the
    # ambient typo never reaches this check, which is the point.
    def _resolve_provider(name: str, source: str):
        try:
            return get_provider(name)
        except ValueError as exc:
            raise click.UsageError(f"{exc} (from {source})") from None

    validator_provider_def = _resolve_provider(validator_provider_name, validator_source)
    terminal_reviewer_provider_def = _resolve_provider(
        terminal_reviewer_provider_name, terminal_source
    )

    def _runs_provider_binary(command: str, provider_def: ProviderDefinition) -> bool:
        """Whether `command` looks like it launches `provider_def`'s own agent.

        Compares the executable — first token, basename only — so an absolute
        path or added arguments (`/usr/local/bin/codex-acp`, `codex-acp
        --verbose`) still reads as codex. Wrong only when a command genuinely
        runs a different binary, which is the case worth a warning.
        """
        default = provider_def.default_worker_acp_command
        if not default:
            return False
        return Path(command.split()[0]).name == Path(default.split()[0]).name

    # Two independent hazards, reported independently: a hermes lane cannot act
    # on a pin at all, and a lane whose command runs somebody else's binary
    # will not get the provider-specific treatment the harness applies for the
    # provider it thinks it has. The command hazard is NOT conditioned on a
    # pin — dispatch keys on provider.name for sandbox flags, the codex config
    # flags and the ACP session mode too, so it is a hazard on its own.
    for role, flag, pin, provider_def, command_var in (
        ("worker", "--worker-model", worker_model, selection.worker, "ZENITH_WORKER_ACP_COMMAND"),
        (
            "validator",
            "--validator-model",
            validator_model,
            validator_provider_def,
            "ZENITH_VALIDATOR_ACP_COMMAND",
        ),
        (
            "terminal reviewer",
            "--terminal-reviewer-model",
            terminal_reviewer_model,
            terminal_reviewer_provider_def,
            "ZENITH_TERMINAL_REVIEWER_ACP_COMMAND",
        ),
    ):
        # The pins come from the flags only (see model_env), so the flag name
        # is always the right thing to name here.
        if pin and provider_def.name == "hermes":
            click.echo(
                f"Warning: {flag} is ignored for provider {provider_def.name} — "
                "it exposes no model selection."
            )
        command = role_command.get(command_var)
        if command and not _runs_provider_binary(command, provider_def):
            click.echo(
                f"Warning: the {role} lane dispatches as provider "
                f"{provider_def.name} but launches {command} — sandbox flags, "
                "model pins and the ACP session mode are all applied the way "
                f"{provider_def.name} expects, and will be wrong if that "
                "command runs a different agent."
            )

    _write_bootstrap_config(workspace, selection, storage_env, cli_env)

    # 2) Per-provider agents + orchestrator prompt. ProviderSelection knows
    #    only the flags, so both roles that can be resolved from the
    #    environment are added here. Skipping either installs a workspace whose
    #    config names a provider that has no agents or skills on disk — a
    #    validator resolved from an ambient ZENITH_VALIDATOR_PROVIDER used to
    #    get assets only by accident, when the reviewer happened to inherit it.
    asset_providers = list(selection.providers())
    for provider_def in (validator_provider_def, terminal_reviewer_provider_def):
        if provider_def.name not in {p.name for p in asset_providers}:
            asset_providers.append(provider_def)
    for provider in asset_providers:
        _setup_provider_assets(workspace, loader, provider)

    click.echo(
        f"\nInitialized v5 project workspace at {workspace}: "
        f"orchestrator={selection.orchestrator.name}, "
        f"worker={worker_provider_name}, "
        # The resolved names, not selection's flag-only view — otherwise the
        # summary contradicts the config written one line earlier whenever a
        # role came from the environment.
        f"validator={validator_provider_name}, "
        f"terminal-reviewer={terminal_reviewer_provider_name}."
    )
    click.echo(
        "Bucket lives at $ZENITH_HOME/projects/<pid>/ — created on the first "
        "`start_project(brief, workspace_dir)` call."
    )
    _echo_next_steps(selection.orchestrator)


# ---------------------------------------------------------------------------
# install-skills
# ---------------------------------------------------------------------------


@cli.command("install-skills")
@click.option("--target", type=click.Path(), required=True)
def install_skills_cmd(target: str) -> None:
    """Install bundled skills to a target directory (e.g. <ws>/.zenith/skills/)."""
    config = HarnessConfig.discover()
    loader = AssetLoader(config)
    _copy_skills(loader, Path(target).resolve())
    click.echo(f"Installed bundled skills to {target}")


# ---------------------------------------------------------------------------
# list-projects
# ---------------------------------------------------------------------------


@cli.command("list-projects")
def list_projects_cmd() -> None:
    """List all projects in HARNESS bucket."""
    store = ProjectStore(HarnessConfig.discover())
    projects = store.list_projects()
    if not projects:
        click.echo("No projects.")
        return
    for p in projects:
        click.echo(f"  {p.id}   ws={p.workspace_dir}   created={p.created_at}")


# ---------------------------------------------------------------------------
# show-project
# ---------------------------------------------------------------------------


@cli.command("show-project")
@click.argument("project_id")
def show_project_cmd(project_id: str) -> None:
    """Show envelope + compact task list for a project."""
    store = ProjectStore(HarnessConfig.discover())
    try:
        record = store.load_project(project_id)
    except FileNotFoundError:
        raise click.ClickException(f"Project not found: {project_id}")
    state = store.load_state(project_id)
    click.echo(f"id:        {record.id}")
    click.echo(f"workspace: {record.workspace_dir}")
    click.echo(f"created:   {record.created_at}")
    click.echo(f"state:     {state.state if state else 'draft'}")
    mid = record.current_mission_id
    if mid:
        click.echo(f"mission:   {mid}")
        try:
            tl = store.load_task_list(record.id, mid)
            ts = store.load_task_state(record.id, mid)
            rendered = render_task_list(tl, ts)
            if rendered:
                click.echo("")
                click.echo(rendered)
        except FileNotFoundError:
            click.echo("  (task list not yet submitted)")


# ---------------------------------------------------------------------------
# inspect-tasks
# ---------------------------------------------------------------------------


@cli.command("inspect-tasks")
@click.option("--project", "project_id", required=True)
@click.option("--mission", "mission_id", default=None)
def inspect_tasks_cmd(project_id: str, mission_id: str | None) -> None:
    """Render the compact text task list for a mission."""
    store = ProjectStore(HarnessConfig.discover())
    if mission_id is None:
        mid_list = store.list_missions(project_id)
        if not mid_list:
            raise click.ClickException("no missions in this project")
        mission_id = mid_list[-1]
    try:
        tl = store.load_task_list(project_id, mission_id)
    except FileNotFoundError:
        raise click.ClickException(f"tasks.json not found for {project_id}/{mission_id}")
    ts = store.load_task_state(project_id, mission_id)
    rendered = render_task_list(tl, ts, mode="full")
    if rendered:
        click.echo(rendered)


# ---------------------------------------------------------------------------
# abort-project
# ---------------------------------------------------------------------------


@cli.command("abort-project")
@click.argument("project_id")
@click.option("--reason", required=True)
def abort_project_cmd(project_id: str, reason: str) -> None:
    """Mark a project Aborted (CLI-side: preserves tasks.json + attempts/)."""
    from .controller import ProjectController
    from .dispatcher import MockDispatcher, MockTerminalReviewer
    from .models import TerminalReviewHandoff, WorkHandoff

    config = HarnessConfig.discover()
    controller = ProjectController(
        config,
        MockDispatcher(lambda r: WorkHandoff(node_id=r.task.id, done=False, report="aborted")),
        MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
    )
    env = controller.abort_project(project_id, reason)
    click.echo(f"Aborted {project_id}: state={env.state.state}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _copy_skills(loader: AssetLoader, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    bundled = loader.bundled_skills_dir()
    if not bundled.exists():
        click.echo(f"warning: bundled skills not found at {bundled}", err=True)
        return
    for skill_dir in iter_skill_directories(bundled):
        dest = target / skill_dir.name
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_dir / "SKILL.md", dest / "SKILL.md")


def _echo_user_next_steps(selection: ProviderSelection) -> None:
    provider = selection.orchestrator.name
    host = {"claude": "Claude Code", "codex": "Codex"}.get(provider, provider)
    click.echo(
        f"\nInitialized v5 user scope: orchestrator={provider}, "
        f"worker={selection.worker.name}, "
        f"validator={selection.resolved_validation_worker.name}."
    )
    click.echo("Zenith is available from every workspace for this user.")
    click.echo("")
    click.echo("Next:")
    click.echo(f"  1. Restart {host} or start a new session.")
    click.echo("  2. Run: /zenith <your instruction or query>")


def _echo_next_steps(orchestrator: ProviderDefinition) -> None:
    prompt_path = orchestrator.orchestrator_prompt_output_path
    click.echo("")
    click.echo("Next:")
    click.echo("  1. Start your agent from the initialized project workspace:")
    click.echo(f"     {orchestrator.name}")
    if prompt_path:
        click.echo("  2. Ask it:")
        click.echo(
            f"     First read {prompt_path} and treat it as your primary role, then use Zenith to run this mission."
        )
        click.echo("")
        click.echo("     <your instruction or query>")


def _resolve_selection(
    *,
    agent: str | None,
    orchestrator: str | None,
    worker: str | None,
    worker_acp_command: str | None,
    validator: str | None,
    validator_acp_command: str | None,
    terminal_reviewer: str | None,
    terminal_reviewer_acp_command: str | None,
) -> ProviderSelection:
    if agent and orchestrator and agent != orchestrator:
        raise click.UsageError("--agent conflicts with --orchestrator-provider")
    orch = orchestrator or agent or "claude"
    wrk = worker or (agent if agent in provider_names_for_role("worker") else None) or default_worker_provider_name(orch)
    return ProviderSelection(
        orchestrator=get_provider(orch),
        worker=get_provider(wrk),
        validation_worker=get_provider(validator) if validator else None,
        worker_acp_command=worker_acp_command,
        validation_worker_acp_command=validator_acp_command,
        terminal_reviewer=get_provider(terminal_reviewer) if terminal_reviewer else None,
        terminal_reviewer_acp_command=terminal_reviewer_acp_command,
    )


def _storage_env(
    *,
    zenith_home: str | None,
    workspace: Path,
    selection: ProviderSelection,
) -> dict[str, str]:
    env: dict[str, str] = {}
    if zenith_home:
        env["ZENITH_HOME"] = str(Path(zenith_home).expanduser().resolve())
    return env


def _forwarded_runtime_env() -> dict[str, str]:
    return {
        key: value
        for key in RUNTIME_ENV_FORWARD_ALLOWLIST
        if (value := os.environ.get(key))
    }


def _zenith_project_root() -> Path:
    """Return the source checkout that owns the Zenith runtime uv project."""
    start = Path(__file__).resolve()
    for candidate in (start.parent, *start.parents):
        pyproject = candidate / "pyproject.toml"
        if not pyproject.exists():
            continue
        try:
            text = pyproject.read_text(encoding="utf-8")
        except OSError:
            continue
        if 'name = "zenith-harness"' in text:
            return candidate
    raise click.ClickException(
        "Could not locate the Zenith uv project root. Run `zenith init` from a "
        "Zenith source checkout with pyproject.toml available."
    )


def _mcp_server_args() -> list[str]:
    return [
        "run",
        "--project",
        str(_zenith_project_root()),
        "zenith-server",
        "--mode",
        "orchestrator",
    ]


def _claude_user_paths() -> tuple[Path, Path]:
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    if configured:
        root = Path(configured).expanduser().resolve()
        return root, root / ".claude.json"
    home = Path.home().resolve()
    return home / ".claude", home / ".claude.json"


def _codex_user_paths() -> tuple[Path, Path]:
    root = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    root = root.expanduser().resolve()
    return root, root / "config.toml"


def _user_paths(provider: ProviderDefinition) -> tuple[Path, Path]:
    if provider.name == "claude":
        return _claude_user_paths()
    if provider.name == "codex":
        return _codex_user_paths()
    raise ValueError(f"user-scope paths are not defined for {provider.name}")


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    previous_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.zenith-",
            delete=False,
        ) as handle:
            handle.write(text)
            temp_path = Path(handle.name)
        if previous_mode is not None:
            temp_path.chmod(previous_mode)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _user_server_config(selection: ProviderSelection, storage_env: dict[str, str]) -> dict:
    return {
        "type": "stdio",
        "command": "uv",
        "args": _mcp_server_args(),
        "env": {**selection.env(), **storage_env},
    }


def _write_claude_user_config(
    path: Path,
    selection: ProviderSelection,
    storage_env: dict[str, str],
) -> None:
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise click.ClickException(f"Cannot update invalid Claude config {path}: {exc}") from exc
    else:
        existing = {}
    if not isinstance(existing, dict):
        raise click.ClickException(f"Cannot update Claude config {path}: root must be an object")
    mcp_servers = existing.setdefault("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        raise click.ClickException(
            f"Cannot update Claude config {path}: mcpServers must be an object"
        )
    mcp_servers["zenith"] = _user_server_config(selection, storage_env)
    _write_text_atomic(path, json.dumps(existing, indent=2) + "\n")
    click.echo(f"Wrote {path}")


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_table_path(line: str) -> tuple[str, ...] | None:
    stripped = line.strip()
    if not stripped.startswith("[") or stripped.startswith("[["):
        return None
    try:
        parsed = tomllib.loads(f"{stripped}\n")
    except tomllib.TOMLDecodeError:
        return None
    path: list[str] = []
    current = parsed
    while len(current) == 1:
        key, value = next(iter(current.items()))
        if not isinstance(value, dict):
            return None
        path.append(key)
        current = value
    return tuple(path) if not current else None


def _strip_toml_tables(text: str, table: tuple[str, ...]) -> str:
    kept: list[str] = []
    removing = False
    for line in text.splitlines(keepends=True):
        path = _toml_table_path(line)
        if path is not None:
            removing = path[: len(table)] == table
        if not removing:
            kept.append(line)
    return "".join(kept).rstrip()


def _parse_managed_block_lines(
    text: str,
    start: str,
    end: str,
) -> tuple[list[str], tuple[int, int] | None]:
    lines = text.splitlines(keepends=True)
    start_lines: list[int] = []
    end_lines: list[int] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == start:
            start_lines.append(index)
        elif stripped == end:
            end_lines.append(index)

    if not start_lines and not end_lines:
        return lines, None
    if len(start_lines) != 1 or len(end_lines) != 1 or start_lines[0] >= end_lines[0]:
        raise ValueError(
            "malformed Zenith managed block: expected no markers or one forward pair; "
            f"found {len(start_lines)} begin and {len(end_lines)} end markers"
        )
    return lines, (start_lines[0], end_lines[0])


def _write_codex_user_config(
    path: Path,
    selection: ProviderSelection,
    storage_env: dict[str, str],
) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        tomllib.loads(existing)
    except tomllib.TOMLDecodeError as exc:
        raise click.ClickException(f"Cannot update invalid Codex config {path}: {exc}") from exc

    start = "# BEGIN zenith"
    end = "# END zenith"
    try:
        existing_lines, managed_span = _parse_managed_block_lines(existing, start, end)
    except ValueError as exc:
        raise click.ClickException(f"Cannot update Codex config {path}: {exc}") from exc
    if managed_span is None:
        existing = _strip_toml_tables(existing, ("mcp_servers", "zenith"))

    server = _user_server_config(selection, storage_env)
    env_lines = "\n".join(
        f"{key} = {_toml_string(value)}" for key, value in server["env"].items()
    )
    block = (
        f"{start}\n"
        "[mcp_servers.zenith]\n"
        'command = "uv"\n'
        f"args = {json.dumps(server['args'], ensure_ascii=False)}\n"
        "startup_timeout_sec = 10\n"
        "tool_timeout_sec = 1000000\n"
        "\n"
        "[mcp_servers.zenith.env]\n"
        f"{env_lines}\n"
        f"{end}\n"
    )
    if managed_span is None:
        updated = existing.rstrip()
        if updated:
            updated += "\n\n"
        updated += block.rstrip() + "\n"
    else:
        start_line, end_line = managed_span
        updated = (
            "".join(existing_lines[:start_line])
            + block
            + "".join(existing_lines[end_line + 1 :])
        )
    try:
        tomllib.loads(updated)
    except tomllib.TOMLDecodeError as exc:
        raise click.ClickException(f"Generated invalid Codex config for {path}: {exc}") from exc
    _write_text_atomic(path, updated)
    click.echo(f"Wrote {path}")


def _write_user_bootstrap_config(
    selection: ProviderSelection,
    storage_env: dict[str, str],
) -> None:
    _, config_path = _user_paths(selection.orchestrator)
    if selection.orchestrator.name == "claude":
        _write_claude_user_config(config_path, selection, storage_env)
    elif selection.orchestrator.name == "codex":
        _write_codex_user_config(config_path, selection, storage_env)
    else:
        raise ValueError(f"unsupported user-scope provider: {selection.orchestrator.name}")


def _zenith_skill_body(prompt_path: Path) -> str:
    return f'''---
name: zenith
description: Run a long-horizon mission through the Zenith continuous-improvement harness.
---

# /zenith

First read `{prompt_path}` and treat it as your primary role, then use the globally
registered Zenith MCP tools to run the mission supplied with this skill.

If the Zenith tools are unavailable, ask the user to restart the host or start a new
session. Do not run workspace initialization merely because the current workspace has
no local Zenith configuration; project state begins with `start_project(brief,
workspace_dir)`.
'''


def _setup_user_provider_assets(loader: AssetLoader, provider: ProviderDefinition) -> None:
    root, _ = _user_paths(provider)
    agents_dir = root / "agents"
    _copy_provider_agents(loader, agents_dir, provider.name)
    click.echo(f"Installed {provider.name} subagents to {agents_dir}")

    skills_dir = root / "skills"
    _copy_skills(loader, skills_dir)
    click.echo(f"Installed bundled skills to {skills_dir}")

    shared_skills_dir = Path.home().resolve() / ".agents" / "skills"
    _copy_skills(loader, shared_skills_dir)
    click.echo(f"Installed bundled skills to {shared_skills_dir}")

    prompt_path = root / "orchestrator_prompt.md"
    prompt = loader.load_prompt_file("orchestrator", "system_prompt.md")
    _write_text_atomic(prompt_path, prompt)
    click.echo(f"Wrote {prompt_path}")

    skill_path = skills_dir / "zenith" / "SKILL.md"
    _write_text_atomic(skill_path, _zenith_skill_body(prompt_path))
    click.echo(f"Wrote {skill_path}")


def _write_bootstrap_config(
    workspace: Path,
    selection: ProviderSelection,
    storage_env: dict[str, str],
    cli_env: dict[str, str],
) -> None:
    fmt = selection.orchestrator.config_format
    env = {**selection.env(), **storage_env, **_forwarded_runtime_env(), **cli_env}
    server_args = _mcp_server_args()
    if fmt == "mcp_json":
        path = workspace / ".mcp.json"
        existing = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        )
        existing.setdefault("mcpServers", {})["zenith"] = {
            "type": "stdio",
            "command": "uv",
            "args": server_args,
            "env": env,
        }
        path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
        click.echo(f"Wrote {path}")
    elif fmt == "codex_config":
        config_path = workspace / ".codex" / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        # TOML basic strings share JSON's escape syntax, so json.dumps closes
        # and escapes embedded quotes. ACP commands splice config via
        # `-c key="value"`, and forwarded env values may hold quotes or
        # backslashes; interpolating either raw emits invalid TOML.
        env_lines = "\n".join(f"{k} = {json.dumps(v)}" for k, v in env.items())
        block = (
            'model = "gpt-5.5"\n'
            'sandbox_mode = "danger-full-access"\n'
            'model_reasoning_effort = "xhigh"\n'
            '[features]\n'
            'memories = true\n'
            "# BEGIN zenith\n"
            "[mcp_servers.zenith]\n"
            'command = "uv"\n'
            f"args = {json.dumps(server_args)}\n"
            "startup_timeout_sec = 10\n"
            "tool_timeout_sec = 1000000\n"
            "\n"
            "[mcp_servers.zenith.env]\n"
            f"{env_lines}\n"
            "# END zenith\n"
        )
        _replace_managed_block(config_path, "# BEGIN zenith", "# END zenith", block)
        click.echo(f"Wrote {config_path}")
    else:
        raise ValueError(f"unsupported config_format: {fmt}")


def _replace_managed_block_text(existing: str, start: str, end: str, block: str) -> str:
    if start in existing and end in existing:
        before, _, tail = existing.partition(start)
        _, _, after = tail.partition(end)
        updated = before.rstrip()
        if updated:
            updated += "\n\n"
        updated += block.rstrip() + "\n"
        if after.strip():
            updated += "\n" + after.lstrip("\n")
    else:
        updated = existing.rstrip()
        if updated:
            updated += "\n\n"
        updated += block.rstrip() + "\n"
    return updated


def _replace_managed_block(path: Path, start: str, end: str, block: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    updated = _replace_managed_block_text(existing, start, end, block)
    path.write_text(updated, encoding="utf-8")


def _setup_provider_assets(
    workspace: Path,
    loader: AssetLoader,
    provider: ProviderDefinition,
) -> None:
    if provider.agent_output_dir:
        agents_dir = workspace / provider.agent_output_dir
        _copy_provider_agents(
            loader, agents_dir, provider.name
        )
        click.echo(f"Installed {provider.name} subagents to {agents_dir}")
    # Install bundled skills into the host-agent skill surface so the
    # orchestrator can discover playbooks/skills at startup — `start_project`
    # runs only after the host agent is already up, so the surface must exist
    # before the first MCP call. `start_project` later merges bucket skills
    # (including project-authored ones) into these dirs.
    for rel in provider.skill_dirs:
        dest = workspace / rel
        _copy_skills(loader, dest)
        click.echo(f"Installed bundled skills to {dest}")
    if provider.orchestrator_prompt_output_path:
        path = workspace / provider.orchestrator_prompt_output_path
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            body = loader.load_prompt_file("orchestrator", "system_prompt.md")
            path.write_text(body, encoding="utf-8")
            click.echo(f"Created {path}")


def _copy_provider_agents(loader: AssetLoader, target: Path, provider_name: str) -> None:
    bundled = loader.bundled_agents_dir(provider_name)
    if not bundled.exists():
        return
    target.mkdir(parents=True, exist_ok=True)
    for agent_file in sorted(bundled.glob("*")):
        if agent_file.is_file():
            shutil.copy2(agent_file, target / agent_file.name)
