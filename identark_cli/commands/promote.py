"""Promote a local sample into a governed Gateway Mode sample."""

from __future__ import annotations

import subprocess
import sys

import typer
from rich.console import Console
from rich.panel import Panel

from identark_cli.core.auth import get_api_client
from identark_cli.core.config import get_project_root, load_config
from identark_cli.core.promotion import PromotionError, promote_project

console = Console()


def promote(
    credential_ref: str = typer.Option(
        ..., "--credential-ref", help="Stored provider credential reference"
    ),
    provider: str = typer.Option(
        "openai", "--provider", help="LLM provider already configured in IdentArk"
    ),
    model: str = typer.Option("gpt-4o-mini", "--model", help="Model for the governed agent"),
    name: str | None = typer.Option(None, "--name", help="Registered agent name"),
    key_ttl_minutes: int = typer.Option(
        15, "--key-ttl-minutes", min=5, max=1440, help="Short-lived capability token lifetime"
    ),
    force: bool = typer.Option(False, "--force", help="Replace the generated Gateway Mode sample"),
    run: bool = typer.Option(
        False, "--run", help="Run one billable governed smoke test after promotion"
    ),
) -> None:
    """Move this project to Gateway Mode without handling a provider secret.

    The command requires a pre-existing vault reference, mints a short-lived
    `llm:invoke` capability bound to one registered agent, and creates a
    separate `identark_gateway_sample.py`. `--run` is explicit because it
    invokes the configured provider and may incur a charge.
    """
    root = get_project_root()
    if root is None:
        console.print("[red]No IdentArk project found. Run `identark init` first.[/red]")
        raise typer.Exit(1)
    try:
        config = load_config(root / ".identark" / "config.toml")
        agent_name = name or f"{config.project_name or root.name}-gateway"
        with get_api_client() as client:
            result = promote_project(
                root,
                credential_ref=credential_ref,
                provider=provider,
                model=model,
                agent_name=agent_name,
                key_ttl_minutes=key_ttl_minutes,
                force=force,
                client=client,
            )
    except PromotionError as exc:
        console.print(f"[red]Could not promote project:[/red] {exc}")
        raise typer.Exit(1) from None
    except Exception:
        console.print(
            "[red]Could not promote project. Check your sign-in, role, and vault reference.[/red]"
        )
        raise typer.Exit(1) from None

    console.print(
        Panel.fit(
            "[green]✓ Gateway Mode configured[/green]\n"
            f"Agent: [cyan]{result.agent_id}[/cyan]\n"
            f"Session: [cyan]{result.session_id}[/cyan]\n"
            "Provider credentials remain in IdentArk; the sample uses a "
            "short-lived capability token."
        )
    )
    if result.expires_at:
        console.print(f"[dim]Capability expires: {result.expires_at}[/dim]")

    if run:
        console.print("[bold]Running one governed smoke test…[/bold]")
        completed = subprocess.run([sys.executable, str(result.sample_path)], cwd=root)
        if completed.returncode != 0:
            console.print(
                "[red]The governed smoke test failed. Run `identark audit list` "
                "to inspect the recorded result.[/red]"
            )
            raise typer.Exit(completed.returncode)
        console.print("[green]✓ Governed smoke test completed[/green]")
        console.print(
            "Run [cyan]identark audit list[/cyan] to inspect the authoritative activity trail."
        )
    else:
        console.print(f"Next: [cyan]python {result.sample_path.name}[/cyan]")
        console.print("Then: [cyan]identark audit list[/cyan]")
