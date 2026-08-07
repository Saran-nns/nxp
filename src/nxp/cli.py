"""
nxp CLI — Internet of Agents command-line interface.

Commands
--------
  serve     Start an agent server
  inspect   Inspect a remote agent's card and skills
  call      Call a skill on a remote agent
  discover  Discover agents on the local network
  keygen    Generate a secure API key

Usage
-----
  nxp serve my_agent:agent --port 8000
  nxp inspect http://localhost:8000
  nxp call http://localhost:8000 add --args '{"a": 10, "b": 20}'
  nxp discover --network localhost --ports 8000,8001,8080
  nxp keygen
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import typer
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(
    name="nxp",
    help=" [bold]Cognitive Agent Tool[/bold] — Internet of Agents CLI",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
console = Console()


# ─── serve ───────────────────────────────────────────────────────────────────────


@app.command()
def serve(
    module: str = typer.Argument(
        ...,
        help="Python module path to agent, e.g. [cyan]my_agent:agent[/cyan]",
    ),
    host: str = typer.Option("0.0.0.0", "--host", "-H", help="Host to bind to"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to listen on"),
    transport: str = typer.Option(
        "http",
        "--transport",
        "-t",
        help="Transport protocol: [cyan]http[/cyan] (default) or [cyan]mcp[/cyan]",
    ),
) -> None:
    """ Start an agent server."""
    import importlib
    import sys

    # Add current directory to sys.path so local modules are importable
    if "" not in sys.path:
        sys.path.insert(0, "")

    try:
        if ":" in module:
            mod_path, attr = module.rsplit(":", 1)
        else:
            mod_path, attr = module, "agent"

        mod = importlib.import_module(mod_path)
        agent = getattr(mod, attr)
    except ModuleNotFoundError as exc:
        console.print(f"[red] Module not found:[/red] {exc}")
        raise typer.Exit(1)
    except AttributeError:
        console.print(
            f"[red] Attribute [cyan]{attr}[/cyan] not found in module [cyan]{mod_path}[/cyan].[/red]\n"
            f"Make sure you have an [bold]Agent[/bold] instance named [cyan]{attr}[/cyan] in that module."
        )
        raise typer.Exit(1)
    except Exception as exc:
        console.print(f"[red] Failed to load agent:[/red] {exc}")
        raise typer.Exit(1)

    from nxp.agent import Agent as CogAgent

    if not isinstance(agent, CogAgent):
        console.print(
            f"[red] [cyan]{module}[/cyan] is not a nxp Agent instance.[/red]"
        )
        raise typer.Exit(1)

    agent.run(host=host, port=port, transport=transport)


# ─── inspect ─────────────────────────────────────────────────────────────────────


@app.command()
def inspect(
    url: str = typer.Argument(..., help="Agent URL, e.g. [cyan]http://localhost:8000[/cyan]"),
) -> None:
    """ Inspect a remote agent's card and skills."""

    async def _run() -> None:
        from nxp.client import AgentClient

        client = AgentClient(url)

        with console.status(f"Connecting to [cyan]{url}[/cyan]..."):
            try:
                card = await client.get_card()
                health = await client.health()
            except Exception as exc:
                console.print(f"[red] Failed to connect: {exc}[/red]")
                raise typer.Exit(1)

        # Agent Card panel
        provider_info = ""
        if card.provider:
            provider_info = f"\n[dim]Provider:[/dim]  {card.provider.name}"
            if card.provider.url:
                provider_info += f" ({card.provider.url})"

        console.print(
            Panel.fit(
                f"[bold]{card.name}[/bold] [dim]v{card.version}[/dim]\n"
                f"[dim]{card.description}[/dim]\n\n"
                f"[dim]Endpoint:[/dim]  [cyan]{card.url}[/cyan]\n"
                f"[dim]Protocol:[/dim]  A2A {card.protocol_version} • CAT {card.cat_version}\n"
                f"[dim]Streaming:[/dim] {'' if card.capabilities.streaming else ''}"
                + provider_info,
                title="[bold green] Agent Card[/bold green]",
            )
        )

        # Skills table
        if card.skills:
            table = Table(title=f"Skills ({len(card.skills)})", border_style="green", show_lines=True)
            table.add_column("ID", style="cyan bold", no_wrap=True)
            table.add_column("Name")
            table.add_column("Description")
            table.add_column("Tags", style="dim")
            table.add_column("Params", style="dim")

            for skill in card.skills:
                desc = skill.description
                if len(desc) > 60:
                    desc = desc[:57] + "..."
                params = list(skill.parameters.get("properties", {}).keys())
                required = skill.parameters.get("required", [])
                param_str = ", ".join(
                    f"[bold]{p}[/bold]" if p in required else p for p in params
                )
                table.add_row(
                    skill.id,
                    skill.name,
                    desc,
                    ", ".join(skill.tags) or "[dim]-[/dim]",
                    param_str or "[dim]-[/dim]",
                )

            console.print(table)
        else:
            console.print("[yellow]No skills registered on this agent.[/yellow]")

    asyncio.run(_run())


