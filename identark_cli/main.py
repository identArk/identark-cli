#!/usr/bin/env python3
"""
IdentArk CLI - Main entry point
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from identark_cli import __version__
from identark_cli.commands import agent, approvals, audit, auth, config, credential, mcp
from identark_cli.core.activity import ActivityRecordError, read_local_activity
from identark_cli.core.config import get_project_root
from identark_cli.core.init import FirstRunProvider

# Rich console for pretty output
console = Console()

# Create the main app
app = typer.Typer(
    name="identark",
    help="IdentArk CLI - credential references, approvals, and managed access",
    add_completion=True,
    rich_markup_mode="rich",
    no_args_is_help=True,
)

# Add subcommands
app.add_typer(auth.app, name="auth", help="Authentication and login")
app.add_typer(agent.app, name="agent", help="Agent scaffolding, registration, and local execution")
app.add_typer(
    credential.app,
    name="credential",
    help="Credential references, scanning, and local injection",
)
app.add_typer(approvals.app, name="approvals", help="HITL approval workflow")
app.add_typer(audit.app, name="audit", help="Authoritative control-plane audit trail")
app.add_typer(mcp.app, name="mcp", help="MCP server management")
app.add_typer(config.app, name="config", help="Configuration management")


@app.callback(invoke_without_command=True)
def main(
    version: bool | None = typer.Option(
        None, "--version", "-v", help="Show version and exit", is_eager=True
    ),
) -> None:
    """
    IdentArk CLI - Secure AI agent access management

    Run local development processes with short-lived credential injection,
    manage references, and review high-risk operations from your terminal.

    [bold]Quick start:[/bold]

    $ identark auth login              # Authenticate with IdentArk

    $ identark agent init --name demo  # Initialize agent project

    $ identark credential scan         # Scan for secrets in code

    $ identark agent run ./my_agent.py # Run with local credential injection
    """
    if version:
        console.print(f"identark version {__version__}")
        raise typer.Exit()


@app.command()
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
        console.print(f"✓ Initialized IdentArk in [bold]{path}[/bold]")
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
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


@app.command("trail")
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
        "[dim]Verified local record. This is not the control-plane audit trail; "
        "use `identark audit list` after Gateway Mode is configured.[/dim]"
    )


@app.command()
def status() -> None:
    """
    Show IdentArk status and configuration

    Displays current authentication status and configured credential references.
    """
    from identark_cli.core.auth import get_auth_status
    from identark_cli.core.config import load_config

    # Title
    console.print()
    console.print(
        Panel.fit(
            Text("IdentArk CLI", style="bold cyan") + Text(f" v{__version__}", style="dim"),
            border_style="cyan",
        )
    )

    # Auth status
    auth_status = get_auth_status()
    console.print("\n[bold]Authentication:[/bold]")
    if auth_status.authenticated:
        if auth_status.email:
            console.print(f"  ✓ Logged in as [green]{auth_status.email}[/green]")
        else:
            console.print(f"  ✓ Authenticated via [green]{auth_status.source}[/green]")
        if auth_status.org_name:
            console.print(f"  Organization: {auth_status.org_name}")
    else:
        console.print("  ✗ Not authenticated")
        console.print("    Run: [cyan]identark auth login[/cyan]")

    # Config
    try:
        config = load_config()
        console.print("\n[bold]Configuration:[/bold]")
        console.print(f"  Project: {config.project_name or 'Not configured'}")
        console.print(f"  Credentials: {len(config.credentials)}")
    except Exception:
        console.print("\n[bold]Configuration:[/bold]")
        console.print("  No project configured")
        console.print("    Run: [cyan]identark init[/cyan]")

    console.print()


# Entry point for `python -m identark_cli`
def cli_entry() -> None:
    """Entry point for the CLI"""
    app()


if __name__ == "__main__":
    cli_entry()
