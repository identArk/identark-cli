"""
Credential management commands
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from identark_cli.core.auth import get_api_client
from identark_cli.core.config import CredentialRef, load_config, save_config

console = Console()
app = typer.Typer(help="Credential management")


@app.command("list")
def list_credentials() -> None:
    """
    List configured credentials

    Shows all credentials registered for this project.
    """
    try:
        config = load_config()
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    if not config.credentials:
        console.print("No credentials configured")
        console.print("Run: [cyan]identark credential add <name>[/cyan]")
        return

    table = Table(title="Configured Credentials")
    table.add_column("Name", style="cyan")
    table.add_column("Reference")
    table.add_column("Required")
    table.add_column("Description")

    for cred in config.credentials:
        table.add_row(cred.name, cred.ref, "✓" if cred.required else "", cred.description or "")

    console.print(table)


@app.command()
def add(
    name: str = typer.Argument(..., help="Credential name"),
    ref: Optional[str] = typer.Option(
        None, "--ref", "-r", help="Vault reference (e.g., vault://prod/openai)"
    ),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Description"),
    required: bool = typer.Option(
        True, "--required/--optional", help="Whether credential is required"
    ),
    env: bool = typer.Option(False, "--env", "-e", help="Use environment variable as reference"),
) -> None:
    """
    Add a credential reference to the project

    Creates a reference to a credential stored in IdentArk vault.
    The actual secret is never stored locally.

    Examples:
        identark credential add OPENAI_API_KEY --ref vault://prod/openai
        identark credential add AWS_KEY --env
    """
    try:
        config = load_config()
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    # Determine reference
    if env:
        ref = f"env://{name}"
    elif not ref:
        # Interactive selection from vault
        ref = _select_from_vault()

    # Check if already exists
    for existing in config.credentials:
        if existing.name == name:
            console.print(f"[yellow]Credential '{name}' already exists[/yellow]")
            overwrite = typer.confirm("Overwrite?")
            if not overwrite:
                return
            config.credentials.remove(existing)
            break

    # Add new credential
    credential = CredentialRef(name=name, ref=ref, required=required, description=description)
    config.credentials.append(credential)
    save_config(config)

    console.print(f"✓ Added credential [cyan]{name}[/cyan]")
    console.print(f"  Reference: {ref}")


@app.command()
def remove(
    name: str = typer.Argument(..., help="Credential name"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """
    Remove a credential reference

    Removes the local reference. The actual secret in vault is not affected.
    """
    try:
        config = load_config()
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    # Find credential
    for cred in config.credentials:
        if cred.name == name:
            if not force:
                confirm = typer.confirm(f"Remove credential '{name}'?")
                if not confirm:
                    console.print("Cancelled")
                    return

            config.credentials.remove(cred)
            save_config(config)
            console.print(f"✓ Removed credential [cyan]{name}[/cyan]")
            return

    console.print(f"[red]Credential '{name}' not found[/red]")
    raise typer.Exit(1)


@app.command()
def scan(
    path: Path = typer.Option(".", "--path", "-p", help="Path to scan"),
    fix: bool = typer.Option(False, "--fix", help="Attempt to fix found secrets"),
    strict: bool = typer.Option(False, "--strict", help="Exit with error if secrets found"),
) -> None:
    """
    Scan for secrets in code

    Detects potential secrets, API keys, and credentials in source files.
    Integrates with git hooks to prevent commits with secrets.
    """
    from identark_cli.core.scanner import scan_directory

    console.print(f"Scanning [cyan]{path}[/cyan] for secrets...")

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console
    ) as progress:
        progress.add_task("Scanning...", total=None)
        findings = scan_directory(path)
        progress.stop()

    if not findings:
        console.print("[green]✓ No secrets found[/green]")
        return

    # Display findings
    table = Table(title=f"Found {len(findings)} potential secret(s)")
    table.add_column("File", style="cyan")
    table.add_column("Line")
    table.add_column("Type")
    table.add_column("Preview")

    for finding in findings:
        table.add_row(str(finding.file), str(finding.line), finding.secret_type, finding.preview)

    console.print(table)

    if fix:
        console.print("\n[yellow]Auto-fix not yet implemented[/yellow]")
        console.print("Manual fix required for each finding")

    if strict:
        raise typer.Exit(1)


@app.command()
def inject(
    command: list[str] = typer.Argument(..., help="Command to run with injected credentials"),
    env_file: Optional[Path] = typer.Option(
        None, "--env-file", help="Write credentials to env file"
    ),
) -> None:
    """
    Inject credentials into a process

    Fetches credentials from IdentArk vault and injects them as
    environment variables. Credentials are masked from process listings.

    Examples:
        identark credential inject -- python my_script.py
        identark credential inject --env-file .env -- npm start
    """
    import subprocess

    try:
        config = load_config()
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    # Fetch credentials from vault
    env_vars = os.environ.copy()

    with console.status("Fetching credentials from vault..."):
        for cred in config.credentials:
            try:
                value = _fetch_credential_value(cred.ref)
                env_vars[cred.name] = value
            except Exception as e:
                if cred.required:
                    console.print(
                        f"[red]Failed to fetch required credential {cred.name}:[/red] {e}"
                    )
                    raise typer.Exit(1)
                console.print(f"[yellow]Warning:[/yellow] Could not fetch {cred.name}")

    # Write to env file if requested
    if env_file:
        with open(env_file, "w") as f:
            for cred in config.credentials:
                if cred.name in env_vars:
                    f.write(f"{cred.name}={env_vars[cred.name]}\n")
        console.print(f"✓ Wrote credentials to [cyan]{env_file}[/cyan]")
        return

    # Run command with injected environment
    console.print(f"Running: [cyan]{' '.join(command)}[/cyan]")
    console.print("[dim]Credentials injected (masked)[/dim]\n")

    result = subprocess.run(command, env=env_vars)
    raise typer.Exit(result.returncode)


def _select_from_vault() -> str:
    """Interactive selection of credential from vault"""
    # TODO: Implement vault credential listing
    console.print("Enter vault reference manually:")
    ref = typer.prompt("Reference (e.g., vault://prod/openai)")
    return ref


def _fetch_credential_value(ref: str) -> str:
    """Fetch credential value from vault"""
    # Handle env:// references
    if ref.startswith("env://"):
        env_var = ref[6:]
        value = os.environ.get(env_var)
        if value is None:
            raise ValueError(f"Environment variable {env_var} not set")
        return value

    # Handle vault:// references
    if ref.startswith("vault://"):
        path = ref[8:]  # Remove vault:// prefix

        with get_api_client() as client:
            response = client.get(f"/v1/credentials/resolve?path={path}")
            response.raise_for_status()
            data = response.json()
            return data["value"]

    raise ValueError(f"Unknown credential reference format: {ref}")
