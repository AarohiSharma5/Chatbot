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

import io
import json
import os
import random
import re
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
import mcp_client
import memory_brain
import storage
import tools

# Cap an uploaded file so a huge document can't exhaust memory.
MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 2 MB
DOC_CHUNK_CHARS = 800               # characters per document chunk
DOC_TOP_K = 4                       # how many chunks to feed the AI

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
    """Decorator: bounce anyone who isn't logged in to the login page.

    We also defend against STALE cookies: if the session points at a user id
    that no longer exists (e.g. a leftover anonymous id from before accounts,
    or data wiped on the old ephemeral disk), we clear it and send them to
    log in -- otherwise creating their data would hit a foreign-key error.
    """

    @wraps(view)
    def wrapped(*args, **kwargs):
        uid = current_user_id()
        if not uid:
            return redirect(url_for("login"))
        if not storage.user_exists(uid):
            session.clear()
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


def _doc_context(user_id, thread_id, query):
    """Retrieve the most relevant chunks of this thread's uploaded docs.

    Same idea as long-term memory: embed the question, compare against each
    stored chunk's embedding (cosine similarity), and return the closest few
    joined together -- to be injected into the AI prompt (RAG).
    """
    if not storage.thread_has_docs(user_id, thread_id):
        return None
    query_vec = ai_brain.embed(query)
    if query_vec is None:
        return None

    scored = []
    for text, vec in storage.get_doc_chunks(user_id, thread_id):
        scored.append((memory_brain.cosine_similarity(query_vec, vec), text))
    scored.sort(reverse=True)
    top = [text for (_, text) in scored[:DOC_TOP_K]]
    return "\n---\n".join(top) if top else None


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

    # No rule matched -> hand off to the AI, which can now CALL TOOLS on its
    # own (weather, web lookup, calculator, date/time, save-a-memory). It's
    # steered by this thread's persona and grounded in uploaded docs + memories.
    system_prompt = ai_brain.persona_prompt(storage.get_persona(user_id, thread_id))
    context = _doc_context(user_id, thread_id, user_message)
    memories = memory_brain.recall(user_id, user_message)
    messages = ai_brain.build_messages(user_message, history, memories, system_prompt, context)

    def dispatch(name, args):
        """Actually run a tool the model asked for. Returns text for the model."""
        # Tools discovered from an MCP server are routed to the MCP client.
        if mcp_client.is_mcp_tool(name):
            return mcp_client.call_tool(name, args) or "No result from MCP tool."
        if name == "get_weather":
            return tools.get_weather(args.get("place", "")) or "No weather found."
        if name == "web_answer":
            return tools.web_answer(args.get("query", "")) or "No answer found."
        if name == "calculate":
            return tools.calculate(args.get("expression", ""))
        if name == "current_datetime":
            return tools.current_datetime()
        if name == "remember_fact":
            fact = (args.get("text") or "").strip()
            if fact:
                memory_brain.remember(user_id, fact)
                return f"Saved to memory: {fact}"
            return "Nothing to save."
        return "Unknown tool."

    # Offer the model BOTH our built-in tools and any tools discovered from the
    # MCP server -- it picks whichever fits the question.
    all_schemas = tools.TOOL_SCHEMAS + mcp_client.get_tool_schemas()

    full_reply = ""
    # The tool loop is non-streaming, so we get the whole answer, then "type"
    # it out word-by-word to keep the familiar streaming feel.
    final_text = ai_brain.run_with_tools(messages, all_schemas, dispatch)
    if final_text:
        for piece in re.split(r"(\s+)", final_text):
            if piece:
                full_reply += piece
                yield piece
    else:
        # Provider unavailable (no key / offline) -> plain stream, else fallback.
        for chunk in ai_brain.stream_ai(user_message, history, memories, system_prompt, context):
            full_reply += chunk
            yield chunk

    if full_reply:
        memory_brain.remember(user_id, user_message)
    else:
        full_reply = random.choice(chatbot.FALLBACK)
        yield full_reply

    _save_exchange(user_id, thread_id, user_message, full_reply, "ai")


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
    return render_template(
        "index.html",
        display_name=storage.get_user_name(user_id),
        theme=storage.get_theme(user_id) or "light",
        personas=list(ai_brain.PERSONAS.keys()),
    )


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


@app.route("/name/clear", methods=["POST"])
@login_required
def clear_name():
    """Forget ONLY the user's name (keeps chats and memories)."""
    user_id = current_user_id()
    storage.save_user_name(user_id, None)
    _state(user_id)["awaiting_name"] = False
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


@app.route("/threads/<int:thread_id>/rename", methods=["POST"])
@login_required
def thread_rename(thread_id):
    """Rename a conversation (used by double-click in the sidebar)."""
    user_id = current_user_id()
    if not storage.thread_belongs_to(user_id, thread_id):
        return jsonify({"error": "not found"}), 404
    title = (request.get_json(silent=True) or {}).get("title", "").strip()
    if title:
        storage.rename_thread(user_id, thread_id, title[:60])
    return ("", 204)


