"""
Authentication commands for IdentArk CLI
"""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from identark_cli.core.auth import login, logout, get_auth_status

console = Console()
app = typer.Typer(help="Authentication and login")


@app.command()
def login_cmd(
    api_url: str = typer.Option(
        "https://identark-cloud.fly.dev",
        "--api-url",
        "-a",
        help="IdentArk API URL"
    ),
    no_browser: bool = typer.Option(
        False,
        "--no-browser",
        help="Don't open browser automatically"
    )
) -> None:
    """
    Authenticate with IdentArk
    
    Opens a browser for OAuth authentication. Use --no-browser for
    headless environments.
    """
    try:
        login(api_url=api_url, browser=not no_browser)
    except Exception as e:
        console.print(f"[red]Login failed:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def logout_cmd(
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation")
) -> None:
    """
    Log out from IdentArk
    
    Clears local credentials and revokes access tokens.
    """
    if not force:
        status = get_auth_status()
        if status.authenticated:
            confirm = typer.confirm(f"Log out {status.email}?")
            if not confirm:
                console.print("Cancelled")
                return
    
    try:
        logout()
    except Exception as e:
        console.print(f"[red]Logout failed:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def status() -> None:
    """
    Show authentication status
    
    Displays current user, organization, and token status.
    """
    status = get_auth_status()
    
    table = Table(title="Authentication Status")
    table.add_column("Property", style="cyan")
    table.add_column("Value")
    
    if status.authenticated:
        table.add_row("Status", "[green]✓ Authenticated[/green]")
        table.add_row("Email", status.email or "Unknown")
        table.add_row("Organization", status.org_name or "Unknown")
        table.add_row("User ID", status.user_id or "Unknown")
    else:
        table.add_row("Status", "[red]✗ Not authenticated[/red]")
        table.add_row("Email", "-")
        table.add_row("Organization", "-")
    
    console.print(table)
    
    if not status.authenticated:
        console.print("\nRun [cyan]identark auth login[/cyan] to authenticate")


@app.command()
def token() -> None:
    """
    Show current access token (for debugging)
    
    [yellow]Warning:[/yellow] This exposes sensitive information.
    Use with caution and never share the output.
    """
    from identark_cli.core.auth import get_access_token
    
    try:
        token = get_access_token()
        console.print(f"Access token: [dim]{token[:20]}...[/dim]")
        console.print("\n[yellow]Use this token in the Authorization header:[/yellow]")
        console.print(f"Authorization: Bearer {token}")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
