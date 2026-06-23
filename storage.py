"""
The STORAGE LAYER -- where the bot keeps its memory.

This file talks to a SQL database. It supports TWO backends and picks one
automatically:

  * SQLite   -- the default. Built into Python, no server, one file
               (chatbot.db). Perfect for local development.
  * Postgres -- used in production. If the environment variable DATABASE_URL
               is set (Render/Neon provide this), we connect to that instead.

The rest of the app NEVER changes when we swap engines -- it just calls these
functions. That's the whole point of a "storage layer".

DATA MODEL (relational):

    users (id, name, username, password_hash)   <- one row per ACCOUNT
      |  1                                          (username/password = login)
      |  many
    threads (id, user_id, title)                 <- each chat conversation
      |  1
      |  many
    messages (id, user_id, thread_id, you, bot)  <- one exchange in a thread

    memories (id, user_id, text, embedding)      <- long-term facts, per user

A FOREIGN KEY (e.g. messages.user_id -> users.id) is how a database models
"this row belongs to that row". We enable enforcement in SQLite with
PRAGMA foreign_keys = ON.
"""

import contextlib
import json
import os
import sqlite3

# If DATABASE_URL is set we use Postgres; otherwise a local SQLite file.
DATABASE_URL = os.environ.get("DATABASE_URL")
USE_POSTGRES = bool(DATABASE_URL)

# Where the SQLite file lives (only used when NOT on Postgres).
DB_FILE = os.environ.get("CHATBOT_DB", "chatbot.db")

# Old single-user data (and the terminal bot) live under this fixed id.
LEGACY_USER = "legacy"

# Keep only the most recent N exchanges PER THREAD, so a table can't grow
# forever (the AI only ever reads the last few turns anyway).
MAX_MESSAGES = 200

# Auto-incrementing primary key: the two engines spell it differently.
_AUTO_ID = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"


def _connect():
    """Open a connection to whichever database we're configured for."""
    if USE_POSTGRES:
        import psycopg2  # imported lazily so local dev needn't install it

        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        return psycopg2.connect(url)

    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA foreign_keys = ON")  # enforce FK rules (SQLite only)
    return conn


def _q(sql):
    """Translate placeholders for the active engine.

    We WRITE our SQL with "?" (SQLite style); Postgres wants "%s". Using
    placeholders -- never string formatting -- is what PREVENTS SQL INJECTION.
    """
    return sql.replace("?", "%s") if USE_POSTGRES else sql


@contextlib.contextmanager
def _cursor():
    """Hand out a cursor, then commit and close automatically. Statements in
    one `with` block share a transaction, so multi-step writes commit together."""
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


def _ensure_column(table, column, decl):
    """Add `column` to `table` if it's missing -- works on both engines."""
    if USE_POSTGRES:
        with _cursor() as cur:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {decl}")
    else:
        conn = _connect()
        if not _column_exists(conn, table, column):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            conn.commit()
        conn.close()


def init_db():
    """Create the tables if they don't exist yet, then migrate old data."""
    with _cursor() as cur:
        # One row per ACCOUNT. username/password_hash are NULL for the legacy
        # terminal user and for any old anonymous (cookie-only) visitors.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            TEXT PRIMARY KEY,
                name          TEXT,
                username      TEXT,
                password_hash TEXT,
                created       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # A conversation. Each belongs to a user; messages belong to a thread.
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS threads (
                id      {_AUTO_ID},
                user_id TEXT NOT NULL,
                title   TEXT NOT NULL DEFAULT 'New chat',
                persona TEXT NOT NULL DEFAULT 'friend',
                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )

        # Chunks of uploaded documents + their embeddings, for "chat with your
        # docs" (RAG). Scoped to a thread, so each conversation has its own docs.
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS doc_chunks (
                id        {_AUTO_ID},
                user_id   TEXT NOT NULL,
                thread_id INTEGER NOT NULL,
                filename  TEXT NOT NULL,
                text      TEXT NOT NULL,
                embedding TEXT NOT NULL,
                created   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )

        # Each message belongs to a user and (for the web) to a thread.
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS messages (
                id        {_AUTO_ID},
                user_id   TEXT NOT NULL DEFAULT 'legacy',
                thread_id INTEGER,
                you       TEXT NOT NULL,
                bot       TEXT NOT NULL,
                created   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )

        # Long-term memory: a fact + its EMBEDDING (a vector), per user. The
        # embedding is stored as JSON text (no native "list" column we need).
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

    # Bring older databases up to the current shape (add missing columns).
    # This MUST run before the username index below, since an existing
    # database's users table may not have the username column yet.
    _ensure_column("users", "username", "TEXT")
    _ensure_column("users", "password_hash", "TEXT")
    _ensure_column("users", "theme", "TEXT")
    _ensure_column("messages", "thread_id", "INTEGER")
    _ensure_column("threads", "persona", "TEXT NOT NULL DEFAULT 'friend'")

    # One username per account. NULLs are allowed (multiple), so legacy /
    # anonymous rows without a username don't clash.
    with _cursor() as cur:
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)"
        )

    if not USE_POSTGRES:
        _migrate_to_multiuser()
        _migrate_from_json()


