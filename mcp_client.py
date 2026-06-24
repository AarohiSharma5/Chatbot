"""
A minimal MCP (Model Context Protocol) CLIENT.

This is the other half of MCP: it launches an MCP *server* (here, our bundled
mcp_server.py) as a subprocess and talks to it over stdio using JSON-RPC 2.0.
The flow mirrors what big MCP clients (Claude Desktop, IDEs) do:

    1. start the server process
    2. `initialize`  handshake
    3. send the `notifications/initialized` notification
    4. `tools/list`  to discover what tools the server offers
    5. `tools/call`  to run a tool and get its result

We then convert the server's tool definitions into the OpenAI-style "function"
schema the LLM already understands, so MCP tools slot straight into our
existing tool-calling loop alongside the built-in Python tools.

Everything is best-effort: if the server can't start or a call fails, we return
empty/None so the chatbot simply behaves as if MCP weren't there. Pure stdlib,
no extra dependencies. Configure a different server command with MCP_COMMAND
(JSON list), e.g. '["npx","-y","@modelcontextprotocol/server-filesystem","."]'.
"""

import json
import os
import subprocess
import sys
import threading

PROTOCOL_VERSION = "2024-11-05"

# Which server to launch. Defaults to our bundled Python server; override with
# the MCP_COMMAND env var to point at any other MCP server command.
_DEFAULT_COMMAND = [sys.executable, os.path.join(os.path.dirname(__file__), "mcp_server.py")]
try:
    _COMMAND = json.loads(os.environ.get("MCP_COMMAND", "")) or _DEFAULT_COMMAND
except Exception:
    _COMMAND = _DEFAULT_COMMAND

_ENABLED = os.environ.get("MCP_ENABLED", "1") != "0"

_LOCK = threading.Lock()   # serialises access (gunicorn runs multiple threads)
_PROC = None               # the running server subprocess
_NEXT_ID = 0
_TOOL_SCHEMAS = None       # cached OpenAI-style schemas
_TOOL_NAMES = set()        # which tool names came from MCP
_FAILED = False            # once a start fails, stop retrying this process


def _log(message):
    print(f"[mcp_client] {message}", file=sys.stderr, flush=True)


def _ensure_started():
    """Launch the server subprocess and run the MCP handshake (once)."""
    global _PROC, _FAILED
    if _PROC and _PROC.poll() is None:
        return True
    if _FAILED or not _ENABLED:
        return False
    try:
        _PROC = subprocess.Popen(
            _COMMAND,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            bufsize=1,
        )
        _rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "chatbot", "version": "1.0"},
        })
        _notify("notifications/initialized")
        _log(f"connected to MCP server: {' '.join(_COMMAND)}")
        return True
    except Exception as exc:  # noqa: BLE001
        _log(f"could not start MCP server: {exc}")
        _FAILED = True
        _PROC = None
        return False


def _rpc(method, params):
    """Send a JSON-RPC request and wait for the matching response."""
    global _NEXT_ID
    _NEXT_ID += 1
    rid = _NEXT_ID
    _PROC.stdin.write(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}) + "\n")
    _PROC.stdin.flush()
    while True:
        line = _PROC.stdout.readline()
        if not line:
            raise IOError("MCP server closed the connection")
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("id") == rid:
            if "error" in message:
                raise RuntimeError(message["error"].get("message", "MCP error"))
            return message.get("result", {})


def _notify(method, params=None):
    """Send a JSON-RPC notification (no id, no response expected)."""
    _PROC.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}}) + "\n")
    _PROC.stdin.flush()


def get_tool_schemas():
    """Return MCP tools as OpenAI-style function schemas (cached). Empty on failure."""
    global _TOOL_SCHEMAS, _TOOL_NAMES
    if _TOOL_SCHEMAS is not None:
        return _TOOL_SCHEMAS
    with _LOCK:
        if _TOOL_SCHEMAS is not None:
            return _TOOL_SCHEMAS
        schemas = []
        if _ensure_started():
            try:
                result = _rpc("tools/list", {})
                for tool in result.get("tools", []):
                    schemas.append({
                        "type": "function",
                        "function": {
                            "name": tool["name"],
                            "description": "[MCP] " + tool.get("description", ""),
                            "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
                        },
                    })
            except Exception as exc:  # noqa: BLE001
                _log(f"tools/list failed: {exc}")
        _TOOL_SCHEMAS = schemas
        _TOOL_NAMES = {s["function"]["name"] for s in schemas}
        return _TOOL_SCHEMAS


def is_mcp_tool(name):
    """True if `name` is provided by an MCP server (so dispatch routes here)."""
    if _TOOL_SCHEMAS is None:
        get_tool_schemas()
    return name in _TOOL_NAMES


def call_tool(name, arguments):
    """Run an MCP tool and return its text result (or None on failure)."""
    with _LOCK:
        if not _ensure_started():
            return None
        try:
            result = _rpc("tools/call", {"name": name, "arguments": arguments or {}})
        except Exception as exc:  # noqa: BLE001
            _log(f"tools/call {name} failed: {exc}")
            return None
    # MCP results are a list of content blocks; join the text ones.
    parts = [block.get("text", "") for block in result.get("content", []) if block.get("type") == "text"]
    return "\n".join(p for p in parts if p) or None
