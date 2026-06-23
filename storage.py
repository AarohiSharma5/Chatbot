"""
The STORAGE LAYER -- where the bot keeps its memory.

We use SQLite (built into Python, no server, one file: chatbot.db). The SQL
here is the same you'd write for PostgreSQL/MySQL, so the skills transfer.

NEW: the bot is now MULTI-USER. Every visitor gets their own id (a random
string stored in their browser cookie), and all their data is linked to it.
This is classic RELATIONAL design:

    users (id, name)                 <- one row per person
      |  1
      |  many
    messages (id, user_id, ...)      <- each row "belongs to" one user
    memories (id, user_id, ...)         via a FOREIGN KEY (user_id -> users.id)

A foreign key is just a column that points at another table's primary key.
It's how databases model "this belongs to that". We enable enforcement with
PRAGMA foreign_keys = ON, so you can't, say, store a message for a user that
doesn't exist.

Why a "storage layer"? The rest of the program doesn't care HOW data is
stored -- it just calls these functions. We could swap SQLite for Postgres
by changing ONLY this file.
"""

import json
import os
import sqlite3

# Where the SQLite file lives. Defaults to the project folder, but a host can
# point it at a persistent disk by setting CHATBOT_DB (e.g. /data/chatbot.db).
DB_FILE = os.environ.get("CHATBOT_DB", "chatbot.db")

# Old single-user data (and the terminal bot) live under this fixed id.
LEGACY_USER = "legacy"

# Keep only the most recent N exchanges PER USER. Old chat isn't needed: the
# AI only uses the last few turns, so we don't let the table grow forever.
MAX_MESSAGES = 200


def _connect():
    """Open a connection to the SQLite database file (with FKs enforced)."""
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _column_exists(conn, table, column):
    """Return True if `table` already has a column named `column`."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def init_db():
    """Create the tables if they don't exist yet, then migrate old data."""
    conn = _connect()

    # One row per person. The name lives here now (not in a settings table).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id      TEXT PRIMARY KEY,
            name    TEXT,
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Each message belongs to a user (user_id -> users.id).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL DEFAULT 'legacy',
            you     TEXT NOT NULL,
            bot     TEXT NOT NULL,
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    # Long-term memory: a fact + its EMBEDDING (a vector), also per user.
    # The embedding is stored as JSON text since SQLite has no "list" column.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   TEXT NOT NULL DEFAULT 'legacy',
            text      TEXT NOT NULL,
            embedding TEXT NOT NULL,
            created   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )
    conn.commit()
    conn.close()

    _migrate_to_multiuser()
    _migrate_from_json()


def _migrate_to_multiuser():
    """Upgrade an OLD single-user database to the new multi-user schema.

    Older versions had `messages`/`memories` without a user_id column and the
    name in a `settings` table. We add the missing columns, file all that old
    data under the LEGACY_USER, and copy the old name into the users table.
    """
    conn = _connect()

    # Make sure the legacy user exists first (so foreign keys are satisfied).
    conn.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (LEGACY_USER,))

    # Add user_id columns to pre-existing tables that lack them.
    for table in ("messages", "memories"):
        if not _column_exists(conn, table, "user_id"):
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN user_id TEXT NOT NULL DEFAULT 'legacy'"
            )

    # Copy an old settings-based name into the users table (one-time).
    settings_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='settings'"
    ).fetchone()
    if settings_exists:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'user_name'"
        ).fetchone()
        if row and row[0]:
            conn.execute(
                "UPDATE users SET name = ? WHERE id = ? AND name IS NULL",
                (row[0], LEGACY_USER),
            )

    conn.commit()
    conn.close()


def get_or_create_user(user_id):
    """Make sure a row exists for this user (called on first visit)."""
    conn = _connect()
    conn.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()


def get_user_name(user_id):
    """Return the stored name for this user, or None."""
    conn = _connect()
    row = conn.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def save_user_name(user_id, name):
    """Store (or update) this user's name. Creates the user row if needed."""
    conn = _connect()
    # "?" placeholders pass values safely -- this PREVENTS SQL INJECTION.
    conn.execute(
        """
        INSERT INTO users (id, name) VALUES (?, ?)
        ON CONFLICT(id) DO UPDATE SET name = excluded.name
        """,
        (user_id, name),
    )
    conn.commit()
    conn.close()


