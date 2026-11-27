"""
MCP server management commands
"""

from __future__ import annotations

import json
from enum import StrEnum
from urllib.parse import urlparse

import typer
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table

from identark_cli.core.auth import get_api_client
from identark_cli.ui import console, error_console
from identark_cli.ui.components import render_empty_state, render_error, render_success
from identark_cli.ui.safety import redact_sensitive, safe_rich_text

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
    except Exception:
        render_error(
            error_console,
            "Could not load MCP servers.",
            explanation="Check your connection and account permissions.",
            next_step="identark auth status",
        )
        raise typer.Exit(1) from None

    if not servers:
        render_empty_state(
            console,
            "No MCP servers registered",
            "Register a public HTTPS endpoint before assigning tools to agents.",
            next_step="identark mcp server add",
        )
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
            safe_rich_text(server.get("id", "unknown"))[:8],
            safe_rich_text(server.get("name", "unknown")),
            safe_rich_text(server.get("transport_type", "unknown")),
            f"[{status_style}]{safe_rich_text(status)}[/{status_style}]",
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

    Adds an unauthenticated HTTPS MCP endpoint for agents to use with human
    approval policies. Authenticated MCP registration is intentionally kept
    in the dashboard until the API accepts vault references instead of values.
    """
    parsed_endpoint = urlparse(endpoint)
    if parsed_endpoint.scheme != "https" or not parsed_endpoint.hostname:
        console.print("[red]MCP endpoints must use an absolute HTTPS URL[/red]")
        raise typer.Exit(2)
    if (
        parsed_endpoint.username
        or parsed_endpoint.password
        or parsed_endpoint.query
        or parsed_endpoint.fragment
    ):
        render_error(
            error_console,
            "MCP endpoint URLs cannot contain credentials, query parameters, or fragments.",
            explanation="Register a stable HTTPS endpoint; keep authentication in IdentArk.",
        )
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

        render_success(console, f"Registered MCP server {safe_rich_text(name)}")
        console.print(f"  ID: [cyan]{safe_rich_text(server.get('id', 'unknown'))}[/cyan]")

    except Exception:
        render_error(
            error_console,
            "Could not register this MCP server.",
            explanation="Check the endpoint, account permissions, and server availability.",
        )
        raise typer.Exit(1) from None


@server_app.command("remove")
def remove_server(
    server_id: str = typer.Argument(..., help="Server ID"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """
    Remove an MCP server

    Unregisters the server. Existing human-approval policies referencing
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

        render_success(console, f"Removed MCP server {safe_rich_text(server_id)}")

    except Exception:
        render_error(
            error_console,
            "Could not remove this MCP server.",
            explanation="It may no longer exist or be outside your access scope.",
        )
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
    except Exception:
        render_error(
            error_console,
            "Could not load this MCP server.",
            next_step="identark mcp server list",
        )
        raise typer.Exit(1) from None

    # Build details panel
    content = f"""
[bold]Name:[/bold]           {safe_rich_text(server.get("name"))}
[bold]Endpoint:[/bold]       {safe_rich_text(server.get("endpoint_url"))}
[bold]Transport:[/bold]      {safe_rich_text(server.get("transport_type"))}
[bold]Status:[/bold]         {safe_rich_text(server.get("status"))}
[bold]Recorded Tools:[/bold]  {len(server.get("tools", []))}
    """

    console.print(
        Panel(content, title=f"MCP Server: {safe_rich_text(server_id)}", border_style="cyan")
    )

    # Show tools if available
    if server.get("tools"):
        console.print("\n[bold]Available Tools:[/bold]")
        tools_table = Table()
        tools_table.add_column("Name", style="cyan")
        tools_table.add_column("Description")

        for tool in server["tools"][:10]:  # Show first 10
            tools_table.add_row(
                safe_rich_text(tool.get("name", "unknown")),
                safe_rich_text(tool.get("description", ""), max_length=50),
            )

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
    except Exception:
        render_error(
            error_console,
            "Could not load tools for this MCP server.",
            next_step="identark mcp server list",
        )
        raise typer.Exit(1) from None

    tools = server.get("tools", [])

    if not tools:
        render_empty_state(
            console,
            "No tools recorded for this server",
            "Tools appear after the service records them through the governed MCP path.",
        )
        return

    table = Table(title=f"Tools on {safe_rich_text(server.get('name', server_id))}")
    table.add_column("Name", style="cyan")
    table.add_column("Description")

    for tool in tools:
        table.add_row(
            safe_rich_text(tool.get("name", "unknown")),
            safe_rich_text(tool.get("description", "No description"), max_length=60),
        )

    console.print(table)


@tool_app.command("execute")
def execute_tool(
    server_id: str = typer.Option(..., "--server", "-s", help="Server ID"),
    tool_name: str = typer.Option(..., "--tool", "-t", help="Tool name"),
    arguments: str | None = typer.Option(None, "--args", "-a", help="JSON arguments"),
) -> None:
    """
    Execute an MCP tool

    Executes a tool through the MCP Gateway. High-risk operations require
    human approval.
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

        render_success(console, "Tool executed successfully")
        console.print(JSON(json.dumps(redact_sensitive(result), indent=2)))

    except Exception:
        render_error(
            error_console,
            "Could not execute this MCP tool.",
            explanation="The request may require human approval or different permissions.",
            next_step="identark approvals list",
        )
        raise typer.Exit(1) from None