@app.route("/threads/<int:thread_id>/persona", methods=["POST"])
@login_required
def thread_persona(thread_id):
    """Set the AI personality for one conversation."""
    user_id = current_user_id()
    if not storage.thread_belongs_to(user_id, thread_id):
        return jsonify({"error": "not found"}), 404
    persona = (request.get_json(silent=True) or {}).get("persona")
    if persona in ai_brain.PERSONAS:
        storage.set_persona(user_id, thread_id, persona)
    return ("", 204)


@app.route("/threads/<int:thread_id>/documents", methods=["GET"])
@login_required
def thread_documents(thread_id):
    """List the files uploaded to a conversation."""
    user_id = current_user_id()
    if not storage.thread_belongs_to(user_id, thread_id):
        return jsonify([])
    return jsonify(storage.list_documents(user_id, thread_id))


@app.route("/threads/<int:thread_id>/upload", methods=["POST"])
@login_required
def thread_upload(thread_id):
    """Accept a PDF/text file, chunk + embed it, and store it for this thread."""
    user_id = current_user_id()
    if not storage.thread_belongs_to(user_id, thread_id):
        return jsonify({"error": "not found"}), 404

    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "No file provided."}), 400

    raw = file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        return jsonify({"error": "File too large (2 MB max)."}), 400

    text = _extract_text(file.filename, raw)
    if not text.strip():
        return jsonify({"error": "Couldn't read any text from that file."}), 400

    stored = 0
    for chunk in _chunk_text(text, DOC_CHUNK_CHARS):
        vector = ai_brain.embed(chunk)
        if vector is None:
            continue
        storage.add_doc_chunk(user_id, thread_id, file.filename, chunk, vector)
        stored += 1

    if stored == 0:
        return jsonify({"error": "Couldn't process that file."}), 400
    return jsonify({"filename": file.filename, "chunks": stored})


@app.route("/threads/<int:thread_id>/export", methods=["GET"])
@login_required
def export_thread(thread_id):
    """Download a conversation as Markdown (default) or JSON."""
    user_id = current_user_id()
    if not storage.thread_belongs_to(user_id, thread_id):
        return ("not found", 404)

    msgs = storage.load_history(user_id, thread_id)
    if request.args.get("format") == "json":
        body = json.dumps(msgs, indent=2)
        resp = Response(body, mimetype="application/json")
        resp.headers["Content-Disposition"] = f"attachment; filename=conversation_{thread_id}.json"
        return resp

    lines = [f"# Conversation {thread_id}", ""]
    for m in msgs:
        lines.append(f"**You:** {m['you']}")
        lines.append("")
        lines.append(f"**Bot:** {m['bot']}")
        lines.append("")
    resp = Response("\n".join(lines), mimetype="text/markdown")
    resp.headers["Content-Disposition"] = f"attachment; filename=conversation_{thread_id}.md"
    return resp


@app.route("/search", methods=["GET"])
@login_required
def search():
    """Find past messages across all of this user's conversations."""
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify([])
    return jsonify(storage.search_messages(current_user_id(), query))


@app.route("/theme", methods=["POST"])
@login_required
def set_theme():
    """Persist the user's light/dark theme choice."""
    theme = (request.get_json(silent=True) or {}).get("theme")
    if theme in ("light", "dark"):
        storage.save_theme(current_user_id(), theme)
    return ("", 204)


def _extract_text(filename, raw):
    """Pull plain text from an uploaded file (PDF via pypdf, else decode)."""
    if filename.lower().endswith(".pdf"):
        try:
            import pypdf

            reader = pypdf.PdfReader(io.BytesIO(raw))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:
            return ""
    return raw.decode("utf-8", errors="ignore")


def _chunk_text(text, size):
    """Split text into ~`size`-character chunks on word boundaries."""
    chunks, current = [], ""
    for word in text.split():
        if len(current) + len(word) + 1 > size:
            if current:
                chunks.append(current)
            current = word
        else:
            current = (current + " " + word).strip()
    if current:
        chunks.append(current)
    return chunks


@app.route("/chat/stream", methods=["POST"])
@login_required
def chat_stream():
    """Receive a message in a thread and STREAM the reply back as generated."""
    user_id = current_user_id()
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    thread_id = data.get("thread_id")
    regenerate = bool(data.get("regenerate"))
    edit = bool(data.get("edit"))

    # The thread must exist and belong to this user.
    if not thread_id or not storage.thread_belongs_to(user_id, int(thread_id)):
        return Response("That conversation doesn't exist.", status=404, mimetype="text/plain")
    thread_id = int(thread_id)

    # EDIT / REGENERATE redo the last turn: drop it first. Regenerate reuses
    # the previous question; edit supplies new text.
    if regenerate:
        previous = storage.pop_last_exchange(user_id, thread_id)
        if not previous:
            return Response("Nothing to regenerate.", status=400, mimetype="text/plain")
        user_message = previous
    elif edit:
        storage.pop_last_exchange(user_id, thread_id)

    if user_message == "":
        return Response("Say something, or type 'bye'.", mimetype="text/plain")

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
