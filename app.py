"""
A web version of our chatbot, using Flask.

The KEY idea: we don't rewrite the chatbot's brain. We IMPORT the same
functions from chatbot.py (get_intent, get_response, try_calculate, ...)
and give them a new "front door" -- a web page instead of the terminal.

This version adds:
  * ACCOUNTS -- register/login with a username + password, so your identity
    (and data) follow you across devices, not just one browser.
  * THREADS  -- multiple separate conversations per account, like the
    sidebar in ChatGPT.
  * RATE LIMITING -- a cap on messages per minute, so a public URL can't be
    abused into burning our AI quota.
"""

import os
import time
import uuid
from functools import wraps

from flask import (
    Flask,
    Response,
    redirect,
    render_template,
    request,
    jsonify,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

# Reuse the logic we already built and tested in chatbot.py.
import ai_brain
import chatbot
import memory_brain
import storage

app = Flask(__name__)

# The secret key signs the session cookie so users can't forge another
# person's id. Set a STABLE value in production (env var) so cookies survive
# restarts; otherwise we generate a throwaway one for local dev.
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(32).hex())

# Per-user conversational state that we DON'T need to persist in the database:
#   last_intent   -> so "another"/"again" can repeat the previous request
#   awaiting_name -> so a bare reply right after "what's your name?" is the name
# Keyed by user id. (One gunicorn worker keeps this in memory across requests.)
STATE = {}

# Simple in-memory RATE LIMIT: how many messages one account may send within
# the rolling window. Plenty for real use, but blocks a flood of requests.
RATE_LIMIT = 30          # messages...
RATE_WINDOW = 60         # ...per this many seconds
_rate_log = {}           # user_id -> list of recent request timestamps


# --------------------------------------------------------------------------
# Authentication helpers
# --------------------------------------------------------------------------

def current_user_id():
    """Return the logged-in account id from the session (or None)."""
    return session.get("uid")


