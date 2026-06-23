"""
A web version of our chatbot, using Flask.

The KEY idea: we don't rewrite the chatbot's brain. We IMPORT the same
functions from chatbot.py (get_intent, get_response, try_calculate, ...)
and just give them a new "front door" -- a web page instead of the
terminal. The terminal loop is replaced by a web server that answers
one message at a time over HTTP.
"""

import os
import random

from flask import Flask, Response, redirect, render_template, request, jsonify, url_for

# Reuse the logic we already built and tested in chatbot.py.
import ai_brain
import chatbot
import memory_brain
import storage

app = Flask(__name__)

# Load any memory saved by previous runs (e.g. the user's name) from the
# SQLite database -- the SAME storage the terminal bot uses.
memory = storage.load_memory()
history = memory.get("history", [])

# CONTEXT: like the terminal version, we remember the previous intent so
# follow-ups such as "another" work. (This is simple single-user state; a
# real multi-user site would store this per-user in a session/database.)
last_intent = None

# Did the bot JUST ask for the user's name? If so, we treat the next reply as
# the name even if it's a bare word like "aarohi" (conversational capture).
awaiting_name = False


def capture_name(user_message):
    """If the message states (or, when asked, simply is) the user's name,
    save it and confirm. Returns a confirmation reply, or None.

    Two ways we learn a name:
      1. Explicit phrasing anytime: "my name is X", "call me X", ...
      2. A bare reply right after WE asked "what's your name?" (awaiting_name).
    """
    global awaiting_name

    name = chatbot.detect_name(user_message)
    if not name and awaiting_name:
        # The bot just asked, so a plain "aarohi" is almost certainly the name.
        name = chatbot.plausible_name(user_message)

    if not name:
        return None

    awaiting_name = False
    storage.save_user_name(name)
    memory["user_name"] = name  # update the in-memory copy too
    return f"Nice to meet you, {name}! I'll remember that."


def build_reply(user_message):
    """Turn one user message into a bot reply. Mirrors the terminal loop."""
    global last_intent

    user_name = memory.get("user_name")

    # 0. Did they tell us their name? Learn it and confirm.
    name_reply = capture_name(user_message)
    if name_reply is not None:
        history.append({"you": user_message, "bot": name_reply})
        storage.add_message(user_message, name_reply)
        return name_reply

    # 1. Try math first.
    reply = chatbot.try_calculate(user_message)
    if reply is not None:
        intent = "calc"
    else:
        intent = chatbot.get_intent(user_message)

        # 2. Context: "another"/"again" repeats the previous request.
        if intent == "repeat":
            if last_intent in (None, "repeat"):
                intent = None
            else:
                intent = last_intent

        reply = chatbot.get_response(intent, user_name, user_message, history)

    # 3. Save this exchange and update context.
    _save_exchange(user_message, reply, intent)
    return reply


def _save_exchange(user_message, reply, intent):
    """Record one exchange (in memory + database) and update context."""
    global last_intent, awaiting_name
    history.append({"you": user_message, "bot": reply})
    # Keep the in-memory list bounded too (the DB is trimmed in add_message).
    if len(history) > storage.MAX_MESSAGES:
        del history[:-storage.MAX_MESSAGES]
    storage.add_message(user_message, reply)
    if intent is not None:
        last_intent = intent

    # If the bot just asked for the name (ask_my_name with none stored), arm
    # conversational capture so the NEXT message is taken as the name.
    awaiting_name = intent == "ask_my_name" and not memory.get("user_name")


def stream_reply(user_message):
    """A GENERATOR that yields the reply in pieces, for live streaming.

    Rule-based answers (math, jokes, time...) are instant, so we yield them
    in one piece. Only the AI fallback is truly streamed, chunk by chunk.
    """
    user_name = memory.get("user_name")

    # Did they tell us their name? Learn it and confirm (instant).
    name_reply = capture_name(user_message)
    if name_reply is not None:
        yield name_reply
        _save_exchange(user_message, name_reply, "set_name")
        return

    # Math and rule-based intents are instant -> yield the whole reply once.
    reply = chatbot.try_calculate(user_message)
    if reply is not None:
        yield reply
        _save_exchange(user_message, reply, "calc")
        return

    intent = chatbot.get_intent(user_message)
    if intent == "repeat":
        intent = last_intent if last_intent not in (None, "repeat") else None

    if intent is not None:
        reply = chatbot.get_response(intent, user_name, user_message, history)
        yield reply
        _save_exchange(user_message, reply, intent)
        return

    # No rule matched -> stream the AI reply token by token.
    memories = memory_brain.recall(user_message)
    full_reply = ""
    for chunk in ai_brain.stream_ai(user_message, history, memories):
        full_reply += chunk
        yield chunk

    if full_reply:
        memory_brain.remember(user_message)
    else:
        # AI unavailable -> fall back to a canned reply.
        full_reply = random.choice(chatbot.FALLBACK)
        yield full_reply

    _save_exchange(user_message, full_reply, None)


@app.route("/")
def index():
    """Serve the chat web page."""
    return render_template("index.html")


@app.route("/memories")
def memories_page():
    """Show every durable fact the bot has stored about the user."""
    facts = storage.list_memories()
    return render_template("memories.html", facts=facts)


@app.route("/memories/<int:memory_id>/delete", methods=["POST"])
def delete_memory(memory_id):
    """Forget one fact, then return to the memory viewer."""
    storage.delete_memory(memory_id)
    return redirect(url_for("memories_page"))


@app.route("/reset", methods=["POST"])
def reset():
    """Make the bot forget everything: name, history, and stored facts.

    We clear the database AND the in-memory state so the running server
    immediately behaves like a fresh start (no restart needed)."""
    global last_intent, awaiting_name
    storage.reset_all()
    history.clear()
    memory["user_name"] = None
    last_intent = None
    awaiting_name = False
    return ("", 204)


@app.route("/chat", methods=["POST"])
def chat():
    """Receive a message as JSON and return the bot's reply as JSON.

    This is an API endpoint: the browser sends {"message": "..."} and we
    send back {"reply": "..."}. The web page's JavaScript handles the rest.
    """
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()

    if user_message == "":
        return jsonify({"reply": "Say something, or type 'bye'."})

    reply = build_reply(user_message)
    return jsonify({"reply": reply})


@app.route("/chat/stream", methods=["POST"])
def chat_stream():
    """Like /chat, but STREAMS the reply back as it's generated.

    We return a streaming Response: Flask keeps the connection open and sends
    each chunk our generator yields. The browser reads these chunks and
    appends them to the bubble live, so the answer appears to type itself.
    """
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()

    if user_message == "":
        return Response("Say something, or type 'bye'.", mimetype="text/plain")

    return Response(
        stream_reply(user_message),
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
