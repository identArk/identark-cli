"""
Authentication commands for IdentArk CLI
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from identark_cli.core.auth import get_auth_status, login, logout

console = Console()
app = typer.Typer(help="Authentication and login")


@app.command("login")
def login_cmd(
    api_url: str = typer.Option(
        "https://api.identark.io", "--api-url", "-a", help="IdentArk API URL"
    ),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't open browser automatically"),
) -> None:
    """
    Authenticate with IdentArk

    Opens the IdentArk device-authorization page. Use --no-browser for
    headless environments and open the printed URL yourself.
    """
    try:
        login(api_url=api_url, browser=not no_browser)
    except Exception as e:
        console.print(f"[red]Login failed:[/red] {e}")
        raise typer.Exit(1) from None


@app.command("logout")
def logout_cmd(
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """
    Log out from IdentArk

    Clears locally stored access and refresh tokens.
    """
    if not force:
        status = get_auth_status()
        if status.authenticated:
            identity = status.email or "the current session"
            confirm = typer.confirm(f"Log out {identity}?")
            if not confirm:
                console.print("Cancelled")
                return

    try:
        logout()
    except Exception as e:
        console.print(f"[red]Logout failed:[/red] {e}")
        raise typer.Exit(1) from None


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
        table.add_row("Source", status.source)
        table.add_row("Verified", "Yes" if status.verified else "No")
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
    Report whether an authentication token is configured

    Raw access tokens are deliberately never printed. Use this command for
    safe authentication diagnostics in support requests.
    """
    from identark_cli.core.auth import get_access_token, get_auth_status
    from identark_cli.core.secrets import storage_backend_name

    try:
        get_access_token()
        status = get_auth_status()
        console.print("[green]✓ Authentication token is configured[/green]")
        console.print(f"Source: {status.source}")
        console.print(f"Verified: {'yes' if status.verified else 'not by this command'}")
        storage = (
            "environment (not persisted)"
            if status.source.startswith("IDENTARK_")
            else storage_backend_name()
        )
        console.print(f"Stored in: {storage}")
        console.print("[dim]Raw tokens are never displayed by IdentArk CLI.[/dim]")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