# ─── call ────────────────────────────────────────────────────────────────────────


@app.command()
def call(
    url: str = typer.Argument(..., help="Agent URL"),
    skill_id: str = typer.Argument(..., help="Skill ID to call"),
    args: Optional[str] = typer.Option(
        None,
        "--args",
        "-a",
        help='JSON-encoded skill arguments, e.g. \'{"query": "AI"}\'',
    ),
    api_key: Optional[str] = typer.Option(
        None, "--key", "-k", help="Bearer API key for authenticated agents"
    ),
    task_mode: bool = typer.Option(
        False, "--task", help="Submit as async task instead of direct call"
    ),
) -> None:
    """ Call a skill on a remote agent."""

    async def _run() -> None:
        from nxp.client import AgentClient

        client = AgentClient(url, api_key=api_key)

        kwargs: dict = {}
        if args:
            try:
                kwargs = json.loads(args)
            except json.JSONDecodeError as exc:
                console.print(f"[red] Invalid JSON args: {exc}[/red]")
                raise typer.Exit(1)

        console.print(
            f"[dim]Calling [cyan]{skill_id}[/cyan] on [cyan]{url}[/cyan]"
            + (f" with args: {kwargs}" if kwargs else "")
            + "...[/dim]"
        )

        try:
            if task_mode:
                result = await client.task(skill_id, **kwargs)
            else:
                result = await client.call(skill_id, **kwargs)
        except Exception as exc:
            console.print(f"[red] Error: {exc}[/red]")
            raise typer.Exit(1)

        # Pretty-print result
        if isinstance(result, (dict, list)):
            console.print(Panel(JSON(json.dumps(result)), title="[green] Result[/green]"))
        else:
            console.print(
                Panel(str(result), title="[green] Result[/green]", border_style="green")
            )

    asyncio.run(_run())


# ─── discover ────────────────────────────────────────────────────────────────────


@app.command()
def discover(
    network: str = typer.Option("localhost", "--network", "-n", help="Hostname or IP to scan"),
    ports: str = typer.Option(
        "8000,8001,8002,8080,8081,9000",
        "--ports",
        "-p",
        help="Comma-separated list of ports to scan",
    ),
) -> None:
    """ Discover nxp agents running on the network."""

    async def _run() -> None:
        import httpx

        port_list = [int(p.strip()) for p in ports.split(",")]
        found = []

        with console.status(f"Scanning [cyan]{network}[/cyan] on ports [cyan]{ports}[/cyan]..."):
            async with httpx.AsyncClient(timeout=2.0) as http:
                tasks = [
                    _probe(http, network, port, found) for port in port_list
                ]
                await asyncio.gather(*tasks, return_exceptions=True)

        if not found:
            console.print(
                f"[yellow]No nxp agents discovered on {network}:{ports}[/yellow]"
            )
            return

        table = Table(
            title=f" Discovered Agents ({len(found)})",
            border_style="green",
            show_lines=True,
        )
        table.add_column("URL", style="cyan")
        table.add_column("Name", style="bold")
        table.add_column("Version", style="dim")
        table.add_column("Skills")
        table.add_column("CAT", style="dim")

        for url, card in sorted(found, key=lambda x: x[0]):
            skills = ", ".join(s.get("id", "?") for s in card.get("skills", []))
            table.add_row(
                url,
                card.get("name", "?"),
                card.get("version", "?"),
                skills or "[dim]-[/dim]",
                card.get("cat_version", "?"),
            )

        console.print(table)

    asyncio.run(_run())


async def _probe(http, network: str, port: int, found: list) -> None:
    """Probe a single host:port for a nxp agent."""
    url = f"http://{network}:{port}"
    try:
        resp = await http.get(f"{url}/.well-known/agent-card.json")
        if resp.status_code == 200:
            card = resp.json()
            if "cat_version" in card:  # Confirm it's a nxp agent
                found.append((url, card))
    except Exception:
        pass


