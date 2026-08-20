"""
Agent development and execution commands
"""

from __future__ import annotations

import os
import subprocess
import sys
from enum import StrEnum
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from identark_cli.core.auth import get_api_client
from identark_cli.core.config import ProjectConfig, load_config, save_config

console = Console()
app = typer.Typer(help="Agent scaffolding, registration, and local execution")


class AgentTemplate(StrEnum):
    BASIC = "basic"
    SLACK_BOT = "slack-bot"
    API_SERVICE = "api-service"


@app.command()
def init(
    name: str = typer.Option(..., "--name", "-n", help="Agent name"),
    template: AgentTemplate = typer.Option(
        AgentTemplate.BASIC, "--template", "-t", help="Agent template"
    ),
    path: Path = typer.Option(".", "--path", "-p", help="Project path"),
) -> None:
    """
    Initialize a new agent project

    Creates local agent configuration and sample code. Register the agent
    separately when it is ready to use the IdentArk control plane.

    Templates:
        basic       - Minimal agent structure
        slack-bot   - Slack bot with IdentArk integration
        api-service - FastAPI service with local credential injection
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
    config = ProjectConfig(project_name=name, default_agent_template=template.value)
    save_config(config, project_path / ".identark" / "config.toml")

    # Create sample files based on template
    if template == "slack-bot":
        _create_slack_bot_template(project_path, name)
        example_credential = "SLACK_TOKEN"
    elif template == "api-service":
        _create_api_service_template(project_path, name)
        example_credential = "DATABASE_URL"
    else:
        _create_basic_template(project_path, name)
        example_credential = "API_KEY"

    console.print(
        Panel.fit(
            f"[green]✓ Created agent project: {name}[/green]\n"
            f"\n[bold]Next steps:[/bold]"
            f"\n  cd {project_path}"
            f"\n  identark credential add {example_credential} --ref vault://prod/{example_credential.lower()}"
            f"\n  identark agent run"
        )
    )


@app.command()
def register(
    name: str = typer.Option(..., "--name", "-n", help="Agent name"),
    credential_ref: str = typer.Option(
        ..., "--credential-ref", help="Vault path used by the agent's LLM provider"
    ),
    provider: str = typer.Option("openai", "--provider", help="Default LLM provider"),
    model: str = typer.Option("gpt-4o", "--model", help="Default LLM model"),
    description: str | None = typer.Option(None, "--description", help="Agent description"),
) -> None:
    """Register an agent with the IdentArk control plane."""
    if not credential_ref.startswith("vault://") or credential_ref == "vault://":
        console.print("[red]--credential-ref must be a non-empty vault:// reference[/red]")
        raise typer.Exit(2)

    payload = {
        "name": name,
        "credential_ref": credential_ref,
        "provider": provider,
        "model": model,
        "description": description,
    }
    try:
        with get_api_client() as client:
            response = client.post("/v1/agents", json=payload)
            response.raise_for_status()
            registered = response.json()
    except Exception as exc:
        console.print(f"[red]Could not register agent:[/red] {exc}")
        raise typer.Exit(1) from None

    console.print(f"[green]✓ Registered agent[/green] [cyan]{registered['name']}[/cyan]")
    console.print(f"  ID: {registered['id']}")
    console.print(f"  Agent key: {registered['agent_key']}")


@app.command()
def run(
    script: Path | None = typer.Argument(None, help="Agent script to run"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Restart on file changes"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug mode"),
) -> None:
    """
    Run a local agent with credential injection

    Injects credentials from IdentArk vault and runs the agent
    for the child process lifetime. The child process can read injected
    environment variables; use managed connectors for production isolation.
    """
    try:
        config = load_config()
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    # Determine entry point
    if script:
        entry_point = script
    elif Path("main.py").exists():
        entry_point = Path("main.py")
    elif Path("app.py").exists():
        entry_point = Path("app.py")
    elif Path("src/main.py").exists():
        entry_point = Path("src/main.py")
    else:
        console.print("[red]No entry point found[/red]")
        console.print("Specify a script or create main.py, app.py, or src/main.py")
        raise typer.Exit(1)

    if not entry_point.is_file():
        console.print(f"[red]Entry point not found:[/red] {entry_point}")
        raise typer.Exit(1)

    # Fetch credentials
    env_vars = os.environ.copy()

    console.print("[bold]Starting agent with IdentArk credential injection[/bold]\n")

    with console.status("Fetching credentials from vault..."):
        for cred in config.credentials:
            try:
                value = _fetch_credential_value(cred.ref)
                env_vars[cred.name] = value
                console.print(f"  ✓ [cyan]{cred.name}[/cyan] injected")
            except Exception as e:
                if cred.required:
                    console.print(f"  [red]✗ {cred.name}:[/red] {e}")
                    raise typer.Exit(1) from None
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
            "Credential references resolved for this child process\n"
            "Use managed connectors when the process must never receive a raw secret"
        )
    )

    try:
        config = load_config()
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from None

    # Check for common frameworks
    if Path("main.py").exists():
        cmd = [sys.executable, "-m", "uvicorn", "main:app", "--port", str(port)]
        if reload:
            cmd.append("--reload")
    elif Path("app.py").exists():
        cmd = [sys.executable, "app.py"]
    elif Path("src/main.py").exists():
        if config.default_agent_template == AgentTemplate.API_SERVICE:
            cmd = [sys.executable, "-m", "uvicorn", "src.main:app", "--port", str(port)]
            if reload:
                cmd.append("--reload")
        else:
            cmd = [sys.executable, "src/main.py"]
    else:
        console.print("[red]No main.py, app.py, or src/main.py found[/red]")
        raise typer.Exit(1)

    # Run with credentials injected
    from identark_cli.commands.credential import _fetch_credential_value

    try:
        env_vars = os.environ.copy()

        for cred in config.credentials:
            try:
                value = _fetch_credential_value(cred.ref)
                env_vars[cred.name] = value
            except Exception as exc:
                if cred.required:
                    console.print(f"[red]Required credential {cred.name} failed:[/red] {exc}")
                    raise typer.Exit(1) from None
                console.print(f"[yellow]Optional credential {cred.name} unavailable[/yellow]")

        result = subprocess.run(cmd, env=env_vars)
        raise typer.Exit(result.returncode)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


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
                console.print("  Register one with: [cyan]identark agent register --help[/cyan]")
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
        raise typer.Exit(1) from None


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
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


def _create_basic_template(path: Path, name: str) -> None:
    """Create basic agent template"""
    main_py = '''"""
