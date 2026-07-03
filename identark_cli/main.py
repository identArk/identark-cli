#!/usr/bin/env python3
"""
IdentArk CLI - Main entry point
"""

from __future__ import annotations

from typing import Optional

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
    help="IdentArk CLI - AI agent credential isolation",
    add_completion=True,
    rich_markup_mode="rich",
    no_args_is_help=True,
)

# Add subcommands
app.add_typer(auth.app, name="auth", help="Authentication and login")
app.add_typer(agent.app, name="agent", help="Agent development and execution")
app.add_typer(credential.app, name="credential", help="Credential management")
app.add_typer(approvals.app, name="approvals", help="HITL approval workflow")
app.add_typer(mcp.app, name="mcp", help="MCP server management")
app.add_typer(config.app, name="config", help="Configuration management")


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", help="Show version and exit", is_eager=True
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose output"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress non-error output"),
) -> None:
    """
    IdentArk CLI - Secure AI agent credential management

    Run agents with isolated credentials, manage secrets, and approve
    high-risk operations from your terminal.

    [bold]Quick start:[/bold]

    $ identark auth login              # Authenticate with IdentArk

    $ identark agent init              # Initialize agent project

    $ identark credential scan         # Scan for secrets in code

    $ identark agent run ./my_agent.py # Run with isolated credentials
    """
    if version:
        console.print(f"identark version {__version__}")
        raise typer.Exit()


@app.command()
def init(
    path: Optional[str] = typer.Option(".", "--path", "-p", help="Path to initialize"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing configuration"),
) -> None:
    """
    Initialize IdentArk in the current directory

    Creates .identark/config.toml and sets up the project for
    credential isolation.
    """
    from identark_cli.core.init import initialize_project

    try:
        initialize_project(path, force=force)
        console.print(f"✓ Initialized IdentArk in [bold]{path}[/bold]")
        console.print("\nNext steps:")
        console.print("  1. Run: identark auth login")
        console.print("  2. Run: identark credential add <name>")
        console.print("  3. Run: identark agent run <script.py>")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def status() -> None:
    """
    Show IdentArk status and configuration

    Displays current authentication status, configured credentials,
    and active sessions.
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
        console.print(f"  ✓ Logged in as [green]{auth_status.email}[/green]")
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
    except:
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