def login_required(view):
    """Decorator: bounce anyone who isn't logged in to the login page."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user_id():
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def _state(user_id):
    """Return the in-memory conversation state for this user."""
    return STATE.setdefault(user_id, {"last_intent": None, "awaiting_name": False})


def _within_rate_limit(user_id):
    """Return True if this user is under the limit; records this request."""
    now = time.time()
    hits = [t for t in _rate_log.get(user_id, []) if now - t < RATE_WINDOW]
    if len(hits) >= RATE_LIMIT:
        _rate_log[user_id] = hits
        return False
    hits.append(now)
    _rate_log[user_id] = hits
    return True


# --------------------------------------------------------------------------
# Chatbot glue
# --------------------------------------------------------------------------

def capture_name(user_id, user_message):
    """If the message states (or, when asked, simply is) the user's name,
    save it and confirm. Returns a confirmation reply, or None."""
    state = _state(user_id)
    name = chatbot.detect_name(user_message)
    if not name and state["awaiting_name"]:
        name = chatbot.plausible_name(user_message)

    if not name:
        return None

    state["awaiting_name"] = False
    storage.save_user_name(user_id, name)
    return f"Nice to meet you, {name}! I'll remember that."


def _save_exchange(user_id, thread_id, user_message, reply, intent):
    """Record one exchange in the database and update conversation state."""
    state = _state(user_id)
    storage.add_message(user_id, user_message, reply, thread_id)
    if intent is not None:
        state["last_intent"] = intent
    state["awaiting_name"] = intent == "ask_my_name" and not storage.get_user_name(user_id)


def stream_reply(user_id, thread_id, user_message, history):
    """A GENERATOR that yields the reply in pieces, for live streaming."""
    state = _state(user_id)
    user_name = storage.get_user_name(user_id)

    name_reply = capture_name(user_id, user_message)
    if name_reply is not None:
        yield name_reply
        _save_exchange(user_id, thread_id, user_message, name_reply, "set_name")
        return

    reply = chatbot.try_calculate(user_message)
    if reply is not None:
        yield reply
        _save_exchange(user_id, thread_id, user_message, reply, "calc")
        return

    intent = chatbot.get_intent(user_message)
    if intent == "repeat":
        last = state["last_intent"]
        intent = last if last not in (None, "repeat") else None

    if intent is not None:
        reply = chatbot.get_response(intent, user_name, user_message, history, user_id)
        yield reply
        _save_exchange(user_id, thread_id, user_message, reply, intent)
        return

    # No rule matched -> stream the AI reply token by token.
    memories = memory_brain.recall(user_id, user_message)
    full_reply = ""
    for chunk in ai_brain.stream_ai(user_message, history, memories):
        full_reply += chunk
        yield chunk

    if full_reply:
        memory_brain.remember(user_id, user_message)
    else:
        import random

        full_reply = random.choice(chatbot.FALLBACK)
        yield full_reply

    _save_exchange(user_id, thread_id, user_message, full_reply, None)


# --------------------------------------------------------------------------
# Auth routes
# --------------------------------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    """Create a new account, then log the user in."""
    if current_user_id():
        return redirect(url_for("index"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        if len(username) < 3 or len(username) > 30:
            return render_template("register.html", error="Username must be 3-30 characters.")
        if len(password) < 6:
            return render_template("register.html", error="Password must be at least 6 characters.")

        user_id = uuid.uuid4().hex
        ok = storage.create_account(user_id, username, generate_password_hash(password))
        if not ok:
            return render_template("register.html", error="That username is taken.")

        session["uid"] = user_id
        session.permanent = True
        return redirect(url_for("index"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log in to an existing account."""
    if current_user_id():
        return redirect(url_for("index"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        account = storage.get_account_by_username(username)
        if not account or not check_password_hash(account["password_hash"] or "", password):
            return render_template("login.html", error="Wrong username or password.")

        session["uid"] = account["id"]
        session.permanent = True
        return redirect(url_for("index"))

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    """Log out (clears the session cookie)."""
    session.clear()
    return redirect(url_for("login"))


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

@app.route("/")
@login_required
def index():
    """Serve the chat web page. Ensure the user has at least one thread."""
    user_id = current_user_id()
    if not storage.list_threads(user_id):
        storage.create_thread(user_id)
    return render_template("index.html", display_name=storage.get_user_name(user_id))


@app.route("/memories")
@login_required
def memories_page():
    """Show every durable fact the bot has stored about THIS user."""
    user_id = current_user_id()
    facts = storage.list_memories(user_id)
    return render_template("memories.html", facts=facts)


@app.route("/memories/<int:memory_id>/delete", methods=["POST"])
@login_required
def delete_memory(memory_id):
    """Forget one of this user's facts, then return to the memory viewer."""
    user_id = current_user_id()
    storage.delete_memory(user_id, memory_id)
    return redirect(url_for("memories_page"))


@app.route("/reset", methods=["POST"])
@login_required
def reset():
    """Make the bot forget everything about THIS user: name, threads, facts."""
    user_id = current_user_id()
    storage.reset_all(user_id)
    STATE.pop(user_id, None)
    storage.create_thread(user_id)  # give them a fresh empty thread
    return ("", 204)


# --------------------------------------------------------------------------
# Thread API (the sidebar talks to these)
# --------------------------------------------------------------------------

@app.route("/threads", methods=["GET"])
@login_required
def threads_list():
    """Return this user's conversations (newest first)."""
    return jsonify(storage.list_threads(current_user_id()))


@app.route("/threads", methods=["POST"])
@login_required
def threads_create():
    """Start a new conversation and return it."""
    user_id = current_user_id()
    thread_id = storage.create_thread(user_id)
    return jsonify({"id": thread_id, "title": "New chat"})


@app.route("/threads/<int:thread_id>/messages", methods=["GET"])
@login_required
def thread_messages(thread_id):
    """Return the messages in one conversation (oldest first)."""
    user_id = current_user_id()
    if not storage.thread_belongs_to(user_id, thread_id):
        return jsonify({"error": "not found"}), 404
    return jsonify(storage.load_history(user_id, thread_id))


@app.route("/threads/<int:thread_id>/delete", methods=["POST"])
@login_required
def thread_delete(thread_id):
    """Delete a conversation. Always leaves the user with at least one."""
    user_id = current_user_id()
    storage.delete_thread(user_id, thread_id)
    if not storage.list_threads(user_id):
        storage.create_thread(user_id)
    return ("", 204)


@app.route("/chat/stream", methods=["POST"])
@login_required
def chat_stream():
    """Receive a message in a thread and STREAM the reply back as generated."""
    user_id = current_user_id()
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    thread_id = data.get("thread_id")

    if user_message == "":
        return Response("Say something, or type 'bye'.", mimetype="text/plain")

    # The thread must exist and belong to this user.
    if not thread_id or not storage.thread_belongs_to(user_id, int(thread_id)):
        return Response("That conversation doesn't exist.", status=404, mimetype="text/plain")
    thread_id = int(thread_id)

    if not _within_rate_limit(user_id):
        return Response(
            "You're sending messages too fast. Give me a few seconds to catch up.",
            status=429,
            mimetype="text/plain",
        )

    # Name the thread after its first message (so the sidebar isn't all "New chat").
    if storage.thread_message_count(user_id, thread_id) == 0:
        title = user_message[:40] + ("..." if len(user_message) > 40 else "")
        storage.rename_thread(user_id, thread_id, title)

    history = storage.load_history(user_id, thread_id)
    return Response(
        stream_reply(user_id, thread_id, user_message, history),
        mimetype="text/plain",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    # Running directly (e.g. `python app.py`) is for LOCAL development.
    # In production, gunicorn imports `app` instead and this block never runs.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