Basic IdentArk Agent
"""
import os

# Credentials are injected by IdentArk - never hardcode!
API_KEY = os.environ.get("API_KEY")

def main():
    print("Agent running with injected development credentials")
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
# Run with local development credential injection
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
    print("Slack bot running with injected development credentials")
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


def _run_agent(entry_point: Path, env_vars: dict[str, str], debug: bool) -> None:
    """Run the agent process"""
    cmd = [sys.executable, str(entry_point)]

    if debug:
        env_vars["IDENTARK_DEBUG"] = "1"

    result = subprocess.run(cmd, env=env_vars)
    raise typer.Exit(result.returncode)


def _run_with_watch(entry_point: Path, env_vars: dict[str, str], debug: bool) -> None:
    """Run agent with file watching"""
    try:
        from watchdog.events import FileSystemEvent, FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        console.print("[yellow]watchdog not installed. Install with:[/yellow]")
        console.print("  pip install watchdog")
        raise typer.Exit(1) from None

    if debug:
        env_vars["IDENTARK_DEBUG"] = "1"

    class ReloadHandler(FileSystemEventHandler):
        def __init__(self) -> None:
            self.process: subprocess.Popen[bytes] | None = None

        def on_modified(self, event: FileSystemEvent) -> None:
            source_path = os.fsdecode(event.src_path)
            if source_path.endswith(".py"):
                console.print(f"[dim]Detected change in {source_path}[/dim]")
                self.restart()

        def restart(self) -> None:
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
            handler.process.wait()

    observer.join()


def _fetch_credential_value(ref: str) -> str:
    """Fetch credential value"""
    from identark_cli.commands.credential import _fetch_credential_value as fetch

    return fetch(ref)
