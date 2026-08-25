"""Read-only access to the authoritative IdentArk audit log."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from identark_cli.core.auth import get_api_client

console = Console()
app = typer.Typer(help="Read the authoritative control-plane audit trail")


@app.command("list")
def list_audit_records(
    limit: int = typer.Option(20, "--limit", "-n", min=1, max=200, help="Records to show"),
) -> None:
    """Show immutable audit records from the IdentArk control plane.

    This endpoint only shows actions that actually ran through Gateway Mode or
    another governed control-plane route.  It never treats a local development
    activity file as an organisation audit log.
    """
    try:
        with get_api_client() as client:
            response = client.get("/v1/audit", params={"limit": limit})
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        console.print(f"[red]Could not load audit trail:[/red] {exc}")
        raise typer.Exit(1) from None

    entries = payload.get("entries", []) if isinstance(payload, dict) else []
    if not entries:
        console.print("[dim]No governed activity yet.[/dim]")
        console.print("Run your agent in Gateway Mode, then try again.")
        return

    table = Table(title="IdentArk audit trail (control plane)")
    table.add_column("When", style="dim")
    table.add_column("Operation", style="cyan")
    table.add_column("Result")
    table.add_column("Session", style="dim")
    for entry in entries:
        table.add_row(
            str(entry.get("created_at", "")),
            str(entry.get("operation", "")),
            "[green]success[/green]" if entry.get("success") else "[red]failed[/red]",
            str(entry.get("session_id") or "—"),
        )
    console.print(table)
