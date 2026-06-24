"""
A tiny MCP (Model Context Protocol) SERVER.

MCP is an open standard that lets AI apps talk to "tool servers" in a uniform
way. A server like this one EXPOSES tools; a client (see mcp_client.py)
DISCOVERS and CALLS them. Communication is JSON-RPC 2.0 over stdio: the client
writes one JSON message per line to our stdin, and we reply with one JSON
message per line on stdout. (All logging must go to stderr so it never
corrupts the protocol stream on stdout.)

The three methods that matter:
  * initialize   -> handshake; we announce our name + capabilities
  * tools/list   -> we return the tools we offer (name, description, schema)
  * tools/call   -> the client asks us to run a tool with arguments

Run it directly to talk to it by hand:
    python mcp_server.py
    {"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
"""

import json
import sys
import urllib.parse
import urllib.request

PROTOCOL_VERSION = "2024-11-05"


def _log(message):
    """Diagnostics go to STDERR (stdout is reserved for the JSON-RPC stream)."""
    print(f"[mcp_server] {message}", file=sys.stderr, flush=True)


# --- The actual tools this server provides -----------------------------------

def text_stats(text=""):
    """Count words, characters and sentences in some text (purely local)."""
    words = len(text.split())
    chars = len(text)
    sentences = sum(text.count(end) for end in ".!?") or (1 if text.strip() else 0)
    return f"{words} words, {chars} characters, {sentences} sentence(s)."


def define_word(word=""):
    """Look up a dictionary definition via the free dictionaryapi.dev (no key)."""
    word = (word or "").strip()
    if not word:
        return "Please provide a word."
    url = "https://api.dictionaryapi.dev/api/v2/entries/en/" + urllib.parse.quote(word)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "chatbot-mcp/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.load(resp)
        meaning = data[0]["meanings"][0]
        definition = meaning["definitions"][0]["definition"]
        pos = meaning.get("partOfSpeech", "")
        return f"{word} ({pos}): {definition}" if pos else f"{word}: {definition}"
    except Exception:
        return f"No definition found for '{word}'."


# Each tool: a JSON Schema describing its inputs, plus the function to run.
TOOLS = {
    "text_stats": {
        "description": "Count the words, characters and sentences in a piece of text.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Text to analyse"}},
            "required": ["text"],
        },
        "fn": text_stats,
    },
    "define_word": {
        "description": "Get the dictionary definition of an English word.",
        "inputSchema": {
            "type": "object",
            "properties": {"word": {"type": "string", "description": "The word to define"}},
            "required": ["word"],
        },
        "fn": define_word,
    },
}


# --- JSON-RPC plumbing --------------------------------------------------------

def _send(obj):
    """Write one JSON-RPC message as a single line on stdout."""
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _result(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def handle(request):
    """Turn one JSON-RPC request into a response (or None for notifications)."""
    method = request.get("method")
    rid = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        return _result(rid, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "chatbot-mcp", "version": "1.0"},
        })

    if method == "tools/list":
        listed = [
            {"name": name, "description": spec["description"], "inputSchema": spec["inputSchema"]}
            for name, spec in TOOLS.items()
        ]
        return _result(rid, {"tools": listed})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        spec = TOOLS.get(name)
        if not spec:
            return _error(rid, -32602, f"Unknown tool: {name}")
        try:
            text = spec["fn"](**args)
        except Exception as exc:  # noqa: BLE001 -- report any tool failure as text
            text = f"Tool error: {exc}"
        # MCP tool results are a list of content blocks.
        return _result(rid, {"content": [{"type": "text", "text": str(text)}]})

    # Notifications (no id, e.g. notifications/initialized) need no reply.
    if rid is None:
        return None
    return _error(rid, -32601, f"Method not found: {method}")


def main():
    _log("ready (stdio JSON-RPC)")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle(request)
        if response is not None:
            _send(response)


if __name__ == "__main__":
    main()
