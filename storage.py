"""
The STORAGE LAYER -- where the bot keeps its memory.

This file talks to a SQL database. It supports TWO backends and picks one
automatically:

  * SQLite   -- the default. Built into Python, no server, one file
               (chatbot.db). Perfect for local development.
  * Postgres -- used in production. If the environment variable DATABASE_URL
               is set (Render provides this), we connect to that instead.

Why two? On a free host like Render the local disk is *ephemeral* -- it gets
wiped on every redeploy or sleep, so a SQLite file there would lose all data.
A managed Postgres database lives on its own and survives restarts.

The beautiful part: the rest of the app NEVER changes. It just calls these
functions. Swapping the entire database engine happens ONLY in this file --
that's the whole point of a "storage layer".

The bot is MULTI-USER. Every visitor gets their own id (a random string in
their browser cookie), and all their data links to it. Classic RELATIONAL
design:

    users (id, name)                 <- one row per person
      |  1
      |  many
    messages (id, user_id, ...)      <- each row "belongs to" one user
    memories (id, user_id, ...)         via a FOREIGN KEY (user_id -> users.id)
"""

import contextlib
import json
import os
import sqlite3

# If DATABASE_URL is set we use Postgres; otherwise we fall back to a local
# SQLite file. This single switch is what makes the code portable.
DATABASE_URL = os.environ.get("DATABASE_URL")
USE_POSTGRES = bool(DATABASE_URL)

# Where the SQLite file lives (only used when NOT on Postgres).
DB_FILE = os.environ.get("CHATBOT_DB", "chatbot.db")

# Old single-user data (and the terminal bot) live under this fixed id.
LEGACY_USER = "legacy"

# Keep only the most recent N exchanges PER USER, so the table can't grow
# forever (the AI only ever reads the last few turns anyway).
MAX_MESSAGES = 200

# Auto-incrementing primary key: the two engines spell it differently.
_AUTO_ID = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"


def _connect():
    """Open a connection to whichever database we're configured for."""
    if USE_POSTGRES:
        # Imported lazily so local dev doesn't need psycopg2 installed.
        import psycopg2

        url = DATABASE_URL
        # Render hands out "postgres://..."; psycopg2 prefers "postgresql://".
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        return psycopg2.connect(url)

    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA foreign_keys = ON")  # enforce FK rules (SQLite only)
    return conn


def _q(sql):
    """Translate placeholders for the active engine.

    We always WRITE our SQL with "?" placeholders (SQLite style). Postgres
    uses "%s" instead, so we swap them when talking to Postgres. Using
    placeholders -- never string formatting -- is what PREVENTS SQL INJECTION.
    """
    return sql.replace("?", "%s") if USE_POSTGRES else sql


@contextlib.contextmanager
def _cursor():
    """Hand out a cursor, then commit and close automatically.

    Statements run inside one `with _cursor() as cur:` block share a single
    transaction, so multi-step writes (insert + trim) commit together.
    """
    conn = _connect()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    finally:
        conn.close()


def _column_exists(conn, table, column):
    """Return True if a SQLite `table` already has a column (migration helper)."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def init_db():
    """Create the tables if they don't exist yet, then migrate old data."""
    with _cursor() as cur:
        # One row per person. The name lives here (not in a settings table).
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id      TEXT PRIMARY KEY,
                name    TEXT,
                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # Each message belongs to a user (user_id -> users.id).
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS messages (
                id      {_AUTO_ID},
                user_id TEXT NOT NULL DEFAULT 'legacy',
                you     TEXT NOT NULL,
                bot     TEXT NOT NULL,
                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )

        # Long-term memory: a fact + its EMBEDDING (a vector), per user. The
        # embedding is stored as JSON text since neither engine has a native
        # "list of floats" column we need here.
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS memories (
                id        {_AUTO_ID},
                user_id   TEXT NOT NULL DEFAULT 'legacy',
                text      TEXT NOT NULL,
                embedding TEXT NOT NULL,
                created   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )

    # These migrations only make sense for an existing local SQLite file.
    # A fresh Postgres database is already in the right shape.
    if not USE_POSTGRES:
        _migrate_to_multiuser()
        _migrate_from_json()


