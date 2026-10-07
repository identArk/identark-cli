"""Terminal design-system and contextual-home regression tests."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from identark_cli.core.auth import AuthStatus
from identark_cli.core.config import GatewayModeConfig, ProjectConfig
from identark_cli.main import app
from identark_cli.ui.components import (
    NextStep,
    StatusRow,
    render_context_summary,
    render_error,
    render_header,
    render_next_steps,
)
from identark_cli.ui.context import build_home_context
from identark_cli.ui.safety import redact_sensitive, safe_rich_text


def _recording_console(*, width: int = 80, no_color: bool = True) -> tuple[Console, StringIO]:
    stream = StringIO()
    return (
        Console(file=stream, width=width, no_color=no_color, force_terminal=False),
        stream,
    )


def test_new_user_home_context_has_one_clear_journey() -> None:
    home = build_home_context(AuthStatus(authenticated=False), None)

    assert [row.value for row in home.rows] == [
        "Not connected",
        "Not initialized",
        "Not configured",
    ]
    assert [step.command for step in home.steps] == [
        "identark auth login",
        "identark init --provider openai",
        "identark agent run identark_sample.py",
    ]
    assert "project files" in home.security_note


def test_gateway_home_context_never_displays_sensitive_identifiers() -> None:
    project = ProjectConfig(
        project_name="payments-agent",
        gateway_mode=GatewayModeConfig(
            agent_id="agent-sensitive-id",
            session_id="session-sensitive-id",
            provider="openai",
            model="gpt-4o-mini",
            credential_ref="vault://prod/sensitive-reference",
        ),
    )
    home = build_home_context(
        AuthStatus(authenticated=True, email="operator@example.com", verified=True),
        project,
    )
    rendered = repr(home)

    assert "Gateway Mode" in rendered
    assert "agent-sensitive-id" not in rendered
    assert "session-sensitive-id" not in rendered
    assert "sensitive-reference" not in rendered
    assert "short-lived capability" in home.security_note


@pytest.mark.parametrize("width", [40, 80, 120])
def test_core_components_render_at_supported_terminal_widths(width: int) -> None:
    console, stream = _recording_console(width=width)

    render_header(console, version="0.1.0")
    render_context_summary(
        console,
        [
            StatusRow("Account", "Not connected", "attention"),
            StatusRow("Project", "demo", "active"),
        ],
    )
    render_next_steps(console, [NextStep("Connect your account", "identark auth login")])

    output = stream.getvalue()
    assert "IdentArk" in output
    assert "Not connected" in output
    assert "identark auth login" in output


def test_error_component_uses_only_explicit_safe_copy() -> None:
    console, stream = _recording_console()
    secret = "csk_this-value-must-not-be-rendered"

    render_error(
        console,
        "Could not connect your account.",
        explanation="The service did not accept the request.",
        next_step="identark auth login",
    )

    output = stream.getvalue()
    assert secret not in output
    assert "Could not connect your account" in output
    assert "identark auth login" in output


def test_no_argument_cli_renders_contextual_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "identark_cli.main.get_auth_status",
        lambda: AuthStatus(authenticated=False),
    )
    monkeypatch.setattr("identark_cli.main._load_project_for_home", lambda: (None, None))

    result = CliRunner().invoke(app, ["--no-color"])

    assert result.exit_code == 0, result.output
    assert "Secure access for production AI agents" in result.output
    assert "Not connected" in result.output
    assert "identark init --provider openai" in result.output
    assert "\x1b" not in result.output


def test_status_does_not_print_gateway_ids_or_credential_references(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = ProjectConfig(
        project_name="demo",
        gateway_mode=GatewayModeConfig(
            agent_id="agent-private",
            session_id="session-private",
            provider="openai",
            model="gpt-4o-mini",
            credential_ref="vault://prod/private",
        ),
    )
    monkeypatch.setattr(
        "identark_cli.main.get_auth_status",
        lambda: AuthStatus(authenticated=True, email="user@example.com", verified=True),
    )
    monkeypatch.setattr(
        "identark_cli.main._load_project_for_home",
        lambda: (project, tmp_path.name),
    )

    result = CliRunner().invoke(app, ["--no-color", "status"])

    assert result.exit_code == 0, result.output
    assert "Gateway Mode" in result.output
    assert "agent-private" not in result.output
    assert "session-private" not in result.output
    assert "vault://prod/private" not in result.output


def test_help_groups_commands_by_user_intent() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0, result.output
    assert result.output.index("Get started") < result.output.index("Build")
    assert result.output.index("Build") < result.output.index("Govern")
    assert "Human approvals for sensitive operations" in result.output
    assert "HITL" not in result.output


def test_untrusted_output_is_recursively_redacted_and_terminal_safe() -> None:
    secret = "csk_abcdefghijklmnopqrstuvwxyz123456"
    value = {
        "result": f"Bearer {secret}",
        "nested": {"password": "do-not-show", "message": f"token={secret}"},
    }

    redacted = redact_sensitive(value)
    rendered = safe_rich_text(f"[bold]\x1b[31m{secret}[/bold]")

    assert secret not in repr(redacted)
    assert redacted["nested"]["password"] == "*** REDACTED ***"
    assert secret not in rendered
    assert "\x1b" not in rendered
    assert "\\[bold]" in rendered


def test_bare_escape_spliced_into_a_key_cannot_evade_redaction() -> None:
    # ANSI_ESCAPE only removes full CSI sequences, so a lone \x1b reaches the
    # control-character pass. Replacing it with a space used to break the
    # `csk_` pattern and print the key split by one space.
    secret = "csk_abcdefghijklmnopqrstuvwxyz123456"
    head, tail = secret[:4], secret[4:]

    rendered = safe_rich_text(f"tool said: {head}\x1b{tail}")

    assert "*** REDACTED ***" in rendered
    assert tail not in rendered
    assert "\x1b" not in rendered


def test_full_csi_sequence_spliced_into_a_key_is_redacted() -> None:
    secret = "csk_abcdefghijklmnopqrstuvwxyz123456"
    head, tail = secret[:4], secret[4:]

    rendered = safe_rich_text(f"tool said: {head}\x1b[31m{tail}")

    assert "*** REDACTED ***" in rendered
    assert tail not in rendered
    assert "\x1b" not in rendered


def test_control_character_splices_are_redacted_for_other_secret_patterns() -> None:
    secret = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"
    head, tail = secret[:7], secret[7:]

    for control in ("\x1b", "\x00", "\n", "\x7f", "\x9b"):
        rendered = safe_rich_text(f"tool said: {head}{control}{tail}")

        assert "*** REDACTED ***" in rendered, control
        assert tail not in rendered, control
        assert control not in rendered, control


def test_clean_untrusted_text_keeps_control_characters_as_spaces() -> None:
    rendered = safe_rich_text("first line\nsecond line")

    assert rendered == "first line second line"
