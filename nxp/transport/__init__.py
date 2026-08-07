from nxp.transport.base import BaseTransport
from nxp.transport.http import HTTPTransport
from nxp.transport.websocket import NXPTransport, NXPClient

__all__ = ["BaseTransport", "HTTPTransport", "MCPTransport", "GRPCTransport", "NXPTransport", "NXPClient"]


def __getattr__(name: str):
    """
    Lazily import optional transports so a base ``pip install nxp`` doesn't
    require the ``grpc`` or ``mcp`` extras just to run ``import nxp``.

    ``GRPCTransport`` needs ``grpcio``/``protobuf`` (extras: ``nxp[grpc]``).
    ``MCPTransport`` needs the ``mcp``/``fastmcp`` extra (``nxp[mcp]``).
    """
    if name == "MCPTransport":
        from nxp.transport.mcp import MCPTransport
        return MCPTransport
    if name == "GRPCTransport":
        from nxp.transport.grpc import GRPCTransport
        return GRPCTransport
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
