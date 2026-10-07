"""Human approval commands."""

from __future__ import annotations

import json
import time

import typer
from rich import box
from rich.panel import Panel
from rich.table import Table

from identark_cli.core.auth import get_api_client
from identark_cli.ui import console, error_console
from identark_cli.ui.components import (
    render_empty_state,
    render_error,
    render_success,
    render_warning,
)
from identark_cli.ui.safety import redact_sensitive as _redact_sensitive
from identark_cli.ui.safety import safe_rich_text as _safe_display_text

app = typer.Typer(help="Human approvals for sensitive operations")


@app.command("list")
def list_approvals(
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum results"),
) -> None:
    """
    List approval requests

    Shows sensitive operations waiting for human review.
    """
    try:
        if limit < 1 or limit > 100:
            render_error(error_console, "--limit must be between 1 and 100.")
            raise typer.Exit(2)
        with get_api_client() as client:
            response = client.get("/v1/mcp/approvals/pending")
            response.raise_for_status()
            approvals = response.json()[:limit]
    except typer.Exit:
        raise
    except Exception:
        render_error(
            error_console,
            "Could not load pending approvals.",
            explanation="Check your connection and account permissions.",
            next_step="identark auth status",
        )
        raise typer.Exit(1) from None

    if not approvals:
        render_empty_state(
            console,
            "No pending approvals",
            "Sensitive agent operations that need your review will appear here.",
            next_step="identark approvals watch",
        )
        return

    table = Table(title=f"Pending Approvals ({len(approvals)})", box=box.ROUNDED)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Tool")
    table.add_column("Risk")
    table.add_column("Requested By")
    table.add_column("Age")

    for approval in approvals:
        risk_score = _coerce_risk_score(approval.get("risk_score"))
        risk_style = _risk_style(risk_score)

        # Calculate age
        created = approval.get("created_at", "")
        age = _time_since(created)

        table.add_row(
            _safe_display_text(approval.get("id", "unknown"))[:8],
            _safe_display_text(approval.get("tool_name", "unknown")),
            f"[{risk_style}]{risk_score}[/{risk_style}]",
            _safe_display_text(approval.get("requested_by", "unknown")),
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
    except Exception:
        render_error(
            error_console,
            "Could not load this approval request.",
            explanation="It may have expired, been decided, or be outside your access scope.",
            next_step="identark approvals list",
        )
        raise typer.Exit(1) from None

    # Build detail panel
    risk_score = _coerce_risk_score(approval.get("risk_score"))
    risk_level = _safe_display_text(approval.get("risk_level", "unknown"))
    risk_style = _risk_style(risk_score)

    safe_arguments = _safe_display_text(
        json.dumps(_redact_sensitive(approval.get("tool_arguments", {})), indent=2),
        max_length=4000,
    )
    content = f"""
[bold]Tool:[/bold]         {_safe_display_text(approval.get("tool_name", "unknown"))}
[bold]Status:[/bold]       {_safe_display_text(approval.get("status", "unknown"))}
[bold]Risk Score:[/bold]   [{risk_style}]{risk_score} ({risk_level})[/{risk_style}]
[bold]Requested By:[/bold] {_safe_display_text(approval.get("requested_by", "unknown"))}
[bold]Created:[/bold]      {_safe_display_text(approval.get("created_at", "unknown"))}
[bold]Expires:[/bold]      {_safe_display_text(approval.get("expires_at", "unknown"))}

[bold]Risk Explanation:[/bold]
{_safe_display_text(approval.get("risk_explanation", "No explanation available"))}

[bold]Tool Arguments:[/bold]
```json
{safe_arguments}
```
    """

    console.print(
        Panel(
            content,
            title=f"Approval Request: {_safe_display_text(approval_id)}",
            border_style="cyan",
        )
    )

    if approval.get("status") == "pending":
        console.print("\n[bold]Actions:[/bold]")
        safe_approval_id = _safe_display_text(approval_id)
        console.print(f"  [cyan]identark approvals approve {safe_approval_id}[/cyan]")
        console.print(f"  [cyan]identark approvals reject {safe_approval_id} --reason '...'[/cyan]")


@app.command()
def approve(
    approval_id: str = typer.Argument(..., help="Approval request ID"),
    comment: str | None = typer.Option(None, "--comment", "-c", help="Approval comment"),
    mfa_code: str | None = typer.Option(None, "--mfa", help="MFA code (required for high risk)"),
) -> None:
    """
    Approve a pending request

    Allows the reviewed agent operation to proceed.
    High-risk operations (>70) require MFA verification.
    """
    try:
        with get_api_client() as client:
            # Get approval details first to check risk
            response = client.get(f"/v1/mcp/approvals/{approval_id}")
            response.raise_for_status()
            approval = response.json()

            # Check if MFA required
            if _coerce_risk_score(approval.get("risk_score")) >= 70 and not mfa_code:
                render_warning(console, "This operation requires MFA verification.")
                mfa_code = typer.prompt("Enter MFA code", hide_input=True)

            # Submit approval
            payload = {"decision": "approved", "comment": comment, "mfa_token": mfa_code}

            response = client.post(f"/v1/mcp/approvals/{approval_id}/decision", json=payload)
            response.raise_for_status()

        render_success(console, f"Approved request {_safe_display_text(approval_id)}")

        if approval.get("tool_name"):
            console.print(f"  Tool: [cyan]{_safe_display_text(approval['tool_name'])}[/cyan]")

    except Exception:
        render_error(
            error_console,
            "Could not approve this request.",
            explanation="The request may have expired or require different authorization.",
            next_step=f"identark approvals inspect {_safe_display_text(approval_id)}",
        )
        raise typer.Exit(1) from None


@app.command()
def reject(
    approval_id: str = typer.Argument(..., help="Approval request ID"),
    reason: str = typer.Option(..., "--reason", "-r", help="Rejection reason"),
) -> None:
    """
    Reject a pending request

    Prevents the reviewed agent operation from running.
    """
    try:
        with get_api_client() as client:
            payload = {"decision": "rejected", "comment": reason}

            response = client.post(f"/v1/mcp/approvals/{approval_id}/decision", json=payload)
            response.raise_for_status()

        render_success(console, f"Rejected request {_safe_display_text(approval_id)}")
        console.print("  Reason recorded; the operation will not run.")

    except Exception:
        render_error(
            error_console,
            "Could not reject this request.",
            explanation="The request may have expired or already been decided.",
            next_step=f"identark approvals inspect {_safe_display_text(approval_id)}",
        )
        raise typer.Exit(1) from None


@app.command()
def watch(
    refresh: int = typer.Option(5, "--refresh", help="Refresh interval in seconds"),
) -> None:
    """
    Watch approvals in real-time

    Monitor approval requests as they arrive. Use approve, reject, or inspect
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
            except Exception:
                render_warning(
                    console,
                    "Could not refresh approvals.",
                    next_step="Check your connection or press Ctrl+C to stop",
                )
                time.sleep(refresh)
                continue

            # Build display
            if not approvals:
                table = Table(box=box.ROUNDED)
                table.add_column("Status", justify="center")
                table.add_row("[dim]No pending approvals[/dim]")
                console.print(table)
            else:
                table = Table(title=f"{len(approvals)} Pending Approvals", box=box.ROUNDED)
                table.add_column("ID", style="cyan")
                table.add_column("Tool")
                table.add_column("Risk", justify="right")
                table.add_column("Action Required")

                for approval in approvals:
                    risk = _coerce_risk_score(approval.get("risk_score"))
                    risk_style = _risk_style(risk)

                    if risk >= 70:
                        action = "[red]MFA required[/red]"
                    else:
                        action = "[yellow]Review needed[/yellow]"

                    table.add_row(
                        _safe_display_text(approval.get("id", "unknown"))[:8],
                        _safe_display_text(approval.get("tool_name", "unknown"), max_length=30),
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


def _coerce_risk_score(value: object) -> int:
    """Normalize untrusted API risk values for display and policy hints."""
    if isinstance(value, bool):
        return 0
    if not isinstance(value, (int, float, str)):
        return 0
    try:
        score = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, min(score, 100))


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
