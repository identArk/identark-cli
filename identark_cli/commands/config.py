"""
Configuration management commands
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from identark_cli.core.config import (
    GLOBAL_CONFIG_FILE,
    PROJECT_CONFIG_FILE,
    get_project_root,
    load_config,
    load_global_config,
    save_config,
    save_global_config,
)

console = Console()
app = typer.Typer(help="Configuration management")

_GLOBAL_EDITABLE_KEYS = {"api_url", "color_output", "default_org_id"}
_PROJECT_EDITABLE_KEYS = {
    "default_agent_template",
    "enable_git_hooks",
    "organization_id",
    "project_name",
    "scan_on_commit",
}


@app.command("show")
def show_config(
    global_config: bool = typer.Option(False, "--global", "-g", help="Show global config"),
) -> None:
    """
    Show current configuration

    Displays the effective configuration for this project
    or global settings.
    """
    if global_config:
        global_values = load_global_config()
        console.print("[bold]Global Configuration[/bold]\n")
        console.print(f"Config file: [dim]{GLOBAL_CONFIG_FILE}[/dim]\n")

        table = Table()
        table.add_column("Setting", style="cyan")
        table.add_column("Value")

        table.add_row("API URL", global_values.api_url)
        table.add_row("Authenticated", str(global_values.is_authenticated))
        table.add_row("User Email", global_values.user_email or "-")
        table.add_row("Default Org", global_values.default_org_id or "-")

        console.print(table)
    else:
        try:
            project_values = load_config()
            console.print("[bold]Project Configuration[/bold]\n")
            console.print(f"Config file: [dim]{_project_config_path()}[/dim]\n")

            table = Table()
            table.add_column("Setting", style="cyan")
            table.add_column("Value")

            table.add_row("Project Name", project_values.project_name or "-")
            table.add_row("Organization ID", project_values.organization_id or "-")
            table.add_row("Credentials", str(len(project_values.credentials)))
            table.add_row("Git Hooks", "Enabled" if project_values.enable_git_hooks else "Disabled")
            table.add_row(
                "Scan on Commit", "Enabled" if project_values.scan_on_commit else "Disabled"
            )

            console.print(table)

            if project_values.credentials:
                console.print("\n[bold]Credentials:[/bold]")
                for cred in project_values.credentials:
                    console.print(f"  • [cyan]{cred.name}[/cyan]: {cred.ref}")

        except Exception:
            console.print("[yellow]No project configuration found[/yellow]")
            console.print("Run: [cyan]identark init[/cyan]")


@app.command("set")
def set_config(
    key: str = typer.Argument(..., help="Configuration key"),
    value: str = typer.Argument(..., help="Configuration value"),
    global_config: bool = typer.Option(False, "--global", "-g", help="Set global config"),
) -> None:
    """
    Set a configuration value

    Updates the project or global configuration.

    Examples:
        identark config set project_name "My Agent"
        identark config set --global api_url https://api.identark.io
    """
    try:
        if global_config:
            if key not in _GLOBAL_EDITABLE_KEYS:
                raise ValueError(f"Unknown or protected global config key: {key}")
            global_values = load_global_config()
            setattr(global_values, key, _convert_value(value))
            save_global_config(global_values)
            scope = "global"
        else:
            if key not in _PROJECT_EDITABLE_KEYS:
                raise ValueError(f"Unknown or protected project config key: {key}")
            project_values = load_config()
            setattr(project_values, key, _convert_value(value))
            save_config(project_values)
            scope = "project"
    except Exception as exc:
        console.print(f"[red]Could not update config:[/red] {exc}")
        raise typer.Exit(2) from None

    console.print(f"[green]✓ Updated {scope} config:[/green] {key} = {value}")


@app.command("get")
def get_config(
    key: str = typer.Argument(..., help="Configuration key"),
    global_config: bool = typer.Option(False, "--global", "-g", help="Get from global config"),
) -> None:
    """
    Get a configuration value

    Retrieves a specific configuration value.
    """
    try:
        if global_config:
            if key not in _GLOBAL_EDITABLE_KEYS | {"user_email", "user_id"}:
                raise ValueError(f"Unknown or protected global config key: {key}")
            value = getattr(load_global_config(), key)
        else:
            if key not in _PROJECT_EDITABLE_KEYS | {"version"}:
                raise ValueError(f"Unknown or protected project config key: {key}")
            value = getattr(load_config(), key)
    except Exception as exc:
        console.print(f"[red]Could not read config:[/red] {exc}")
        raise typer.Exit(2) from None

    console.print(value)


@app.command("edit")
def edit_config(
    global_config: bool = typer.Option(False, "--global", "-g", help="Edit global config"),
) -> None:
    """
    Open configuration in editor

    Opens the configuration file in your default editor.
    """
    import os
    import subprocess

    if global_config:
        config_file = GLOBAL_CONFIG_FILE
    else:
        try:
            config_file = _project_config_path()
        except Exception as exc:
            console.print(f"[red]Could not find project config:[/red] {exc}")
            raise typer.Exit(1) from None

    editor = os.environ.get("EDITOR", "vim")

    try:
        subprocess.run([editor, str(config_file)], check=True)
        console.print(f"[green]✓ Edited {config_file}[/green]")
    except Exception as e:
        console.print(f"[red]Could not open editor:[/red] {e}")
        raise typer.Exit(1) from None


def _project_config_path() -> Path:
    root = get_project_root()
    if root is None:
        raise ValueError("No IdentArk project found. Run 'identark init' first.")
    return root / PROJECT_CONFIG_FILE


def _convert_value(value: str) -> Any:
    """Convert string value to appropriate type"""
    # Try bool
    if value.lower() in ("true", "yes", "1"):
        return True
    if value.lower() in ("false", "no", "0"):
        return False

    # Try int
    try:
        return int(value)
    except ValueError:
        pass

    # Try float
    try:
        return float(value)
    except ValueError:
        pass

    # Return as string
    return value
