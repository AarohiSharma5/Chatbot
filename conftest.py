"""Pytest setup, loaded before any test imports the app modules.

Living at the project root, this also puts the root on sys.path so tests can
`import chatbot`, `import storage`, etc. It forces a throwaway SQLite database
and an offline AI provider -- tests must never hit a real LLM or the network.
"""
import os
import tempfile

_tmp_db = tempfile.NamedTemporaryFile(prefix="chatbot_test_", suffix=".db", delete=False)
_tmp_db.close()

os.environ.pop("DATABASE_URL", None)        # force SQLite, never Postgres
os.environ["CHATBOT_DB"] = _tmp_db.name
os.environ["CHATBOT_AI_PROVIDER"] = "none"  # no real model calls
os.environ["MCP_ENABLED"] = "1"             # MCP tests want the stdio server