# ─── keygen ──────────────────────────────────────────────────────────────────────


@app.command()
def keygen(
    prefix: str = typer.Option("nxp", "--prefix", help="Key prefix"),
    count: int = typer.Option(1, "--count", "-n", help="Number of keys to generate"),
) -> None:
    """ Generate secure API keys for agent authentication."""
    from nxp.security.auth import generate_api_key

    console.print(f"[dim]Generated {count} API key(s):[/dim]")
    for _ in range(count):
        key = generate_api_key(prefix=prefix)
        console.print(f"  [cyan bold]{key}[/cyan bold]")

    if count > 0:
        console.print(
            "\n[dim]Usage:[/dim] [cyan]nxp serve my_agent:agent[/cyan] "
            "[dim]# then set NXP_API_KEY env var on the server[/dim]"
        )


# ─── version ─────────────────────────────────────────────────────────────────────


@app.command()
def version() -> None:
    """ Show nxp version information."""
    from nxp import __version__

    console.print(
        Panel.fit(
            f"[bold]Cognitive Agent Tool[/bold]\n"
            f"Version: [cyan]{__version__}[/cyan]\n"
            f"Protocol: A2A 1.0 • MCP 2024-11-05",
            title="nxp",
            border_style="green",
        )
    )


# ─── registry ────────────────────────────────────────────────────────────────────


registry_cmd_app = typer.Typer(
    name="registry",
    help=" [bold]Agent Registry[/bold] — start and query verified agent marketplaces",
    no_args_is_help=True,
)


@registry_cmd_app.command("start")
def registry_start(
    host: str = typer.Option("0.0.0.0", "--host", "-H", help="Host to bind to"),
    port: int = typer.Option(9999, "--port", "-p", help="Port to listen on"),
) -> None:
    """ Start a standalone nxp agent registry server."""
    import uvicorn
    from nxp.registry import create_registry_server

    console.print(
        Panel.fit(
            f"[bold green] nxp Registry Server[/bold green]\n"
            f"[dim]Endpoint:[/dim] [cyan]http://{host}:{port}[/cyan]\n"
            f"[dim]Docs:[/dim]     [cyan]http://{host}:{port}/docs[/cyan]",
            title="[bold]nxp Infrastructure[/bold]",
            border_style="green",
        )
    )
    uvicorn.run(create_registry_server(), host=host, port=port, log_level="warning")


@registry_cmd_app.command("list")
def registry_list(
    url: str = typer.Argument("http://localhost:9999", help="Registry server URL"),
) -> None:
    """ List all registered live agents."""

    async def _run() -> None:
        from nxp.registry import Registry

        reg = Registry(url=url)
        with console.status(f"Connecting to registry at [cyan]{url}[/cyan]..."):
            try:
                agents = await reg.list_all()
            except Exception as e:
                console.print(f"[red] Registry connection failed: {e}[/red]")
                raise typer.Exit(1)

        _display_registry_agents(agents)

    asyncio.run(_run())


@registry_cmd_app.command("find")
def registry_find(
    url: str = typer.Argument("http://localhost:9999", help="Registry server URL"),
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Filter by skill tag"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Filter by agent name"),
) -> None:
    """ Find agents by name or tag in the registry."""

    async def _run() -> None:
        from nxp.registry import Registry

        reg = Registry(url=url)
        tags = [tag] if tag else None
        with console.status(f"Searching registry at [cyan]{url}[/cyan]..."):
            try:
                agents = await reg.find(tags=tags, name=name)
            except Exception as e:
                console.print(f"[red] Registry search failed: {e}[/red]")
                raise typer.Exit(1)

        _display_registry_agents(agents)

    asyncio.run(_run())


def _display_registry_agents(agents: list) -> None:
    if not agents:
        console.print("[yellow]No agents found in registry.[/yellow]")
        return

    table = Table(
        title=f" Registered Agents ({len(agents)})",
        border_style="green",
        show_lines=True,
    )
    table.add_column("Agent Card / URL", style="cyan")
    table.add_column("Version", style="dim")
    table.add_column("Description")
    table.add_column("Skills")

    for card in agents:
        skill_str = ", ".join(s.id for s in card.skills)
        desc = card.description
        if len(desc) > 60:
            desc = desc[:57] + "..."
        table.add_row(
            f"[bold]{card.name}[/bold]\n{card.url}",
            card.version,
            desc,
            skill_str or "[dim]-[/dim]",
        )

    console.print(table)


app.add_typer(registry_cmd_app, name="registry")


if __name__ == "__main__":
    app()
