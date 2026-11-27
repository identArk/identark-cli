"""Build the non-sensitive state shown on the CLI home and status screens."""

from __future__ import annotations

from dataclasses import dataclass

from identark_cli.core.auth import AuthStatus
from identark_cli.core.config import ProjectConfig
from identark_cli.ui.components import NextStep, StatusRow
from identark_cli.ui.copy import (
    GATEWAY_MODE,
    GATEWAY_SECURITY_NOTE,
    LOCAL_MODE,
    LOCAL_SECURITY_NOTE,
    NEW_PROJECT_SECURITY_NOTE,
)


@dataclass(frozen=True)
class HomeContext:
    """Presentation-safe home screen state."""

    rows: tuple[StatusRow, ...]
    steps: tuple[NextStep, ...]
    security_note: str


def build_home_context(
    auth: AuthStatus,
    project: ProjectConfig | None,
    *,
    project_directory_name: str | None = None,
) -> HomeContext:
    """Derive the recommended journey without exposing identifiers or references."""
    if auth.authenticated:
        account = auth.email or "Connected"
        account_state = "active" if auth.verified else "attention"
    else:
        account = "Not connected"
        account_state = "attention"

    if project is None:
        project_name = "Not initialized"
        mode = "Not configured"
        project_state = "attention"
        mode_state = "neutral"
    else:
        project_name = project.project_name or project_directory_name or "Current project"
        project_state = "active"
        if project.gateway_mode is not None:
            mode = GATEWAY_MODE
            mode_state = "active"
        else:
            mode = LOCAL_MODE
            mode_state = "neutral"

    rows = (
        StatusRow("Account", account, account_state),
        StatusRow("Project", project_name, project_state),
        StatusRow("Mode", mode, mode_state),
    )

    steps: list[NextStep] = []
    if not auth.authenticated:
        steps.append(NextStep("Connect your account", "identark auth login"))
    if project is None:
        steps.append(NextStep("Set up this project", "identark init --provider openai"))
        steps.append(NextStep("Run the sample", "identark agent run identark_sample.py"))
        security_note = NEW_PROJECT_SECURITY_NOTE
    elif project.gateway_mode is None:
        steps.append(NextStep("Run your local agent", "identark agent run identark_sample.py"))
        if auth.authenticated:
            steps.append(NextStep("Move to Gateway Mode", "identark promote --help"))
        security_note = LOCAL_SECURITY_NOTE
    else:
        steps.append(NextStep("Run the governed agent", "python identark_gateway_sample.py"))
        steps.append(NextStep("Inspect governed history", "identark audit list"))
        security_note = GATEWAY_SECURITY_NOTE

    return HomeContext(rows=rows, steps=tuple(steps[:3]), security_note=security_note)