def load_history(user_id):
    """Return this user's chat history, oldest first."""
    conn = _connect()
    rows = conn.execute(
        "SELECT you, bot FROM messages WHERE user_id = ? ORDER BY id", (user_id,)
    ).fetchall()
    conn.close()
    return [{"you": you, "bot": bot} for (you, bot) in rows]


def load_memory(user_id):
    """Read this user's name and history together.

    Returns {"user_name": <name or None>, "history": [{"you","bot"}, ...]}.
    """
    return {"user_name": get_user_name(user_id), "history": load_history(user_id)}


def add_message(user_id, you, bot):
    """Insert ONE new exchange for this user, then trim THEIR rows to the most
    recent MAX_MESSAGES (each user is bounded independently)."""
    conn = _connect()
    conn.execute(
        "INSERT INTO messages (user_id, you, bot) VALUES (?, ?, ?)",
        (user_id, you, bot),
    )
    conn.execute(
        """
        DELETE FROM messages
        WHERE user_id = ? AND id NOT IN (
            SELECT id FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?
        )
        """,
        (user_id, user_id, MAX_MESSAGES),
    )
    conn.commit()
    conn.close()


def add_memory(user_id, text, embedding):
    """Store a long-term memory (fact + embedding) for this user."""
    conn = _connect()
    conn.execute(
        "INSERT INTO memories (user_id, text, embedding) VALUES (?, ?, ?)",
        (user_id, text, json.dumps(embedding)),
    )
    conn.commit()
    conn.close()


def memory_exists(user_id, text):
    """Return True if THIS user already has this exact fact stored."""
    conn = _connect()
    found = conn.execute(
        "SELECT 1 FROM memories WHERE user_id = ? AND text = ? LIMIT 1",
        (user_id, text),
    ).fetchone() is not None
    conn.close()
    return found


def get_all_memories(user_id):
    """Return this user's memories as a list of (text, embedding) pairs."""
    conn = _connect()
    rows = conn.execute(
        "SELECT text, embedding FROM memories WHERE user_id = ? ORDER BY id",
        (user_id,),
    ).fetchall()
    conn.close()
    return [(text, json.loads(emb)) for (text, emb) in rows]


def list_memories(user_id):
    """Return this user's facts for display: newest first, with id + date."""
    conn = _connect()
    rows = conn.execute(
        "SELECT id, text, created FROM memories WHERE user_id = ? ORDER BY id DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return [
        {"id": mem_id, "text": text, "created": created}
        for (mem_id, text, created) in rows
    ]


def delete_memory(user_id, memory_id):
    """Delete one of THIS user's facts (the user_id guard prevents deleting
    someone else's memory by guessing its id)."""
    conn = _connect()
    conn.execute(
        "DELETE FROM memories WHERE id = ? AND user_id = ?", (memory_id, user_id)
    )
    conn.commit()
    conn.close()


def reset_all(user_id):
    """Wipe everything for ONE user: their name, chat history, and facts.

    Only this user's rows are touched -- other people's data is untouched.
    """
    conn = _connect()
    conn.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
    conn.execute("UPDATE users SET name = NULL WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


def _migrate_from_json(json_file="memory.json"):
    """One-time import of a very old memory.json into the LEGACY user, if the
    legacy user has no data yet. Preserves your earliest chats."""
    if not os.path.exists(json_file):
        return

    existing = load_memory(LEGACY_USER)
    if existing["user_name"] or existing["history"]:
        return  # legacy user already has data; nothing to migrate

    try:
        with open(json_file, "r") as file:
            old = json.load(file)
    except (json.JSONDecodeError, OSError):
        return

    if old.get("user_name"):
        save_user_name(LEGACY_USER, old["user_name"])
    for turn in old.get("history", []):
        if "you" in turn and "bot" in turn:
            add_message(LEGACY_USER, turn["you"], turn["bot"])


# Make sure the tables exist as soon as this module is imported.
init_db()
