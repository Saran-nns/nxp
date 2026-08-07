"""
MCP Transport — stdio JSON-RPC 2.0 server for MCP protocol compatibility.

This transport makes a nxp agent usable as an MCP tool server,
compatible with Claude Desktop, Cursor, Continue, and other MCP clients.

Protocol: MCP 2024-11-05 (JSON-RPC 2.0 over stdin/stdout)

MCP Methods Supported
---------------------
  initialize         — Handshake and capability negotiation
  initialized        — Client acknowledgment (notification)
  tools/list         — List all registered skills as MCP tools
  tools/call         — Execute a skill by name
  ping               — Liveness check
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import TYPE_CHECKING, Any, Dict, Optional

from nxp.transport.base import BaseTransport

if TYPE_CHECKING:
    from nxp.core.agent import Agent

# MCP Protocol version this transport implements
MCP_PROTOCOL_VERSION = "2024-11-05"


class MCPTransport(BaseTransport):
    """
    MCP-compatible stdio transport.

    Reads JSON-RPC 2.0 requests from stdin, writes responses to stdout.
    This allows any MCP client (Claude Desktop, Cursor, Continue, etc.)
    to use a nxp agent as a tool server.

    Example claude_desktop_config.json:
        {
          "mcpServers": {
            "my-agent": {
              "command": "nxp",
              "args": ["serve", "my_agent:agent", "--transport", "mcp"]
            }
          }
        }
    """

    def __init__(self, agent: "Agent") -> None:
        super().__init__(agent)
        self._initialized = False

    async def serve(self) -> None:
        """Run the MCP JSON-RPC server over stdin/stdout."""
        loop = asyncio.get_event_loop()

        while True:
            # Read one line from stdin (each line = one JSON-RPC message)
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break  # EOF — client disconnected

            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                self._write(self._parse_error(str(exc), req_id=None))
                continue

            response = await self._dispatch(request)

            # Notifications (no id) don't need a response
            if response is not None:
                self._write(response)

    async def _dispatch(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Route an incoming JSON-RPC request to the appropriate handler."""
        method: str = request.get("method", "")
        req_id: Any = request.get("id")
        params: Dict[str, Any] = request.get("params", {}) or {}

        # Notifications (no id field) — process but don't respond
        if "id" not in request:
            if method == "notifications/initialized":
                self._initialized = True
            return None

        # ── MCP methods ───────────────────────────────────────────────────────

        if method == "initialize":
            return self._result(
                req_id,
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "serverInfo": {
                        "name": self.agent.name,
                        "version": self.agent.version,
                    },
                    "capabilities": {
                        "tools": {"listChanged": False},
                    },
                },
            )

        if method == "ping":
            return self._result(req_id, {})

        if method == "tools/list":
            tools = [
                {
                    "name": skill.skill_id,
                    "description": skill.description,
                    "inputSchema": skill.param_schema,
                }
                for skill in self.agent._skills.values()
            ]
            return self._result(req_id, {"tools": tools})

        if method == "tools/call":
            tool_name: str = params.get("name", "")
            arguments: Dict[str, Any] = params.get("arguments", {}) or {}

            if tool_name not in self.agent._skills:
                return self._error(
                    req_id,
                    code=-32602,
                    message=f"Tool '{tool_name}' not found. "
                    f"Available: {list(self.agent._skills.keys())}",
                )

            try:
                result = await self.agent._skills[tool_name].execute(**arguments)
                return self._result(
                    req_id,
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": str(result)
                                if not isinstance(result, str)
                                else result,
                            }
                        ],
                        "isError": False,
                    },
                )
            except TypeError as exc:
                return self._error(
                    req_id,
                    code=-32602,
                    message=f"Invalid arguments for '{tool_name}': {exc}",
                )
            except Exception as exc:
                # MCP spec: tool errors are returned as content with isError=True
                return self._result(
                    req_id,
                    {
                        "content": [{"type": "text", "text": f"Error: {exc}"}],
                        "isError": True,
                    },
                )

        # Unknown method
        return self._error(
            req_id,
            code=-32601,
            message=f"Method '{method}' not found.",
        )

    # ─── Helpers ─────────────────────────────────────────────────────────────────

    def _write(self, message: Dict[str, Any]) -> None:
        """Write a JSON-RPC message to stdout followed by newline."""
        print(json.dumps(message), flush=True)

    def _result(self, req_id: Any, result: Any) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _error(self, req_id: Any, code: int, message: str) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }

    def _parse_error(self, message: str, req_id: Any) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32700, "message": f"Parse error: {message}"},
        }
