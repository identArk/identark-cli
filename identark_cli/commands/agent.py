"""
Agent development and execution commands
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from identark_cli.core.auth import get_api_client
from identark_cli.core.config import ProjectConfig, load_config, save_config

console = Console()
app = typer.Typer(help="Agent development and execution")


@app.command()
def init(
    name: str = typer.Option(..., "--name", "-n", help="Agent name"),
    template: str = typer.Option("basic", "--template", "-t", help="Agent template"),
    path: Path = typer.Option(".", "--path", "-p", help="Project path"),
) -> None:
    """
    Initialize a new agent project

    Creates agent configuration, sample code, and sets up
    credential isolation.

    Templates:
        basic       - Minimal agent structure
        slack-bot   - Slack bot with IdentArk integration
        api-service - FastAPI service with isolated credentials
    """
    project_path = Path(path) / name

    if project_path.exists():
        console.print(f"[red]Directory {project_path} already exists[/red]")
        raise typer.Exit(1)

    # Create project structure
    project_path.mkdir(parents=True)
    (project_path / "src").mkdir()
    (project_path / ".identark").mkdir()

    # Create config
    config = ProjectConfig(project_name=name, default_agent_template=template)
    save_config(config, project_path / ".identark" / "config.toml")

    # Create sample files based on template
    if template == "slack-bot":
        _create_slack_bot_template(project_path, name)
    elif template == "api-service":
        _create_api_service_template(project_path, name)
    else:
        _create_basic_template(project_path, name)

    console.print(
        Panel.fit(
            f"[green]✓ Created agent project: {name}[/green]\n"
            f"\n[bold]Next steps:[/bold]"
            f"\n  cd {project_path}"
            f"\n  identark credential add SLACK_TOKEN --ref vault://prod/slack"
            f"\n  identark agent run"
        )
    )


@app.command()
def run(
    script: Optional[Path] = typer.Argument(None, help="Agent script to run"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Restart on file changes"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug mode"),
) -> None:
    """
    Run an agent with isolated credentials

    Injects credentials from IdentArk vault and runs the agent
    with full isolation. High-risk operations trigger HITL prompts.
    """
    try:
        config = load_config()
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    # Determine entry point
    if script:
        entry_point = script
    elif Path("main.py").exists():
        entry_point = Path("main.py")
    elif Path("app.py").exists():
        entry_point = Path("app.py")
    else:
        console.print("[red]No entry point found[/red]")
        console.print("Specify a script or create main.py")
        raise typer.Exit(1)

    # Fetch credentials
    env_vars = os.environ.copy()

    console.print("[bold]Starting agent with IdentArk isolation[/bold]\n")

    with console.status("Fetching credentials from vault..."):
        for cred in config.credentials:
            try:
                value = _fetch_credential_value(cred.ref)
                env_vars[cred.name] = value
                console.print(f"  ✓ [cyan]{cred.name}[/cyan] injected")
            except Exception as e:
                if cred.required:
                    console.print(f"  [red]✗ {cred.name}:[/red] {e}")
                    raise typer.Exit(1)
                console.print(f"  [yellow]⚠ {cred.name}:[/yellow] {e}")

    console.print()

    # Run the agent
    if watch:
        _run_with_watch(entry_point, env_vars, debug)
    else:
        _run_agent(entry_point, env_vars, debug)


@app.command()
def dev(
    port: int = typer.Option(8000, "--port", "-p", help="Port to run on"),
    reload: bool = typer.Option(True, "--reload/--no-reload", help="Auto-reload on changes"),
) -> None:
    """
    Start agent in development mode

    Runs the agent with hot reload, debug output, and
    local credential vault for rapid development.
    """
    console.print(
        Panel.fit(
            "[bold cyan]IdentArk Agent Development Mode[/bold cyan]\n"
            "Local credential vault active\n"
            "HITL prompts enabled for high-risk operations"
        )
    )

    # Check for common frameworks
    if Path("main.py").exists():
        cmd = [sys.executable, "-m", "uvicorn", "main:app", "--port", str(port)]
        if reload:
            cmd.append("--reload")
    elif Path("app.py").exists():
        cmd = [sys.executable, "app.py"]
    else:
        console.print("[red]No main.py or app.py found[/red]")
        raise typer.Exit(1)

    # Run with credentials injected
    from identark_cli.commands.credential import _fetch_credential_value

    try:
        config = load_config()
        env_vars = os.environ.copy()

        for cred in config.credentials:
            try:
                value = _fetch_credential_value(cred.ref)
                env_vars[cred.name] = value
            except:
                pass  # Dev mode allows missing credentials

        subprocess.run(cmd, env=env_vars)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def logs(
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    lines: int = typer.Option(100, "--lines", "-n", help="Number of lines to show"),
) -> None:
    """
    Show agent logs

    Displays recent agent execution logs from IdentArk.
    """
    console.print("[dim]Agent logs (from IdentArk cloud)...[/dim]\n")

    try:
        with get_api_client() as client:
            response = client.get(f"/v1/agents/logs?lines={lines}")
            response.raise_for_status()
            logs_data = response.json()

            for log in logs_data.get("logs", []):
                timestamp = log.get("timestamp", "")
                level = log.get("level", "INFO")
                message = log.get("message", "")

                color = "white"
                if level == "ERROR":
                    color = "red"
                elif level == "WARN":
                    color = "yellow"

                console.print(f"[{timestamp}] [{color}]{level}[/{color}] {message}")

    except Exception as e:
        console.print(f"[yellow]Could not fetch logs:[/yellow] {e}")
        console.print("Logs are stored locally in .identark/logs/")


@app.command()
def inspect(
    session_id: Optional[str] = typer.Argument(None, help="Session ID to inspect"),
) -> None:
    """
    Inspect agent session details

    Shows credential usage, HITL decisions, and audit trail
    for a specific agent session.
    """
    if not session_id:
        # List recent sessions
        try:
            with get_api_client() as client:
                response = client.get("/v1/agents/sessions")
                response.raise_for_status()
                sessions = response.json()

                table = Table(title="Recent Agent Sessions")
                table.add_column("Session ID", style="cyan")
                table.add_column("Started")
                table.add_column("Status")
                table.add_column("Actions")

                for session in sessions:
                    table.add_row(
                        session["id"],
                        session["started_at"],
                        session["status"],
                        str(session.get("action_count", 0)),
                    )

                console.print(table)
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
    else:
        # Show session details
        console.print(f"Session: [cyan]{session_id}[/cyan]")
        console.print("[dim]Detailed session inspection coming soon...[/dim]")


@app.command()
def list(
    all: bool = typer.Option(False, "--all", "-a", help="Include inactive/unboarded agents"),
) -> None:
    """
    List registered agents in IdentArk

    Shows all active agents by default. Use --all to include
    agents that have been unboarded (soft-deleted).
    """
    try:
        with get_api_client() as client:
            params = {}
            if not all:
                params["is_active"] = "true"
            response = client.get("/v1/agents", params=params)
            response.raise_for_status()
            agents = response.json()

            if not agents:
                console.print("[dim]No agents found.[/dim]")
                console.print("  Register one with: [cyan]identark agent init[/cyan]")
                return

            table = Table(title="IdentArk Agents")
            table.add_column("ID", style="cyan", no_wrap=True)
            table.add_column("Name")
            table.add_column("Agent Key", style="magenta")
            table.add_column("Model")
            table.add_column("Status")

            for agent in agents:
                status = (
                    "[green]🟢 active[/green]" if agent["is_active"] else "[red]🔴 unboarded[/red]"
                )
                table.add_row(
                    agent["id"],
                    agent["name"],
                    agent["agent_key"],
                    f"{agent['provider']}/{agent['model']}",
                    status,
                )

            console.print(table)
            console.print(f"\nTotal: {len(agents)} agent(s)")
            if not all:
                console.print("[dim]Use --all to see unboarded agents[/dim]")

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")


@app.command()
def delete(
    agent_id: str = typer.Argument(..., help="Agent UUID to unboard"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
) -> None:
    """
    Unboard (soft-delete) an agent from IdentArk

    This sets the agent's is_active flag to False. The agent's
    sessions and audit trail are preserved for compliance.
    To permanently remove data, contact your administrator.
    """
    if not force:
        confirm = typer.confirm(f"Unboard agent {agent_id}?")
        if not confirm:
            console.print("[yellow]Cancelled.[/yellow]")
            raise typer.Exit(0)

    try:
        with get_api_client() as client:
            response = client.delete(f"/v1/agents/{agent_id}")
            if response.status_code == 204:
                console.print(f"✓ Agent [cyan]{agent_id}[/cyan] unboarded successfully")
                console.print("  [dim]Sessions and audit trail preserved[/dim]")
            else:
                console.print(f"[red]Error {response.status_code}:[/red] {response.text}")
                raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


def _create_basic_template(path: Path, name: str) -> None:
    """Create basic agent template"""
    main_py = '''"""