def _migrate_to_multiuser():
    """Upgrade an OLD single-user SQLite database to the multi-user schema.

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
    """Make sure a row exists for this user (called on first visit).

    `ON CONFLICT (id) DO NOTHING` is understood by both Postgres and modern
    SQLite, so the same statement works on either engine.
    """
    with _cursor() as cur:
        cur.execute(
            _q("INSERT INTO users (id) VALUES (?) ON CONFLICT (id) DO NOTHING"),
            (user_id,),
        )


def get_user_name(user_id):
    """Return the stored name for this user, or None."""
    with _cursor() as cur:
        cur.execute(_q("SELECT name FROM users WHERE id = ?"), (user_id,))
        row = cur.fetchone()
    return row[0] if row else None


def save_user_name(user_id, name):
    """Store (or update) this user's name. Creates the user row if needed."""
    with _cursor() as cur:
        cur.execute(
            _q(
                """
                INSERT INTO users (id, name) VALUES (?, ?)
                ON CONFLICT (id) DO UPDATE SET name = excluded.name
                """
            ),
            (user_id, name),
        )


def load_history(user_id):
    """Return this user's chat history, oldest first."""
    with _cursor() as cur:
        cur.execute(
            _q("SELECT you, bot FROM messages WHERE user_id = ? ORDER BY id"),
            (user_id,),
        )
        rows = cur.fetchall()
    return [{"you": you, "bot": bot} for (you, bot) in rows]


def load_memory(user_id):
    """Read this user's name and history together.

    Returns {"user_name": <name or None>, "history": [{"you","bot"}, ...]}.
    """
    return {"user_name": get_user_name(user_id), "history": load_history(user_id)}


def add_message(user_id, you, bot):
    """Insert ONE new exchange for this user, then trim THEIR rows to the most
    recent MAX_MESSAGES (each user is bounded independently)."""
    with _cursor() as cur:
        cur.execute(
            _q("INSERT INTO messages (user_id, you, bot) VALUES (?, ?, ?)"),
            (user_id, you, bot),
        )
        cur.execute(
            _q(
                """
                DELETE FROM messages
                WHERE user_id = ? AND id NOT IN (
                    SELECT id FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?
                )
                """
            ),
            (user_id, user_id, MAX_MESSAGES),
        )


def add_memory(user_id, text, embedding):
    """Store a long-term memory (fact + embedding) for this user."""
    with _cursor() as cur:
        cur.execute(
            _q("INSERT INTO memories (user_id, text, embedding) VALUES (?, ?, ?)"),
            (user_id, text, json.dumps(embedding)),
        )


def memory_exists(user_id, text):
    """Return True if THIS user already has this exact fact stored."""
    with _cursor() as cur:
        cur.execute(
            _q("SELECT 1 FROM memories WHERE user_id = ? AND text = ? LIMIT 1"),
            (user_id, text),
        )
        found = cur.fetchone() is not None
    return found


def get_all_memories(user_id):
    """Return this user's memories as a list of (text, embedding) pairs."""
    with _cursor() as cur:
        cur.execute(
            _q("SELECT text, embedding FROM memories WHERE user_id = ? ORDER BY id"),
            (user_id,),
        )
        rows = cur.fetchall()
    return [(text, json.loads(emb)) for (text, emb) in rows]


def list_memories(user_id):
    """Return this user's facts for display: newest first, with id + date."""
    with _cursor() as cur:
        cur.execute(
            _q("SELECT id, text, created FROM memories WHERE user_id = ? ORDER BY id DESC"),
            (user_id,),
        )
        rows = cur.fetchall()
    # `created` is a string in SQLite but a datetime in Postgres -- normalise
    # to a string so the template renders the same either way.
    return [
        {"id": mem_id, "text": text, "created": str(created)}
        for (mem_id, text, created) in rows
    ]


def delete_memory(user_id, memory_id):
    """Delete one of THIS user's facts (the user_id guard prevents deleting
    someone else's memory by guessing its id)."""
    with _cursor() as cur:
        cur.execute(
            _q("DELETE FROM memories WHERE id = ? AND user_id = ?"),
            (memory_id, user_id),
        )


def reset_all(user_id):
    """Wipe everything for ONE user: their name, chat history, and facts.

    Only this user's rows are touched -- other people's data is untouched.
    """
    with _cursor() as cur:
        cur.execute(_q("DELETE FROM messages WHERE user_id = ?"), (user_id,))
        cur.execute(_q("DELETE FROM memories WHERE user_id = ?"), (user_id,))
        cur.execute(_q("UPDATE users SET name = NULL WHERE id = ?"), (user_id,))


def _migrate_from_json(json_file="memory.json"):
    """One-time import of a very old memory.json into the LEGACY user, if the
    legacy user has no data yet. Preserves your earliest chats (SQLite only)."""
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
