#!/usr/bin/env python3
"""
IdentArk CLI - Main entry point
"""

from __future__ import annotations

import typer
from rich.table import Table

from identark_cli import __version__
from identark_cli.commands import agent, approvals, audit, auth, config, credential, mcp, promote
from identark_cli.commands.execute import execute
from identark_cli.core.activity import ActivityRecordError, read_local_activity
from identark_cli.core.auth import get_auth_status
from identark_cli.core.config import ProjectConfig, get_project_root, load_config
from identark_cli.core.init import FirstRunProvider
from identark_cli.ui import configure_console, console, error_console
from identark_cli.ui.components import (
    StatusRow,
    render_context_summary,
    render_error,
    render_header,
    render_next_steps,
    render_security_note,
    render_success,
)
from identark_cli.ui.context import build_home_context

# Create the main app
app = typer.Typer(
    name="identark",
    help="IdentArk CLI - credential references, approvals, and managed access",
    add_completion=True,
    rich_markup_mode="rich",
    no_args_is_help=False,
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool | None = typer.Option(
        None, "--version", "-v", help="Show version and exit", is_eager=True
    ),
    no_color: bool = typer.Option(
        False,
        "--no-color",
        help="Disable color output (also honors NO_COLOR and TERM=dumb)",
    ),
) -> None:
    """
    Secure access for production AI agents.

    Start locally, then move to Gateway Mode without placing provider
    credentials inside your production agent.

    [bold]Quick start:[/bold]

    $ identark auth login              # Connect your account

    $ identark agent init --name demo  # Initialize agent project

    $ identark credential scan         # Scan local code for secrets

    $ identark agent run ./my_agent.py # Run with local credential injection
    """
    configure_console(no_color=no_color)
    if version:
        console.print(f"identark version {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        _render_home()


def _load_project_for_home() -> tuple[ProjectConfig | None, str | None]:
    """Load presentation-safe project state without treating absence as an error."""
    root = get_project_root()
    if root is None:
        return None, None
    try:
        return load_config(root / ".identark" / "config.toml"), root.name
    except Exception:
        return None, root.name


def _render_home(*, detailed: bool = False) -> None:
    """Render a contextual landing screen for the current directory."""
    auth_status = get_auth_status()
    project, directory_name = _load_project_for_home()
    home = build_home_context(auth_status, project, project_directory_name=directory_name)

    render_header(console, version=__version__)
    rows = list(home.rows)
    if detailed and project is not None:
        rows.append(StatusRow("References", str(len(project.credentials))))
        if project.gateway_mode and project.gateway_mode.capability_expires_at:
            rows.append(
                StatusRow(
                    "Capability",
                    f"Expires {project.gateway_mode.capability_expires_at}",
                    "attention",
                )
            )
    render_context_summary(console, rows)
    render_next_steps(console, home.steps, title="Get started" if project is None else "Next steps")
    render_security_note(console, home.security_note)
    console.print()


@app.command(rich_help_panel="Get started")
def init(
    path: str = typer.Option(".", "--path", "-p", help="Path to initialize"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing configuration"),
    provider: FirstRunProvider | None = typer.Option(
        None, "--provider", help="Generate a runnable local sample for this provider"
    ),
) -> None:
    """
    Initialize IdentArk in the current directory

    Creates .identark/config.toml and sets up project credential references.
    """
    from identark_cli.core.init import initialize_project

    try:
        setup = initialize_project(path, force=force, provider=provider)
        render_success(console, f"Initialized IdentArk in {path}")
        if setup:
            console.print("\n[bold]First run — local development only:[/bold]")
            console.print(f"  1. Install: {setup.install_command}")
            if provider != FirstRunProvider.OLLAMA:
                console.print(
                    f"  2. Set {setup.credential_name} in your shell "
                    "(it is never written to the project)"
                )
            console.print("  3. Run: identark agent run identark_sample.py")
            console.print("  4. Inspect: identark trail")
            console.print(
                "\n[dim]The local record is not a governed audit trail. Gateway Mode "
                "records the authoritative trail.[/dim]"
            )
            return
        console.print("\nNext steps:")
        console.print("  1. Run: identark auth login")
        console.print("  2. Run: identark credential add <name>")
        console.print("  3. Optional: identark credential install-hook")
        console.print("  4. Run: identark agent run <script.py>")
    except Exception:
        render_error(
            error_console,
            "Could not initialize this project.",
            explanation="The path may be unavailable or an existing configuration may need review.",
            next_step="identark init --help",
        )
        raise typer.Exit(1) from None


@app.command("trail", rich_help_panel="Build")
def activity_trail(
    limit: int = typer.Option(10, "--limit", "-n", min=1, max=200, help="Local records to show"),
) -> None:
    """Verify and show local development activity without exposing prompts or secrets."""
    root = get_project_root()
    if root is None:
        console.print("[red]No IdentArk project found. Run 'identark init' first.[/red]")
        raise typer.Exit(1)
    try:
        events = read_local_activity(root, limit=limit)
    except ActivityRecordError as exc:
        console.print(f"[red]Could not verify local activity record:[/red] {exc}")
        raise typer.Exit(1) from None
    if not events:
        console.print("[dim]No local activity records yet. Run identark_sample.py first.[/dim]")
        return
    table = Table(title="Local development activity (hash-linked)")
    table.add_column("When", style="dim")
    table.add_column("Provider", style="cyan")
    table.add_column("Model")
    table.add_column("Result")
    table.add_column("Cost")
    for event in events:
        table.add_row(
            str(event["recorded_at"]),
            str(event["provider"]),
            str(event["model"]),
            "[green]success[/green]" if event["success"] else "[red]failed[/red]",
            f"${float(event['cost_usd']):.6f}" if event["cost_usd"] is not None else "—",
        )
    console.print(table)
    console.print(
        "[dim]Verified local record. This is not governed history; "
        "use `identark audit list` after Gateway Mode is configured.[/dim]"
    )


@app.command(rich_help_panel="Get started")
def status() -> None:
    """
    Show IdentArk status and configuration

    Displays current authentication status and configured credential references.
    """
    _render_home(detailed=True)


# Register grouped command families after the first-class onboarding commands
# so Typer renders "Get started" before advanced sections.
app.command("promote", rich_help_panel="Build")(promote.promote)
app.add_typer(
    agent.app,
    name="agent",
    help="Agent scaffolding, registration, and local execution",
    rich_help_panel="Build",
)
app.add_typer(
    credential.app,
    name="credential",
    help="Credential references, scanning, and local injection",
    rich_help_panel="Build",
)
app.command("exec", rich_help_panel="Govern")(execute)
app.add_typer(
    auth.app,
    name="auth",
    help="Account connection and secure sessions",
    rich_help_panel="Account",
)
app.add_typer(
    config.app,
    name="config",
    help="Configuration management",
    rich_help_panel="Account",
)
app.add_typer(
    approvals.app,
    name="approvals",
    help="Human approvals for sensitive operations",
    rich_help_panel="Govern",
)
app.add_typer(
    audit.app,
    name="audit",
    help="Governed history and verifiable evidence",
    rich_help_panel="Govern",
)
app.add_typer(mcp.app, name="mcp", help="MCP server management", rich_help_panel="Govern")


# Entry point for `python -m identark_cli`
def cli_entry() -> None:
    """Entry point for the CLI"""
    app()


if __name__ == "__main__":
    cli_entry()