def _migrate_to_multiuser():
    """Upgrade an OLD single-user SQLite database to the multi-user schema."""
    conn = _connect()

    conn.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (LEGACY_USER,))
    for table in ("messages", "memories"):
        if not _column_exists(conn, table, "user_id"):
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN user_id TEXT NOT NULL DEFAULT 'legacy'"
            )

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


# --------------------------------------------------------------------------
# Accounts (username + password login)
# --------------------------------------------------------------------------

def get_or_create_user(user_id):
    """Make sure a row exists for this user id (anonymous or legacy)."""
    with _cursor() as cur:
        cur.execute(
            _q("INSERT INTO users (id) VALUES (?) ON CONFLICT (id) DO NOTHING"),
            (user_id,),
        )


def user_exists(user_id):
    """Return True if a row for this user id exists in the users table."""
    with _cursor() as cur:
        cur.execute(_q("SELECT 1 FROM users WHERE id = ? LIMIT 1"), (user_id,))
        return cur.fetchone() is not None


def username_exists(username):
    """Return True if the username is already taken."""
    with _cursor() as cur:
        cur.execute(_q("SELECT 1 FROM users WHERE username = ? LIMIT 1"), (username,))
        return cur.fetchone() is not None


def create_account(user_id, username, password_hash):
    """Create a new account row. Returns True, or False if the name is taken."""
    if username_exists(username):
        return False
    with _cursor() as cur:
        cur.execute(
            _q(
                "INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)"
            ),
            (user_id, username, password_hash),
        )
    return True


def get_account_by_username(username):
    """Return {'id', 'password_hash'} for a username, or None."""
    with _cursor() as cur:
        cur.execute(
            _q("SELECT id, password_hash FROM users WHERE username = ?"),
            (username,),
        )
        row = cur.fetchone()
    return {"id": row[0], "password_hash": row[1]} if row else None


def get_user_name(user_id):
    """Return the stored display name for this user, or None."""
    with _cursor() as cur:
        cur.execute(_q("SELECT name FROM users WHERE id = ?"), (user_id,))
        row = cur.fetchone()
    return row[0] if row else None


def save_user_name(user_id, name):
    """Store (or update) this user's display name. Creates the row if needed."""
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


def get_theme(user_id):
    """Return this user's saved UI theme ('light' or 'dark'), or None."""
    with _cursor() as cur:
        cur.execute(_q("SELECT theme FROM users WHERE id = ?"), (user_id,))
        row = cur.fetchone()
    return row[0] if row and row[0] else None


def save_theme(user_id, theme):
    """Store the user's preferred theme."""
    with _cursor() as cur:
        cur.execute(_q("UPDATE users SET theme = ? WHERE id = ?"), (theme, user_id))


# --------------------------------------------------------------------------
# Threads (multiple conversations per user)
# --------------------------------------------------------------------------

def create_thread(user_id, title="New chat"):
    """Create a new conversation for this user and return its id."""
    with _cursor() as cur:
        cur.execute(
            _q("INSERT INTO threads (user_id, title) VALUES (?, ?) RETURNING id"),
            (user_id, title),
        )
        return cur.fetchone()[0]


def list_threads(user_id):
    """Return this user's conversations, newest first."""
    with _cursor() as cur:
        cur.execute(
            _q(
                "SELECT id, title, persona, created FROM threads WHERE user_id = ? ORDER BY id DESC"
            ),
            (user_id,),
        )
        rows = cur.fetchall()
    return [
        {"id": tid, "title": title, "persona": persona or "friend", "created": str(created)}
        for (tid, title, persona, created) in rows
    ]


def thread_belongs_to(user_id, thread_id):
    """Return True if this thread exists AND belongs to this user."""
    with _cursor() as cur:
        cur.execute(
            _q("SELECT 1 FROM threads WHERE id = ? AND user_id = ? LIMIT 1"),
            (thread_id, user_id),
        )
        return cur.fetchone() is not None


