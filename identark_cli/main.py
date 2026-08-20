#!/usr/bin/env python3
"""
IdentArk CLI - Main entry point
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from identark_cli import __version__
from identark_cli.commands import agent, approvals, auth, config, credential, mcp

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
) -> None:
    """
    Initialize IdentArk in the current directory

    Creates .identark/config.toml and sets up project credential references.
    """
    from identark_cli.core.init import initialize_project

    try:
        initialize_project(path, force=force)
        console.print(f"✓ Initialized IdentArk in [bold]{path}[/bold]")
        console.print("\nNext steps:")
        console.print("  1. Run: identark auth login")
        console.print("  2. Run: identark credential add <name>")
        console.print("  3. Optional: identark credential install-hook")
        console.print("  4. Run: identark agent run <script.py>")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


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
