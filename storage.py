"""
The STORAGE LAYER -- where the bot keeps its memory.

We previously saved everything to a JSON file. Now we use a real database:
SQLite. SQLite is special because it's built into Python (no server to run,
no install) and stores everything in a single file (chatbot.db). The SQL we
write here is the SAME SQL you'd use with PostgreSQL or MySQL, so these
skills transfer directly to professional databases.

Why a "storage layer"? The rest of the program doesn't care HOW data is
stored -- it just calls load_memory(), save_user_name(), and add_message().
That means we could swap SQLite for Postgres later by changing ONLY this
file. Separating storage from logic like this is a key professional pattern.
"""

import json
import os
import sqlite3

# Where the SQLite file lives. Defaults to the project folder, but a host can
# point it at a persistent disk by setting CHATBOT_DB (e.g. /data/chatbot.db).
DB_FILE = os.environ.get("CHATBOT_DB", "chatbot.db")


def _connect():
    """Open a connection to the SQLite database file."""
    return sqlite3.connect(DB_FILE)


def init_db():
    """Create the tables if they don't exist yet, then migrate old data.

    A TABLE is like a spreadsheet: rows of data with named columns.
    We use two tables:
      - settings: simple key/value pairs (e.g. the user's name)
      - messages: one row per chat exchange, with a timestamp
    """
    conn = _connect()

    # "IF NOT EXISTS" means this is safe to run every startup.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            you     TEXT NOT NULL,
            bot     TEXT NOT NULL,
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Long-term memory: each row is a fact plus its EMBEDDING (a vector of
    # numbers). We store the vector as JSON text since SQLite has no native
    # "list" column. This little table is our hand-built "vector store".
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            text      TEXT NOT NULL,
            embedding TEXT NOT NULL,
            created   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()

    _migrate_from_json()


def load_memory():
    """Read the user's name and full chat history out of the database.

    Returns the SAME shape the rest of the program already expects:
    {"user_name": <name or None>, "history": [{"you": ..., "bot": ...}, ...]}
    """
    conn = _connect()
    cursor = conn.cursor()

    # SELECT pulls data out. Here we read the saved name (if any).
    cursor.execute("SELECT value FROM settings WHERE key = 'user_name'")
    row = cursor.fetchone()             # one row, or None
    user_name = row[0] if row else None

    # Read every message, oldest first (ORDER BY id).
    cursor.execute("SELECT you, bot FROM messages ORDER BY id")
    history = [{"you": you, "bot": bot} for (you, bot) in cursor.fetchall()]

    conn.close()
    return {"user_name": user_name, "history": history}


def save_user_name(name):
    """Store (or update) the user's name in the settings table."""
    conn = _connect()
    # The "?" is a placeholder. Passing values separately (not by string
    # formatting) is how you PREVENT SQL INJECTION -- a critical security
    # habit. ON CONFLICT updates the row if the key already exists.
    conn.execute(
        """
        INSERT INTO settings (key, value) VALUES ('user_name', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (name,),
    )
    conn.commit()
    conn.close()


# Keep only the most recent N exchanges. Old chat isn't needed: the AI only
# uses the last few turns, so letting the table grow forever just wastes space.
MAX_MESSAGES = 200


def add_message(you, bot):
    """Insert ONE new exchange, then trim the table to the most recent
    MAX_MESSAGES rows so it stays bounded.

    Unlike the file approach, we add a single row instead of rewriting the
    whole history every time -- a big reason databases scale better. The
    DELETE keeps every row EXCEPT the newest MAX_MESSAGES (found via a
    subquery), so the table can't grow without limit."""
    conn = _connect()
    conn.execute("INSERT INTO messages (you, bot) VALUES (?, ?)", (you, bot))
    conn.execute(
        """
        DELETE FROM messages
        WHERE id NOT IN (
            SELECT id FROM messages ORDER BY id DESC LIMIT ?
        )
        """,
        (MAX_MESSAGES,),
    )
    conn.commit()
    conn.close()


def add_memory(text, embedding):
    """Store a long-term memory: the text plus its embedding vector.

    The embedding (a list of floats) is saved as JSON text via json.dumps.
    """
    conn = _connect()
    conn.execute(
        "INSERT INTO memories (text, embedding) VALUES (?, ?)",
        (text, json.dumps(embedding)),
    )
    conn.commit()
    conn.close()


def memory_exists(text):
    """Return True if we've already stored this exact fact.

    Used to avoid saving the same fact twice (e.g. the user mentions they
    like coffee in several messages -> we keep just one copy).
    """
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM memories WHERE text = ? LIMIT 1", (text,))
    found = cursor.fetchone() is not None
    conn.close()
    return found


def get_all_memories():
    """Return every stored memory as a list of (text, embedding) pairs.

    json.loads turns the saved JSON text back into a Python list of floats.
    """
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("SELECT text, embedding FROM memories ORDER BY id")
    memories = [(text, json.loads(emb)) for (text, emb) in cursor.fetchall()]
    conn.close()
    return memories


def list_memories():
    """Return every stored fact for display: newest first, with id + date.

    We deliberately leave OUT the embedding here -- that big list of numbers
    is only useful for similarity math, not for showing to a human.
    """
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("SELECT id, text, created FROM memories ORDER BY id DESC")
    rows = [
        {"id": mem_id, "text": text, "created": created}
        for (mem_id, text, created) in cursor.fetchall()
    ]
    conn.close()
    return rows


def delete_memory(memory_id):
    """Delete one stored fact by its id (used by the memory viewer)."""
    conn = _connect()
    conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    conn.commit()
    conn.close()


def reset_all():
    """Wipe everything the bot remembers: the name, chat history, and facts.

    Used by the "forget me" button. We clear all three tables so the bot
    starts fresh, as if it had never met the user.
    """
    conn = _connect()
    conn.execute("DELETE FROM messages")
    conn.execute("DELETE FROM memories")
    conn.execute("DELETE FROM settings WHERE key = 'user_name'")
    conn.commit()
    conn.close()


def _migrate_from_json(json_file="memory.json"):
    """One-time import: if an old memory.json exists and the database is
    still empty, copy its data in. This preserves your previous chats."""
    if not os.path.exists(json_file):
        return

    existing = load_memory()
    if existing["user_name"] or existing["history"]:
        return  # database already has data; nothing to migrate

    try:
        with open(json_file, "r") as file:
            old = json.load(file)
    except (json.JSONDecodeError, OSError):
        return

    if old.get("user_name"):
        save_user_name(old["user_name"])
    for turn in old.get("history", []):
        if "you" in turn and "bot" in turn:
            add_message(turn["you"], turn["bot"])


# Make sure the tables exist as soon as this module is imported.
init_db()
