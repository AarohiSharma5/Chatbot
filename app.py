"""
A web version of our chatbot, using Flask.

The KEY idea: we don't rewrite the chatbot's brain. We IMPORT the same
functions from chatbot.py (get_intent, get_response, try_calculate, ...)
and just give them a new "front door" -- a web page instead of the
terminal. The terminal loop is replaced by a web server that answers
one message at a time over HTTP.
"""

from flask import Flask, render_template, request, jsonify

# Reuse the logic we already built and tested in chatbot.py.
import chatbot

app = Flask(__name__)

# Load any memory saved by previous runs (e.g. the user's name).
memory = chatbot.load_memory()
history = memory.get("history", [])

# CONTEXT: like the terminal version, we remember the previous intent so
# follow-ups such as "another" work. (This is simple single-user state; a
# real multi-user site would store this per-user in a session/database.)
last_intent = None


def build_reply(user_message):
    """Turn one user message into a bot reply. Mirrors the terminal loop."""
    global last_intent

    user_name = memory.get("user_name", "friend")

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

        reply = chatbot.get_response(intent, user_name)

    # 3. Save this exchange to the same memory file the terminal bot uses.
    history.append({"you": user_message, "bot": reply})
    memory["history"] = history
    chatbot.save_memory(memory)

    # 4. Remember the intent for next time.
    if intent is not None:
        last_intent = intent

    return reply


@app.route("/")
def index():
    """Serve the chat web page."""
    return render_template("index.html")


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


if __name__ == "__main__":
    # debug=True auto-reloads the server when you edit the code.
    app.run(host="127.0.0.1", port=5000, debug=True)
