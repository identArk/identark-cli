"""Read-only access to the authoritative IdentArk audit log."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from identark_cli.core.audit_evidence import AuditEvidenceError, verify_evidence_bundle
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


@app.command("export")
def export_audit_evidence(
    output: Path = typer.Option(
        Path("identark-approval-evidence.json"),
        "--output",
        "-o",
        help="Where to write the portable approval evidence bundle",
    ),
    force: bool = typer.Option(False, "--force", help="Replace an existing evidence file"),
) -> None:
    """Export non-secret HITL decision evidence for independent review.

    The bundle contains the fields protected by the approval hash chain, never
    tool arguments, prompts, outputs, credentials, or capability tokens.
    """
    if output.exists() and not force:
        console.print(f"[red]Evidence file already exists:[/red] {output}")
        console.print("Use --force only after reviewing the existing file.")
        raise typer.Exit(2)
    try:
        with get_api_client() as client:
            response = client.get("/v1/mcp/audit/chain/evidence")
            response.raise_for_status()
            bundle = response.json()
        verification = verify_evidence_bundle(bundle)
        if not verification.valid:
            raise AuditEvidenceError("server returned evidence that did not verify")
        output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:
        # Avoid printing response bodies or exception text: evidence commands
        # must remain safe even when a proxy returns unexpected sensitive data.
        console.print(
            "[red]Could not export audit evidence.[/red] Check your sign-in and try again."
        )
        raise typer.Exit(1) from None

    console.print("[green]✓ Approval evidence exported[/green]")
    console.print(f"  File: [cyan]{output}[/cyan]")
    console.print(f"  Records: {verification.records_checked}")
    console.print(f"  Verify offline: [cyan]identark audit verify {output}[/cyan]")
    console.print(
        "[dim]This proves integrity of supplied records, not that an exporter included every "
        "historical record or that the file originated from a particular server.[/dim]"
    )


@app.command("verify")
def verify_audit_evidence(
    evidence: Path = typer.Argument(
        ..., exists=True, readable=True, help="Evidence JSON file to verify"
    ),
) -> None:
    """Verify a supplied approval evidence bundle locally, without an API call."""
    try:
        bundle = json.loads(evidence.read_text(encoding="utf-8"))
        verification = verify_evidence_bundle(bundle)
    except (OSError, json.JSONDecodeError, AuditEvidenceError):
        console.print(
            "[red]Evidence could not be verified.[/red] Check that the file is intact JSON."
        )
        raise typer.Exit(1) from None

    if not verification.valid:
        console.print("[red]Evidence integrity check failed.[/red]")
        console.print(f"  Records checked: {verification.records_checked}")
        if verification.failure_position is not None:
            console.print(f"  First failing record: {verification.failure_position + 1}")
        console.print(f"  Reason: {verification.failure_reason}")
        raise typer.Exit(1)

    console.print("[green]✓ Evidence integrity verified[/green]")
    console.print(f"  Records checked: {verification.records_checked}")
    console.print(f"  Chain head: {verification.head_hash or 'empty chain'}")
    console.print(
        "[dim]This verifies the supplied records' hashes and order offline. It cannot prove "
        "whether other records were omitted or attest the source of this file.[/dim]"
    )
