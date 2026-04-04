"""
HITL Approval commands
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich import box

from identark_cli.core.auth import get_api_client

console = Console()
app = typer.Typer(help="HITL approval workflow")


@app.command("list")
def list_approvals(
    status: str = typer.Option("pending", "--status", "-s", help="Filter by status"),
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum results"),
) -> None:
    """
    List approval requests
    
    Shows pending, approved, or rejected HITL requests.
    """
    try:
        with get_api_client() as client:
            response = client.get(f"/v1/mcp/approvals/pending?limit={limit}")
            response.raise_for_status()
            approvals = response.json()
    except Exception as e:
        console.print(f"[red]Error fetching approvals:[/red] {e}")
        raise typer.Exit(1)
    
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
            age
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
        raise typer.Exit(1)
    
    # Build detail panel
    risk_score = approval.get("risk_score", 0)
    risk_level = approval.get("risk_level", "unknown")
    risk_style = _risk_style(risk_score)
    
    content = f"""
[bold]Tool:[/bold]         {approval.get('tool_name', 'unknown')}
[bold]Status:[/bold]       {approval.get('status', 'unknown')}
[bold]Risk Score:[/bold]   [{risk_style}]{risk_score} ({risk_level})[/{risk_style}]
[bold]Requested By:[/bold] {approval.get('requested_by', 'unknown')}
[bold]Created:[/bold]      {approval.get('created_at', 'unknown')}
[bold]Expires:[/bold]      {approval.get('expires_at', 'unknown')}

[bold]Risk Explanation:[/bold]
{approval.get('risk_explanation', 'No explanation available')}

[bold]Tool Arguments:[/bold]
```json
{approval.get('tool_arguments', {})}
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
    comment: Optional[str] = typer.Option(None, "--comment", "-c", help="Approval comment"),
    mfa_code: Optional[str] = typer.Option(None, "--mfa", help="MFA code (required for high risk)"),
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
            payload = {
                "decision": "approved",
                "comment": comment,
                "mfa_token": mfa_code
            }
            
            response = client.post(
                f"/v1/mcp/approvals/{approval_id}/decision",
                json=payload
            )
            response.raise_for_status()
        
        console.print(f"[green]✓ Approved request {approval_id}[/green]")
        
        if approval.get("tool_name"):
            console.print(f"  Tool: [cyan]{approval['tool_name']}[/cyan]")
    
    except Exception as e:
        console.print(f"[red]Approval failed:[/red] {e}")
        raise typer.Exit(1)


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
            payload = {
                "decision": "rejected",
                "comment": reason
            }
            
            response = client.post(
                f"/v1/mcp/approvals/{approval_id}/decision",
                json=payload
            )
            response.raise_for_status()
        
        console.print(f"[yellow]✗ Rejected request {approval_id}[/yellow]")
        console.print(f"  Reason: {reason}")
    
    except Exception as e:
        console.print(f"[red]Rejection failed:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def watch(
    refresh: int = typer.Option(5, "--refresh", help="Refresh interval in seconds"),
    auto_approve: bool = typer.Option(False, "--auto-approve", help="Auto-approve low-risk (<30)"),
) -> None:
    """
    Watch approvals in real-time
    
    Interactive terminal UI for monitoring and approving
    HITL requests as they arrive.
    """
    console.print("[bold]Watching for approval requests...[/bold]")
    console.print("[dim]Press Ctrl+C to exit[/dim]\n")
    
    try:
        while True:
            # Fetch pending approvals
            try:
                with get_api_client() as client:
                    response = client.get("/v1/mcp/approvals/pending?limit=10")
                    response.raise_for_status()
                    approvals = response.json()
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
                    
                    # Auto-approve low risk if enabled
                    if auto_approve and risk < 30:
                        _auto_approve(approval["id"])
                        action = "[green]Auto-approved[/green]"
                    else:
                        if risk >= 70:
                            action = "[red]MFA required[/red]"
                        else:
                            action = "[yellow]Review needed[/yellow]"
                    
                    table.add_row(
                        approval["id"][:8],
                        approval.get("tool_name", "unknown")[:30],
                        f"[{risk_style}]{risk}[/{risk_style}]",
                        action
                    )
                
                console.print(table)
            
            # Show controls
            console.print("\n[dim]Commands: approve <id> | reject <id> | inspect <id> | quit[/dim]")
            
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
    except:
        return "unknown"


def _auto_approve(approval_id: str) -> None:
    """Auto-approve a low-risk request"""
    try:
        with get_api_client() as client:
            payload = {
                "decision": "approved",
                "comment": "Auto-approved (low risk)"
            }
            client.post(f"/v1/mcp/approvals/{approval_id}/decision", json=payload)
    except:
        pass
