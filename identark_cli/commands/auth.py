"""
Authentication commands for IdentArk CLI
"""

from __future__ import annotations

import typer

from identark_cli.core.auth import get_auth_status, login, logout
from identark_cli.ui import console, error_console
from identark_cli.ui.components import (
    StatusRow,
    render_context_summary,
    render_empty_state,
    render_error,
    render_security_note,
    render_success,
)

app = typer.Typer(help="Account connection and secure sessions")


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
    except Exception:
        render_error(
            error_console,
            "Could not connect your account.",
            explanation="The authorization session did not complete.",
            next_step="identark auth login --no-browser",
        )
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
    except Exception:
        render_error(
            error_console,
            "Could not clear the local session.",
            explanation="Check access to your OS keychain and IdentArk configuration directory.",
        )
        raise typer.Exit(1) from None


@app.command()
def status() -> None:
    """
    Show authentication status

    Displays current user, organization, and token status.
    """
    status = get_auth_status()

    if status.authenticated:
        render_context_summary(
            console,
            [
                StatusRow("Account", status.email or "Connected", "active"),
                StatusRow("Organization", status.org_name or "Not selected"),
                StatusRow("Session", "Verified" if status.verified else "Available", "active"),
                StatusRow("Source", status.source),
            ],
        )
        render_security_note(console, "Raw session tokens are never displayed by IdentArk CLI.")
    else:
        render_empty_state(
            console,
            "Account not connected",
            "Connect your account to manage production agents and approvals.",
            next_step="identark auth login",
        )


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
        render_success(console, "Secure session is available")
        console.print(f"Source: {status.source}")
        console.print(f"Verified: {'yes' if status.verified else 'not by this command'}")
        storage = (
            "environment (not persisted)"
            if status.source.startswith("IDENTARK_")
            else storage_backend_name()
        )
        console.print(f"Stored in: {storage}")
        console.print("[dim]Raw tokens are never displayed by IdentArk CLI.[/dim]")
    except Exception:
        render_error(
            error_console,
            "No usable secure session was found.",
            next_step="identark auth login",
        )
        raise typer.Exit(1) from None
