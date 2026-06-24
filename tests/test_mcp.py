"""Tests for the MCP client/server handshake over stdio.

These spawn the real mcp_server.py subprocess but only use the LOCAL tool
(text_stats), so they don't need the network.
"""
import mcp_client


def test_get_tool_schemas_includes_local_tools():
    schemas = mcp_client.get_tool_schemas()
    # If MCP failed to start this would be []; the local server should expose
    # at least text_stats.
    names = {s["function"]["name"] for s in schemas}
    assert "text_stats" in names


def test_is_mcp_tool_recognises_discovered_tools():
    mcp_client.get_tool_schemas()  # ensure discovery has run
    assert mcp_client.is_mcp_tool("text_stats")
    assert not mcp_client.is_mcp_tool("get_weather")


def test_call_text_stats_counts_words():
    out = mcp_client.call_tool("text_stats", {"text": "one two three"})
    assert out and "3" in out
