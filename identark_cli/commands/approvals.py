"""
HITL Approval commands
"""

from __future__ import annotations

import json
import time
from typing import Any

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from identark_cli.core.auth import get_api_client

console = Console()
app = typer.Typer(help="HITL approval workflow")


@app.command("list")
def list_approvals(
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum results"),
) -> None:
    """
    List approval requests

    Shows pending HITL requests.
    """
    try:
        if limit < 1 or limit > 100:
            console.print("[red]--limit must be between 1 and 100[/red]")
            raise typer.Exit(2)
        with get_api_client() as client:
            response = client.get("/v1/mcp/approvals/pending")
            response.raise_for_status()
            approvals = response.json()[:limit]
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error fetching approvals:[/red] {e}")
        raise typer.Exit(1) from None

    if not approvals:
        console.print("No pending approvals")
        return

    table = Table(title=f"Pending Approvals ({len(approvals)})", box=box.ROUNDED)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Tool")
    table.add_column("Risk")
    table.add_column("Requested By")
    table.add_column("Age")

    for approval in approvals:
        risk_score = approval.get("risk_score", 0)
        risk_style = _risk_style(risk_score)

        # Calculate age
        created = approval.get("created_at", "")
        age = _time_since(created)

        table.add_row(
            approval["id"][:8],
            approval.get("tool_name", "unknown"),
            f"[{risk_style}]{risk_score}[/{risk_style}]",
            approval.get("requested_by", "unknown"),
            age,
        )

    console.print(table)

    console.print("\n[dim]Run [cyan]identark approvals inspect <id>[/cyan] for details[/dim]")


@app.command()
def inspect(
    approval_id: str = typer.Argument(..., help="Approval request ID"),
) -> None:
    """
    Inspect approval request details

    Shows full details including tool arguments, risk factors,
    and approval history.
    """
    try:
        with get_api_client() as client:
            response = client.get(f"/v1/mcp/approvals/{approval_id}")
            response.raise_for_status()
            approval = response.json()
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    # Build detail panel
    risk_score = approval.get("risk_score", 0)
    risk_level = approval.get("risk_level", "unknown")
    risk_style = _risk_style(risk_score)

    safe_arguments = json.dumps(_redact_sensitive(approval.get("tool_arguments", {})), indent=2)
    content = f"""
[bold]Tool:[/bold]         {approval.get("tool_name", "unknown")}
[bold]Status:[/bold]       {approval.get("status", "unknown")}
[bold]Risk Score:[/bold]   [{risk_style}]{risk_score} ({risk_level})[/{risk_style}]
[bold]Requested By:[/bold] {approval.get("requested_by", "unknown")}
[bold]Created:[/bold]      {approval.get("created_at", "unknown")}
[bold]Expires:[/bold]      {approval.get("expires_at", "unknown")}

[bold]Risk Explanation:[/bold]
{approval.get("risk_explanation", "No explanation available")}

[bold]Tool Arguments:[/bold]
```json
{safe_arguments}
```
    """

    console.print(Panel(content, title=f"Approval Request: {approval_id}", border_style="cyan"))

    if approval.get("status") == "pending":
        console.print("\n[bold]Actions:[/bold]")
        console.print(f"  [cyan]identark approvals approve {approval_id}[/cyan]")
        console.print(f"  [cyan]identark approvals reject {approval_id} --reason '...'[/cyan]")


@app.command()
def approve(
    approval_id: str = typer.Argument(..., help="Approval request ID"),
    comment: str | None = typer.Option(None, "--comment", "-c", help="Approval comment"),
    mfa_code: str | None = typer.Option(None, "--mfa", help="MFA code (required for high risk)"),
) -> None:
    """
    Approve a pending request

    Approves the HITL request and allows the agent to proceed.
    High-risk operations (>70) require MFA verification.
    """
    try:
        with get_api_client() as client:
            # Get approval details first to check risk
            response = client.get(f"/v1/mcp/approvals/{approval_id}")
            response.raise_for_status()
            approval = response.json()

            # Check if MFA required
            if approval.get("risk_score", 0) >= 70 and not mfa_code:
                console.print("[yellow]This operation requires MFA verification[/yellow]")
                mfa_code = typer.prompt("Enter MFA code", hide_input=True)

            # Submit approval
            payload = {"decision": "approved", "comment": comment, "mfa_token": mfa_code}

            response = client.post(f"/v1/mcp/approvals/{approval_id}/decision", json=payload)
            response.raise_for_status()

        console.print(f"[green]✓ Approved request {approval_id}[/green]")

        if approval.get("tool_name"):
            console.print(f"  Tool: [cyan]{approval['tool_name']}[/cyan]")

    except Exception as e:
        console.print(f"[red]Approval failed:[/red] {e}")
        raise typer.Exit(1) from None


