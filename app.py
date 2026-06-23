"""
A web version of our chatbot, using Flask.

The KEY idea: we don't rewrite the chatbot's brain. We IMPORT the same
functions from chatbot.py (get_intent, get_response, try_calculate, ...)
and give them a new "front door" -- a web page instead of the terminal.

MULTI-USER: every browser gets its own random id, stored in a signed cookie
(Flask's `session`). We pass that id to the storage layer so each visitor has
their own private name, history, and memories. Conversation state that isn't
worth saving to the database (the last intent, "are we waiting for a name?")
is kept in a small in-memory dict keyed by user id.
"""

import os
import random
import uuid

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


def current_user_id():
    """Return this browser's user id, creating one on first visit.

    The id lives in the signed session cookie. We also make sure a matching
    row exists in the `users` table (the parent of all their data)."""
    uid = session.get("uid")
    if not uid:
        uid = uuid.uuid4().hex
        session["uid"] = uid
        session.permanent = True
    storage.get_or_create_user(uid)
    return uid


def _state(user_id):
    """Return the in-memory conversation state for this user."""
    return STATE.setdefault(user_id, {"last_intent": None, "awaiting_name": False})


def capture_name(user_id, user_message):
    """If the message states (or, when asked, simply is) the user's name,
    save it and confirm. Returns a confirmation reply, or None.

    Two ways we learn a name:
      1. Explicit phrasing anytime: "my name is X", "call me X", ...
      2. A bare reply right after WE asked "what's your name?" (awaiting_name).
    """
    state = _state(user_id)
    name = chatbot.detect_name(user_message)
    if not name and state["awaiting_name"]:
        name = chatbot.plausible_name(user_message)

    if not name:
        return None

    state["awaiting_name"] = False
    storage.save_user_name(user_id, name)
    return f"Nice to meet you, {name}! I'll remember that."


def _save_exchange(user_id, user_message, reply, intent):
    """Record one exchange in the database and update conversation state."""
    state = _state(user_id)
    storage.add_message(user_id, user_message, reply)
    if intent is not None:
        state["last_intent"] = intent
    # If the bot just asked for the name (ask_my_name, none stored), arm
    # conversational capture so the NEXT message is taken as the name.
    state["awaiting_name"] = intent == "ask_my_name" and not storage.get_user_name(user_id)


def stream_reply(user_id, user_message, history):
    """A GENERATOR that yields the reply in pieces, for live streaming.

    Rule-based answers (math, jokes, time...) are instant, so we yield them
    in one piece. Only the AI fallback is truly streamed, chunk by chunk.
    """
    state = _state(user_id)
    user_name = storage.get_user_name(user_id)

    # Did they tell us their name? Learn it and confirm (instant).
    name_reply = capture_name(user_id, user_message)
    if name_reply is not None:
        yield name_reply
        _save_exchange(user_id, user_message, name_reply, "set_name")
        return

    # Math and rule-based intents are instant -> yield the whole reply once.
    reply = chatbot.try_calculate(user_message)
    if reply is not None:
        yield reply
        _save_exchange(user_id, user_message, reply, "calc")
        return

    intent = chatbot.get_intent(user_message)
    if intent == "repeat":
        last = state["last_intent"]
        intent = last if last not in (None, "repeat") else None

    if intent is not None:
        reply = chatbot.get_response(intent, user_name, user_message, history, user_id)
        yield reply
        _save_exchange(user_id, user_message, reply, intent)
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
        # AI unavailable -> fall back to a canned reply.
        full_reply = random.choice(chatbot.FALLBACK)
        yield full_reply

    _save_exchange(user_id, user_message, full_reply, None)


@app.route("/")
def index():
    """Serve the chat web page (and assign a session id on first visit)."""
    current_user_id()
    return render_template("index.html")


@app.route("/memories")
def memories_page():
    """Show every durable fact the bot has stored about THIS user."""
    user_id = current_user_id()
    facts = storage.list_memories(user_id)
    return render_template("memories.html", facts=facts)


@app.route("/memories/<int:memory_id>/delete", methods=["POST"])
def delete_memory(memory_id):
    """Forget one of this user's facts, then return to the memory viewer."""
    user_id = current_user_id()
    storage.delete_memory(user_id, memory_id)
    return redirect(url_for("memories_page"))


@app.route("/reset", methods=["POST"])
def reset():
    """Make the bot forget everything about THIS user: name, history, facts.

    We clear the database AND this user's in-memory state, so the running
    server immediately behaves like a fresh start (no restart needed)."""
    user_id = current_user_id()
    storage.reset_all(user_id)
    STATE.pop(user_id, None)
    return ("", 204)


@app.route("/chat/stream", methods=["POST"])
def chat_stream():
    """Receive a message and STREAM the reply back as it's generated.

    We resolve the user id HERE (in the view) so the session cookie is saved
    before the streaming body starts -- session changes made inside the
    generator would be too late to set the cookie."""
    user_id = current_user_id()
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()

    if user_message == "":
        return Response("Say something, or type 'bye'.", mimetype="text/plain")

    history = storage.load_history(user_id)
    return Response(
        stream_reply(user_id, user_message, history),
        mimetype="text/plain",
        # Tell proxies/browsers not to buffer, so chunks arrive immediately.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    # Running directly (e.g. `python app.py`) is for LOCAL development.
    # In production, a real server (gunicorn) imports `app` instead and this
    # block never runs -- see the Procfile / Render start command.
    #
    # Hosts tell us which port to use via the PORT environment variable, so
    # we read it (defaulting to 5000 for local use). We bind to 0.0.0.0 so
    # the server is reachable from outside the container, not just localhost.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