Basic IdentArk Agent
"""
import os

# Credentials are injected by IdentArk - never hardcode!
API_KEY = os.environ.get("API_KEY")

def main():
    print(f"Agent running with isolated credentials")
    print(f"API_KEY loaded: {bool(API_KEY)}")
    # Your agent logic here

if __name__ == "__main__":
    main()
'''
    (path / "src" / "main.py").write_text(main_py)

    readme = f"""# {name}

IdentArk Agent Project

## Development

```bash
# Run with isolated credentials
identark agent run

# Or in dev mode with hot reload
identark agent dev
```

## Adding Credentials

```bash
identark credential add API_KEY --ref vault://prod/api
```
"""
    (path / "README.md").write_text(readme)


def _create_slack_bot_template(path: Path, name: str) -> None:
    """Create Slack bot template"""
    main_py = '''"""
Slack Bot with IdentArk Isolation
"""
import os
from slack_sdk import WebClient

SLACK_TOKEN = os.environ.get("SLACK_TOKEN")

client = WebClient(token=SLACK_TOKEN)

def handle_message(event):
    # Your bot logic here
    pass

if __name__ == "__main__":
    # Start bot
    print("Slack bot running with isolated credentials")
'''
    (path / "src" / "main.py").write_text(main_py)

    requirements = "slack-sdk>=3.0\n"
    (path / "requirements.txt").write_text(requirements)


def _create_api_service_template(path: Path, name: str) -> None:
    """Create API service template"""
    main_py = '''"""
