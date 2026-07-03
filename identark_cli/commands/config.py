"""
Configuration management commands
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from identark_cli.core.config import (
    GLOBAL_CONFIG_FILE,
    PROJECT_CONFIG_FILE,
    load_config,
    load_global_config,
    save_config,
    save_global_config,
)

console = Console()
app = typer.Typer(help="Configuration management")


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
        config = load_global_config()
        console.print("[bold]Global Configuration[/bold]\n")
        console.print(f"Config file: [dim]{GLOBAL_CONFIG_FILE}[/dim]\n")

        table = Table()
        table.add_column("Setting", style="cyan")
        table.add_column("Value")

        table.add_row("API URL", config.api_url)
        table.add_row("Authenticated", str(config.is_authenticated))
        table.add_row("User Email", config.user_email or "-")
        table.add_row("Default Org", config.default_org_id or "-")
        table.add_row("Auto-approve Threshold", str(config.auto_approve_threshold))

        console.print(table)
    else:
        try:
            config = load_config()
            console.print("[bold]Project Configuration[/bold]\n")
            console.print(f"Config file: [dim]{PROJECT_CONFIG_FILE}[/dim]\n")

            table = Table()
            table.add_column("Setting", style="cyan")
            table.add_column("Value")

            table.add_row("Project Name", config.project_name or "-")
            table.add_row("Organization ID", config.organization_id or "-")
            table.add_row("Credentials", str(len(config.credentials)))
            table.add_row("Git Hooks", "Enabled" if config.enable_git_hooks else "Disabled")
            table.add_row("Scan on Commit", "Enabled" if config.scan_on_commit else "Disabled")

            console.print(table)

            if config.credentials:
                console.print("\n[bold]Credentials:[/bold]")
                for cred in config.credentials:
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
        identark config set --global auto_approve_threshold 40
    """
    if global_config:
        config = load_global_config()

        # Handle nested keys
        if "." in key:
            section, prop = key.split(".", 1)
            if hasattr(config, section):
                section_obj = getattr(config, section)
                if hasattr(section_obj, prop):
                    setattr(section_obj, prop, _convert_value(value))
                else:
                    console.print(f"[red]Unknown config key: {key}[/red]")
                    return
        else:
            if hasattr(config, key):
                setattr(config, key, _convert_value(value))
            else:
                console.print(f"[red]Unknown config key: {key}[/red]")
                return

        save_global_config(config)
        console.print(f"[green]✓ Updated global config:[/green] {key} = {value}")
    else:
        try:
            config = load_config()
        except Exception:
            console.print("[red]No project found. Run 'identark init' first.[/red]")
            return

        if hasattr(config, key):
            setattr(config, key, _convert_value(value))
            save_config(config)
            console.print(f"[green]✓ Updated project config:[/green] {key} = {value}")
        else:
            console.print(f"[red]Unknown config key: {key}[/red]")


@app.command("get")
def get_config(
    key: str = typer.Argument(..., help="Configuration key"),
    global_config: bool = typer.Option(False, "--global", "-g", help="Get from global config"),
) -> None:
    """
    Get a configuration value

    Retrieves a specific configuration value.
    """
    if global_config:
        config = load_global_config()
    else:
        try:
            config = load_config()
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            return

    if hasattr(config, key):
        value = getattr(config, key)
        console.print(value)
    else:
        console.print(f"[red]Unknown config key: {key}[/red]")


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
        config_file = PROJECT_CONFIG_FILE

    editor = os.environ.get("EDITOR", "vim")

    try:
        subprocess.run([editor, str(config_file)], check=True)
        console.print(f"[green]✓ Edited {config_file}[/green]")
    except Exception as e:
        console.print(f"[red]Could not open editor:[/red] {e}")


def _convert_value(value: str):
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