def rename_thread(user_id, thread_id, title):
    """Set a thread's title (only if it belongs to this user)."""
    with _cursor() as cur:
        cur.execute(
            _q("UPDATE threads SET title = ? WHERE id = ? AND user_id = ?"),
            (title, thread_id, user_id),
        )


def get_persona(user_id, thread_id):
    """Return the persona key for a thread (defaults to 'friend')."""
    with _cursor() as cur:
        cur.execute(
            _q("SELECT persona FROM threads WHERE id = ? AND user_id = ?"),
            (thread_id, user_id),
        )
        row = cur.fetchone()
    return (row[0] if row and row[0] else "friend")


def set_persona(user_id, thread_id, persona):
    """Set a thread's persona (only if it belongs to this user)."""
    with _cursor() as cur:
        cur.execute(
            _q("UPDATE threads SET persona = ? WHERE id = ? AND user_id = ?"),
            (persona, thread_id, user_id),
        )


def delete_thread(user_id, thread_id):
    """Delete a thread plus its messages and documents (if owned by this user)."""
    with _cursor() as cur:
        cur.execute(
            _q("DELETE FROM messages WHERE thread_id = ? AND user_id = ?"),
            (thread_id, user_id),
        )
        cur.execute(
            _q("DELETE FROM doc_chunks WHERE thread_id = ? AND user_id = ?"),
            (thread_id, user_id),
        )
        cur.execute(
            _q("DELETE FROM threads WHERE id = ? AND user_id = ?"),
            (thread_id, user_id),
        )


def thread_message_count(user_id, thread_id):
    """How many exchanges a thread has (used to auto-title the first one)."""
    with _cursor() as cur:
        cur.execute(
            _q("SELECT COUNT(*) FROM messages WHERE thread_id = ? AND user_id = ?"),
            (thread_id, user_id),
        )
        return cur.fetchone()[0]


# --------------------------------------------------------------------------
# Messages
# --------------------------------------------------------------------------

def load_history(user_id, thread_id=None):
    """Return chat history oldest-first.

    With a thread_id, only that conversation's messages. Without one (the
    terminal bot), every message for the user.
    """
    with _cursor() as cur:
        if thread_id is None:
            cur.execute(
                _q("SELECT you, bot FROM messages WHERE user_id = ? ORDER BY id"),
                (user_id,),
            )
        else:
            cur.execute(
                _q(
                    "SELECT you, bot FROM messages WHERE user_id = ? AND thread_id = ? ORDER BY id"
                ),
                (user_id, thread_id),
            )
        rows = cur.fetchall()
    return [{"you": you, "bot": bot} for (you, bot) in rows]


def load_memory(user_id):
    """Read this user's name and (whole-account) history together."""
    return {"user_name": get_user_name(user_id), "history": load_history(user_id)}


def add_message(user_id, you, bot, thread_id=None):
    """Insert one exchange, then trim the oldest so a thread/user stays bounded."""
    with _cursor() as cur:
        cur.execute(
            _q("INSERT INTO messages (user_id, thread_id, you, bot) VALUES (?, ?, ?, ?)"),
            (user_id, thread_id, you, bot),
        )
        if thread_id is None:
            cur.execute(
                _q(
                    """
                    DELETE FROM messages
                    WHERE user_id = ? AND thread_id IS NULL AND id NOT IN (
                        SELECT id FROM messages
                        WHERE user_id = ? AND thread_id IS NULL
                        ORDER BY id DESC LIMIT ?
                    )
                    """
                ),
                (user_id, user_id, MAX_MESSAGES),
            )
        else:
            cur.execute(
                _q(
                    """
                    DELETE FROM messages
                    WHERE thread_id = ? AND id NOT IN (
                        SELECT id FROM messages WHERE thread_id = ? ORDER BY id DESC LIMIT ?
                    )
                    """
                ),
                (thread_id, thread_id, MAX_MESSAGES),
            )