FastAPI Service with IdentArk Isolation
"""
import os
from fastapi import FastAPI

app = FastAPI()
DB_URL = os.environ.get("DATABASE_URL")

@app.get("/")
def read_root():
    return {"status": "ok", "credentials_loaded": bool(DB_URL)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
'''
    (path / "src" / "main.py").write_text(main_py)

    requirements = "fastapi>=0.100\nuvicorn>=0.30\n"
    (path / "requirements.txt").write_text(requirements)


def _run_agent(entry_point: Path, env_vars: dict, debug: bool) -> None:
    """Run the agent process"""
    cmd = [sys.executable, str(entry_point)]

    if debug:
        env_vars["IDENTARK_DEBUG"] = "1"

    result = subprocess.run(cmd, env=env_vars)
    raise typer.Exit(result.returncode)


def _run_with_watch(entry_point: Path, env_vars: dict, debug: bool) -> None:
    """Run agent with file watching"""
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        console.print("[yellow]watchdog not installed. Install with:[/yellow]")
        console.print("  pip install watchdog")
        raise typer.Exit(1)

    class ReloadHandler(FileSystemEventHandler):
        def __init__(self):
            self.process = None

        def on_modified(self, event):
            if event.src_path.endswith(".py"):
                console.print(f"[dim]Detected change in {event.src_path}[/dim]")
                self.restart()

        def restart(self):
            if self.process:
                self.process.terminate()
                self.process.wait()

            console.print("[cyan]Restarting agent...[/cyan]\n")
            self.process = subprocess.Popen([sys.executable, str(entry_point)], env=env_vars)

    handler = ReloadHandler()
    handler.restart()

    observer = Observer()
    observer.schedule(handler, ".", recursive=True)
    observer.start()

    try:
        observer.join()
    except KeyboardInterrupt:
        observer.stop()
        if handler.process:
            handler.process.terminate()

    observer.join()


def _fetch_credential_value(ref: str) -> str:
    """Fetch credential value"""
    from identark_cli.commands.credential import _fetch_credential_value as fetch

    return fetch(ref)
