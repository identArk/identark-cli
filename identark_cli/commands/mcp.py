"""
MCP server management commands
"""

from __future__ import annotations

import json
from enum import StrEnum
from urllib.parse import urlparse

import typer
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table

from identark_cli.core.auth import get_api_client

console = Console()
app = typer.Typer(help="MCP server management")


class TransportType(StrEnum):
    """MCP transport. Typer renders an Enum as a choice list natively."""

    HTTP_SSE = "http_sse"
    STREAMABLE_HTTP = "streamable_http"


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
        raise typer.Exit(1) from None

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
    transport: TransportType = typer.Option(
        TransportType.STREAMABLE_HTTP,
        prompt=True,
        help="Transport type",
    ),
) -> None:
    """
    Register a new MCP server

    Adds an unauthenticated HTTPS MCP endpoint for agents to use with HITL
    approval policies. Authenticated MCP registration is intentionally kept
    in the dashboard until the API accepts vault references instead of values.
    """
    parsed_endpoint = urlparse(endpoint)
    if parsed_endpoint.scheme != "https" or not parsed_endpoint.hostname:
        console.print("[red]MCP endpoints must use an absolute HTTPS URL[/red]")
        raise typer.Exit(2)
    if parsed_endpoint.hostname in {"localhost", "127.0.0.1", "::1"}:
        console.print("[red]Local MCP endpoints cannot be reached by the IdentArk cloud[/red]")
        raise typer.Exit(2)

    payload: dict[str, object] = {
        "name": name,
        "endpoint_url": endpoint,
        "transport_type": transport.value,
        "auth_config": {},
    }

    try:
        with get_api_client() as client:
            response = client.post("/v1/mcp/servers", json=payload)
            response.raise_for_status()
            server = response.json()

        console.print(f"[green]✓ Registered MCP server:[/green] {name}")
        console.print(f"  ID: [cyan]{server['id']}[/cyan]")

    except Exception as e:
        console.print(f"[red]Failed to register server:[/red] {e}")
        raise typer.Exit(1) from None


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
        raise typer.Exit(1) from None


@server_app.command("show")
def show_server(
    server_id: str = typer.Argument(..., help="Server ID"),
) -> None:
    """
    Show MCP server details

    Displays the server configuration and recorded tools.
    """
    try:
        with get_api_client() as client:
            response = client.get(f"/v1/mcp/servers/{server_id}")
            response.raise_for_status()
            server = response.json()
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    # Build details panel
    content = f"""
[bold]Name:[/bold]           {server.get("name")}
[bold]Endpoint:[/bold]       {server.get("endpoint_url")}
[bold]Transport:[/bold]      {server.get("transport_type")}
[bold]Status:[/bold]         {server.get("status")}
[bold]Recorded Tools:[/bold]  {len(server.get("tools", []))}
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
        raise typer.Exit(1) from None

    tools = server.get("tools", [])

    if not tools:
        console.print("No tools are recorded for this server")
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
    arguments: str | None = typer.Option(None, "--args", "-a", help="JSON arguments"),
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
            raise typer.Exit(1) from None
        if not isinstance(args, dict):
            console.print("[red]Tool arguments must be a JSON object[/red]")
            raise typer.Exit(2)

    payload = {"server_id": server_id, "tool_name": tool_name, "arguments": args}

    try:
        with console.status("Executing tool..."):
            with get_api_client() as client:
                response = client.post("/v1/mcp/execute", json=payload)

                response.raise_for_status()
                result = response.json()

        console.print("[green]✓ Tool executed successfully[/green]")
        console.print(JSON(json.dumps(result, indent=2)))

    except Exception as e:
        console.print(f"[red]Execution failed:[/red] {e}")
        raise typer.Exit(1) from None