def pop_last_exchange(user_id, thread_id):
    """Delete the most recent exchange in a thread and return its user text.

    Used by EDIT and REGENERATE: we remove the last turn so it can be redone
    (with the same or edited prompt). Returns the deleted 'you' text, or None.
    """
    with _cursor() as cur:
        cur.execute(
            _q(
                "SELECT id, you FROM messages WHERE user_id = ? AND thread_id = ? ORDER BY id DESC LIMIT 1"
            ),
            (user_id, thread_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        cur.execute(_q("DELETE FROM messages WHERE id = ?"), (row[0],))
    return row[1]


def search_messages(user_id, query, limit=50):
    """Find this user's messages containing `query` (case-insensitive).

    Returns matches with their thread so the UI can jump to them. This is a
    plain SQL LIKE search -- simple, and works the same on both engines.
    """
    pattern = f"%{query.lower()}%"
    with _cursor() as cur:
        cur.execute(
            _q(
                """
                SELECT m.thread_id, t.title, m.you, m.bot
                FROM messages m
                JOIN threads t ON t.id = m.thread_id
                WHERE m.user_id = ?
                  AND (LOWER(m.you) LIKE ? OR LOWER(m.bot) LIKE ?)
                ORDER BY m.id DESC
                LIMIT ?
                """
            ),
            (user_id, pattern, pattern, limit),
        )
        rows = cur.fetchall()
    return [
        {"thread_id": tid, "title": title, "you": you, "bot": bot}
        for (tid, title, you, bot) in rows
    ]


# --------------------------------------------------------------------------
# Documents (uploaded files, chunked + embedded for RAG, scoped to a thread)
# --------------------------------------------------------------------------

def add_doc_chunk(user_id, thread_id, filename, text, embedding):
    """Store one chunk of an uploaded document, with its embedding."""
    with _cursor() as cur:
        cur.execute(
            _q(
                "INSERT INTO doc_chunks (user_id, thread_id, filename, text, embedding) VALUES (?, ?, ?, ?, ?)"
            ),
            (user_id, thread_id, filename, text, json.dumps(embedding)),
        )


def get_doc_chunks(user_id, thread_id):
    """Return (text, embedding) pairs for all docs uploaded to a thread."""
    with _cursor() as cur:
        cur.execute(
            _q(
                "SELECT text, embedding FROM doc_chunks WHERE user_id = ? AND thread_id = ?"
            ),
            (user_id, thread_id),
        )
        rows = cur.fetchall()
    return [(text, json.loads(emb)) for (text, emb) in rows]


def list_documents(user_id, thread_id):
    """Return the distinct filenames uploaded to a thread, with chunk counts."""
    with _cursor() as cur:
        cur.execute(
            _q(
                """
                SELECT filename, COUNT(*) FROM doc_chunks
                WHERE user_id = ? AND thread_id = ?
                GROUP BY filename ORDER BY MIN(id)
                """
            ),
            (user_id, thread_id),
        )
        rows = cur.fetchall()
    return [{"filename": name, "chunks": n} for (name, n) in rows]


def thread_has_docs(user_id, thread_id):
    """True if this thread has any uploaded document chunks."""
    with _cursor() as cur:
        cur.execute(
            _q("SELECT 1 FROM doc_chunks WHERE user_id = ? AND thread_id = ? LIMIT 1"),
            (user_id, thread_id),
        )
        return cur.fetchone() is not None


# --------------------------------------------------------------------------
# Long-term memory (per user, shared across their threads)
# --------------------------------------------------------------------------

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
        return cur.fetchone() is not None


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
    return [
        {"id": mem_id, "text": text, "created": str(created)}
        for (mem_id, text, created) in rows
    ]


def delete_memory(user_id, memory_id):
    """Delete one of THIS user's facts (the user_id guard blocks guessing ids)."""
    with _cursor() as cur:
        cur.execute(
            _q("DELETE FROM memories WHERE id = ? AND user_id = ?"),
            (memory_id, user_id),
        )


def reset_all(user_id):
    """Wipe everything for ONE user: name, all threads, history, and facts."""
    with _cursor() as cur:
        cur.execute(_q("DELETE FROM messages WHERE user_id = ?"), (user_id,))
        cur.execute(_q("DELETE FROM memories WHERE user_id = ?"), (user_id,))
        cur.execute(_q("DELETE FROM doc_chunks WHERE user_id = ?"), (user_id,))
        cur.execute(_q("DELETE FROM threads WHERE user_id = ?"), (user_id,))
        cur.execute(_q("UPDATE users SET name = NULL WHERE id = ?"), (user_id,))


def _migrate_from_json(json_file="memory.json"):
    """One-time import of a very old memory.json into the LEGACY user (SQLite)."""
    if not os.path.exists(json_file):
        return

    existing = load_memory(LEGACY_USER)
    if existing["user_name"] or existing["history"]:
        return

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

# A one-line note in the logs so it's obvious which database we're using.
import sys as _sys
print(
    f"[storage] backend={'postgres' if USE_POSTGRES else 'sqlite'}",
    file=_sys.stderr,
)
