"""
Credential management commands
"""

from __future__ import annotations

import os
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from identark_cli.core.auth import get_api_client
from identark_cli.core.config import CredentialRef, load_config, save_config

console = Console()
app = typer.Typer(help="Credential references, scanning, and local injection")


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
        raise typer.Exit(1) from None

    if not config.credentials:
        console.print("No credentials configured")
        console.print("Run: [cyan]identark credential add <name>[/cyan]")
        return

    table = Table(title="Project Credential References")
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
    ref: str | None = typer.Option(
        None, "--ref", "-r", help="Vault reference (e.g., vault://prod/openai)"
    ),
    description: str | None = typer.Option(None, "--description", "-d", help="Description"),
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
        raise typer.Exit(1) from None

    # Determine reference
    if env and ref:
        console.print("[red]Provide exactly one of --ref or --env.[/red]")
        raise typer.Exit(2)
    if env:
        ref = f"env://{name}"
    elif not ref:
        console.print("[red]Provide exactly one of --ref or --env.[/red]")
        raise typer.Exit(2)

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
    try:
        credential = CredentialRef(
            name=name,
            ref=ref,
            required=required,
            description=description,
        )
    except ValueError as exc:
        console.print(f"[red]Invalid credential reference:[/red] {exc}")
        raise typer.Exit(2) from None
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
        raise typer.Exit(1) from None

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

    if strict:
        raise typer.Exit(1)


@app.command("install-hook")
def install_hook() -> None:
    """Install a fail-closed IdentArk pre-commit secret scan hook."""
    from identark_cli.core.config import get_project_root
    from identark_cli.core.scanner import install_git_hook

    root = get_project_root()
    if root is None:
        console.print("[red]No IdentArk project found. Run 'identark init' first.[/red]")
        raise typer.Exit(1)
    try:
        install_git_hook(root)
    except Exception as exc:
        console.print(f"[red]Could not install hook:[/red] {exc}")
        raise typer.Exit(1) from None

    config = load_config()
    config.enable_git_hooks = True
    save_config(config)
    console.print("[green]✓ Installed fail-closed pre-commit secret scanner[/green]")


@app.command()
def inject(
    command: list[str] = typer.Argument(..., help="Command to run with injected credentials"),
) -> None:
    """
    Inject credentials into a process

    Fetches credentials from IdentArk vault and injects them as
    environment variables. Credentials are masked from process listings.

    Examples:
        identark credential inject -- python my_script.py

    IdentArk deliberately does not write resolved credentials to env files.
    They exist only in this process and the child process for its lifetime.
    """
    import subprocess

    try:
        config = load_config()
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

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
                    raise typer.Exit(1) from None
                console.print(f"[yellow]Warning:[/yellow] Could not fetch {cred.name}")

    # Run command with injected environment
    console.print(f"Running: [cyan]{' '.join(command)}[/cyan]")
    console.print("[dim]Credentials injected (masked)[/dim]\n")

    result = subprocess.run(command, env=env_vars)
    raise typer.Exit(result.returncode)


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
            response = client.get("/v1/credentials/resolve", params={"path": path})
            response.raise_for_status()
            data = response.json()
            if data.get("fields") is not None:
                raise ValueError(
                    "Structured credentials cannot be injected into an environment variable. "
                    "Use an IdentArk managed connector instead."
                )
            value = data.get("value")
            if not isinstance(value, str) or not value:
                raise ValueError("IdentArk returned an empty credential value")
            return value

    raise ValueError(f"Unknown credential reference format: {ref}")