@app.command()
def reject(
    approval_id: str = typer.Argument(..., help="Approval request ID"),
    reason: str = typer.Option(..., "--reason", "-r", help="Rejection reason"),
) -> None:
    """
    Reject a pending request

    Rejects the HITL request and prevents the agent from
    executing the operation.
    """
    try:
        with get_api_client() as client:
            payload = {"decision": "rejected", "comment": reason}

            response = client.post(f"/v1/mcp/approvals/{approval_id}/decision", json=payload)
            response.raise_for_status()

        console.print(f"[yellow]✗ Rejected request {approval_id}[/yellow]")
        console.print(f"  Reason: {reason}")

    except Exception as e:
        console.print(f"[red]Rejection failed:[/red] {e}")
        raise typer.Exit(1) from None


@app.command()
def watch(
    refresh: int = typer.Option(5, "--refresh", help="Refresh interval in seconds"),
) -> None:
    """
    Watch approvals in real-time

    Monitor HITL requests as they arrive. Use approve, reject, or inspect
    from another terminal to act on a request.
    """
    if refresh < 1:
        console.print("[red]--refresh must be at least 1 second[/red]")
        raise typer.Exit(2)
    console.print("[bold]Watching for approval requests...[/bold]")
    console.print("[dim]Press Ctrl+C to exit[/dim]\n")

    try:
        while True:
            # Fetch pending approvals
            try:
                with get_api_client() as client:
                    response = client.get("/v1/mcp/approvals/pending")
                    response.raise_for_status()
                    approvals = response.json()[:10]
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")
                time.sleep(refresh)
                continue

            # Build display
            if not approvals:
                table = Table(box=box.ROUNDED)
                table.add_column("Status", justify="center")
                table.add_row("[dim]No pending approvals[/dim]")
                console.print(table)
            else:
                table = Table(title=f"🔄 {len(approvals)} Pending", box=box.ROUNDED)
                table.add_column("ID", style="cyan")
                table.add_column("Tool")
                table.add_column("Risk", justify="right")
                table.add_column("Action Required")

                for approval in approvals:
                    risk = approval.get("risk_score", 0)
                    risk_style = _risk_style(risk)

                    if risk >= 70:
                        action = "[red]MFA required[/red]"
                    else:
                        action = "[yellow]Review needed[/yellow]"

                    table.add_row(
                        approval["id"][:8],
                        approval.get("tool_name", "unknown")[:30],
                        f"[{risk_style}]{risk}[/{risk_style}]",
                        action,
                    )

                console.print(table)

            console.print(
                "\n[dim]Use identark approvals inspect/approve/reject in another terminal[/dim]"
            )

            # Simple input handling (would be more sophisticated in real implementation)
            time.sleep(refresh)
            console.clear()

    except KeyboardInterrupt:
        console.print("\n[dim]Stopped watching[/dim]")


def _risk_style(score: int) -> str:
    """Get Rich style for risk score"""
    if score >= 70:
        return "red bold"
    elif score >= 40:
        return "yellow"
    else:
        return "green"


def _time_since(iso_timestamp: str) -> str:
    """Convert ISO timestamp to human-readable time since"""
    from datetime import datetime

    try:
        dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        delta = datetime.now(dt.tzinfo) - dt

        if delta.days > 0:
            return f"{delta.days}d ago"
        elif delta.seconds > 3600:
            return f"{delta.seconds // 3600}h ago"
        elif delta.seconds > 60:
            return f"{delta.seconds // 60}m ago"
        else:
            return "just now"
    except (TypeError, ValueError):
        return "unknown"


_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)


def _redact_sensitive(value: Any) -> Any:
    """Return a display-safe copy of nested tool arguments."""
    if isinstance(value, dict):
        return {
            key: (
                "*** REDACTED ***"
                if any(part in str(key).lower() for part in _SENSITIVE_KEY_PARTS)
                else _redact_sensitive(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value
