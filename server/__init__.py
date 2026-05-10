"""Praxova Framing MCP bridge (in-Blender side).

This package owns the localhost JSON-RPC socket and the main-thread
dispatch glue. The external MCP server process (mcp_server/) connects to
this bridge to drive the v0.2 operators from an LLM agent.

Public surface:
    bridge.start(host, port)    -- start listener
    bridge.stop()               -- stop listener
    bridge.is_running()         -- bool
    bridge.get_port()           -- current port (0 if not running)
    handlers.METHODS            -- dict of method name -> callable
    PRAXOVA_OT_start_bridge     -- operator
    PRAXOVA_OT_stop_bridge      -- operator
"""

from . import bridge, handlers  # noqa: F401
from .ops_bridge import (  # noqa: F401
    PRAXOVA_OT_start_bridge,
    PRAXOVA_OT_stop_bridge,
)
