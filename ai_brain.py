"""
The AI "brain" -- an optional upgrade that talks to a local Ollama model.

Ollama runs a small web server on your own computer at localhost:11434.
We send it a prompt over HTTP and get back a generated reply. This is the
SAME client/server idea as our Flask app: here, OUR program is the client
and Ollama is the server.

Nothing here needs `pip install` -- we use Python's built-in urllib.

If Ollama isn't installed or running, every function returns None so the
chatbot can fall back to its normal rule-based replies. The AI is a bonus,
never a requirement.
"""

import json
import urllib.error
import urllib.request

# Where Ollama listens, and which model to use. After installing Ollama,
# run `ollama pull llama3.2` once to download this model. You can swap in
# any model you've pulled (e.g. "qwen2.5:3b", "phi3", "mistral").
#
# We use the /api/chat endpoint (not /api/generate) because it accepts a
# LIST of past messages -- that's how we give the AI conversation memory.
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "llama3.2"

# For long-term memory we turn text into "embeddings" (vectors). That needs
# a dedicated embedding model. Install it once with: ollama pull nomic-embed-text
EMBED_URL = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"

# How many recent exchanges to send the AI for context. Keeping this small
# stays fast and avoids overwhelming the model with the whole history.
HISTORY_TURNS = 6

# A "system prompt" sets the AI's personality and rules. This is a core
# concept of modern AI chatbots: you steer behavior with instructions.
SYSTEM_PROMPT = (
    "You are a friendly psycologist(more of a friend, dont let the user know that youre a psycologist), concise chatbot helping a friend. "
    "Keep replies friendly and soothing, concise sentences and avoid markdown. dont let the user know that youre a psycologist."
    
)


def build_messages(message, history, memories=None):
    """Turn our chat history into the message list Ollama expects.

    Ollama's chat format is a list of {"role", "content"} items, where role
    is "system", "user", or "assistant". We start with the system prompt
    (optionally enriched with long-term memories), replay the recent
    conversation, then add the new user message.
    """
    system = SYSTEM_PROMPT
    if memories:
        # Inject relevant long-term memories so the AI can use them.
        facts = "\n".join(f"- {m}" for m in memories)
        system += "\n\nThings you remember about the user:\n" + facts

    messages = [{"role": "system", "content": system}]

    recent = history[-HISTORY_TURNS:] if history else []
    for turn in recent:
        messages.append({"role": "user", "content": turn["you"]})
        messages.append({"role": "assistant", "content": turn["bot"]})

    messages.append({"role": "user", "content": message})
    return messages


def ask_ai(message, history=None, memories=None):
    """Send `message` (plus recent `history` and long-term `memories`) to
    Ollama and return its reply.

    History gives SHORT-TERM memory (this conversation); memories give
    LONG-TERM memory (relevant facts recalled from the past). Returns None
    if Ollama is unavailable, so the caller can fall back to a rule reply.
    """
    payload = {
        "model": MODEL,
        "messages": build_messages(message, history, memories),
        "stream": False,  # get the whole reply at once, not piece by piece
    }

    # Build the HTTP POST request with a JSON body.
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.load(response)
    except urllib.error.URLError:
        # Ollama isn't running or isn't installed -> let the bot fall back.
        return None
    except Exception:
        return None

    # If the model isn't downloaded yet, Ollama returns an "error" field.
    if "error" in result:
        return None

    # The chat endpoint returns {"message": {"role": ..., "content": ...}}.
    reply = result.get("message", {}).get("content", "").strip()
    return reply or None


def embed(text):
    """Turn `text` into an EMBEDDING: a list of numbers (a vector) that
    captures its MEANING. Texts with similar meaning produce similar
    vectors, which is what powers semantic memory search.

    Returns the vector, or None if the embedding model isn't available
    (so the caller can skip long-term memory and carry on).
    """
    payload = {"model": EMBED_MODEL, "prompt": text}
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        EMBED_URL,
        data=data,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.URLError:
        return None
    except Exception:
        return None

    if "error" in result:
        return None  # model not pulled yet -> skip memory gracefully

    vector = result.get("embedding")
    return vector or None


def is_available():
    """Quick check: is the Ollama server reachable right now?"""
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        return True
    except Exception:
        return False
