"""
MCP server management commands
"""

from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table

from identark_cli.core.auth import get_api_client

console = Console()
app = typer.Typer(help="MCP server management")

# Server subcommand
server_app = typer.Typer(help="MCP server operations")
app.add_typer(server_app, name="server")

# Tool subcommand
tool_app = typer.Typer(help="MCP tool operations")
app.add_typer(tool_app, name="tool")


@server_app.command("list")
def list_servers() -> None:
    """
    List registered MCP servers

    Shows all MCP servers configured for this organization.
    """
    try:
        with get_api_client() as client:
            response = client.get("/v1/mcp/servers")
            response.raise_for_status()
            data = response.json()
            servers = data.get("servers", [])
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    if not servers:
        console.print("No MCP servers registered")
        console.print("Run: [cyan]identark mcp server add[/cyan]")
        return

    table = Table(title="MCP Servers")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name")
    table.add_column("Transport")
    table.add_column("Status")
    table.add_column("Tools")

    for server in servers:
        tools_count = len(server.get("tools", []))
        status = server.get("status", "unknown")
        status_style = "green" if status == "active" else "yellow"

        table.add_row(
            server["id"][:8],
            server["name"],
            server.get("transport_type", "unknown"),
            f"[{status_style}]{status}[/{status_style}]",
            str(tools_count),
        )

    console.print(table)


@server_app.command("add")
def add_server(
    name: str = typer.Option(..., prompt=True, help="Server name"),
    endpoint: str = typer.Option(..., prompt=True, help="Server endpoint URL"),
    transport: str = typer.Option(
        "stdio",
        prompt=True,
        help="Transport type",
        click_type=typer.Choice(["stdio", "http_sse", "streamable_http"]),
    ),
    auth_type: str = typer.Option(
        "none", help="Authentication type", click_type=typer.Choice(["none", "bearer", "api_key"])
    ),
) -> None:
    """
    Register a new MCP server

    Adds an MCP server endpoint for agents to use with
    HITL approval policies.
    """
    # Build auth config
    auth_config = {}
    if auth_type == "bearer":
        token = typer.prompt("Bearer token", hide_input=True)
        auth_config = {"type": "bearer", "token": token}
    elif auth_type == "api_key":
        key_name = typer.prompt("API key header name", default="X-API-Key")
        key_value = typer.prompt("API key value", hide_input=True)
        auth_config = {"type": "api_key", "key_name": key_name, "key_value": key_value}

    payload = {
        "name": name,
        "endpoint_url": endpoint,
        "transport_type": transport,
        "auth_config": auth_config,
    }

    try:
        with get_api_client() as client:
            response = client.post("/v1/mcp/servers", json=payload)
            response.raise_for_status()
            server = response.json()

        console.print(f"[green]✓ Registered MCP server:[/green] {name}")
        console.print(f"  ID: [cyan]{server['id']}[/cyan]")

        # Offer to discover capabilities
        discover = typer.confirm("Discover server capabilities now?")
        if discover:
            _discover_server(server["id"])

    except Exception as e:
        console.print(f"[red]Failed to register server:[/red] {e}")
        raise typer.Exit(1)


@server_app.command("remove")
def remove_server(
    server_id: str = typer.Argument(..., help="Server ID"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """
    Remove an MCP server

    Unregisters the server. Existing HITL policies referencing
    this server will be deactivated.
    """
    if not force:
        confirm = typer.confirm(f"Remove MCP server {server_id}?")
        if not confirm:
            console.print("Cancelled")
            return

    try:
        with get_api_client() as client:
            response = client.delete(f"/v1/mcp/servers/{server_id}")
            response.raise_for_status()

        console.print(f"[green]✓ Removed MCP server[/green] {server_id}")

    except Exception as e:
        console.print(f"[red]Failed to remove server:[/red] {e}")
        raise typer.Exit(1)


@server_app.command("discover")
def discover_server(
    server_id: str = typer.Argument(..., help="Server ID"),
) -> None:
    """
    Discover MCP server capabilities

    Fetches available tools, resources, and prompts from
    the MCP server and updates the local cache.
    """
    _discover_server(server_id)


def _discover_server(server_id: str) -> None:
    """Helper to discover server capabilities"""
    with console.status("Discovering server capabilities..."):
        try:
            with get_api_client() as client:
                response = client.post(f"/v1/mcp/servers/{server_id}/discover")
                response.raise_for_status()
                result = response.json()

            console.print("[green]✓ Discovered capabilities[/green]")

            if "tools" in result:
                console.print(f"  Tools: {len(result['tools'])}")
            if "resources" in result:
                console.print(f"  Resources: {len(result['resources'])}")
            if "prompts" in result:
                console.print(f"  Prompts: {len(result['prompts'])}")

        except Exception as e:
            console.print(f"[yellow]Discovery failed:[/yellow] {e}")


@server_app.command("show")
def show_server(
    server_id: str = typer.Argument(..., help="Server ID"),
) -> None:
    """
    Show MCP server details

    Displays full server configuration and discovered capabilities.
    """
    try:
        with get_api_client() as client:
            response = client.get(f"/v1/mcp/servers/{server_id}")
            response.raise_for_status()
            server = response.json()
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    # Build details panel
    content = f"""
[bold]Name:[/bold]           {server.get('name')}
[bold]Endpoint:[/bold]       {server.get('endpoint_url')}
[bold]Transport:[/bold]      {server.get('transport_type')}
[bold]Status:[/bold]         {server.get('status')}
[bold]Protocol:[/bold]       {server.get('protocol_version', 'unknown')}

[bold]Capabilities:[/bold]
  Tools:     {len(server.get('tools', []))}
  Resources: {len(server.get('resources', []))}
  Prompts:   {len(server.get('prompts', []))}

[bold]Circuit Breaker:[/bold] {'Enabled' if server.get('circuit_breaker_enabled') else 'Disabled'}
    """

    console.print(Panel(content, title=f"MCP Server: {server_id}", border_style="cyan"))

    # Show tools if available
    if server.get("tools"):
        console.print("\n[bold]Available Tools:[/bold]")
        tools_table = Table()
        tools_table.add_column("Name", style="cyan")
        tools_table.add_column("Description")

        for tool in server["tools"][:10]:  # Show first 10
            tools_table.add_row(tool.get("name", "unknown"), tool.get("description", "")[:50])

        console.print(tools_table)


@tool_app.command("list")
def list_tools(
    server_id: str = typer.Option(..., "--server", "-s", help="Server ID"),
) -> None:
    """
    List available MCP tools

    Shows all tools available on a specific MCP server.
    """
    try:
        with get_api_client() as client:
            response = client.get(f"/v1/mcp/servers/{server_id}")
            response.raise_for_status()
            server = response.json()
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    tools = server.get("tools", [])

    if not tools:
        console.print("No tools available on this server")
        console.print("Run: [cyan]identark mcp server discover <server_id>[/cyan]")
        return

    table = Table(title=f"Tools on {server.get('name', server_id)}")
    table.add_column("Name", style="cyan")
    table.add_column("Description")

    for tool in tools:
        table.add_row(tool.get("name", "unknown"), tool.get("description", "No description")[:60])

    console.print(table)


@tool_app.command("execute")
def execute_tool(
    server_id: str = typer.Option(..., "--server", "-s", help="Server ID"),
    tool_name: str = typer.Option(..., "--tool", "-t", help="Tool name"),
    arguments: Optional[str] = typer.Option(None, "--args", "-a", help="JSON arguments"),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for HITL approval"),
) -> None:
    """
    Execute an MCP tool

    Executes a tool through the MCP Gateway with HITL.
    High-risk operations will require approval.
    """
    # Parse arguments
    args = {}
    if arguments:
        try:
            args = json.loads(arguments)
        except json.JSONDecodeError:
            console.print("[red]Invalid JSON in arguments[/red]")
            raise typer.Exit(1)

    payload = {"server_id": server_id, "tool_name": tool_name, "arguments": args}

    try:
        with console.status("Executing tool..."):
            with get_api_client() as client:
                response = client.post("/v1/mcp/execute", json=payload)

                if response.status_code == 202:
                    # HITL required
                    console.print("[yellow]⏳ HITL approval required[/yellow]")

                    if wait:
                        console.print("Waiting for approval...")
                        # Poll for result
                        # TODO: Implement polling
                    else:
                        console.print("Run [cyan]identark approvals list[/cyan] to check status")
                    return

                response.raise_for_status()
                result = response.json()

        console.print("[green]✓ Tool executed successfully[/green]")
        console.print(JSON(json.dumps(result, indent=2)))

    except Exception as e:
        console.print(f"[red]Execution failed:[/red] {e}")
        raise typer.Exit(1)


@app.command("policy")
def manage_policy(
    server_id: Optional[str] = typer.Option(None, "--server", "-s", help="Server ID"),
    risk_threshold: int = typer.Option(50, "--threshold", "-t", help="Risk threshold"),
) -> None:
    """
    Manage HITL policies for MCP

    Configure approval policies for MCP server operations.
    """
    console.print("[bold]MCP HITL Policies[/bold]\n")
    console.print("To create a policy, use the web dashboard:")
    console.print("  https://identark.io/dashboard/mcp/policies")
    console.print("\nOr use the API directly:")
    console.print("  POST /v1/mcp/policies")
