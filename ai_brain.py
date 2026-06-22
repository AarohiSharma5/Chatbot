"""
The AI "brain" -- an optional upgrade that talks to a real language model.

It supports two PROVIDERS, chosen via the CHATBOT_AI_PROVIDER env var:
  - "ollama"     : a model running locally on your computer (free, private)
  - "openrouter" : a cloud model via OpenRouter's API (free tier available)

Both speak the same OpenAI-style "messages" format, so we build the request
once and just send it to a different URL. Either way it's plain HTTP over
Python's built-in urllib -- nothing here needs `pip install`.

If the provider is unavailable (Ollama not running, or no OpenRouter key),
every function returns None so the chatbot falls back to its rule-based
replies. The AI is a bonus, never a requirement.
"""

import json
import os
import urllib.error
import urllib.request

# WHICH AI PROVIDER TO USE.
#   "ollama"     -> a model running locally on your computer (free, private)
#   "openrouter" -> a model in the cloud via OpenRouter (free tier available)
# Switch without editing code by setting an environment variable, e.g.:
#   export CHATBOT_AI_PROVIDER=openrouter
PROVIDER = os.environ.get("CHATBOT_AI_PROVIDER", "ollama")

# --- Ollama (local) settings ---
# After installing Ollama, run `ollama pull llama3.2` to download this model.
# We use /api/chat (not /api/generate) because it accepts a LIST of past
# messages -- that's how we give the AI conversation memory.
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "llama3.2"

# --- OpenRouter (cloud) settings ---
# OpenRouter exposes many models behind ONE OpenAI-style API. Get a free key
# at https://openrouter.ai/keys and set it as an environment variable:
#   export OPENROUTER_API_KEY=sk-or-...
# We read the key from the environment (NEVER hardcode secrets in code!).
# Pick any model from https://openrouter.ai/models -- ones ending in ":free"
# cost nothing (with rate limits). Override with OPENROUTER_MODEL if you like.
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get(
    "OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"
)

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
    the configured AI provider and return its reply.

    History gives SHORT-TERM memory (this conversation); memories give
    LONG-TERM memory (relevant facts recalled from the past). Returns None
    if the provider is unavailable, so the caller can fall back to a rule
    reply. We build the messages ONCE, then dispatch to the chosen provider.
    """
    messages = build_messages(message, history, memories)

    if PROVIDER == "openrouter":
        return _ask_openrouter(messages)
    return _ask_ollama(messages)


def chat_once(messages):
    """Send a custom `messages` list to the AI and return its text reply.

    Unlike ask_ai(), this does NOT add the chatbot's personality, history,
    or memories -- you provide the EXACT messages. It's a low-level helper
    for internal tasks where we use the model as a tool (e.g. pulling facts
    out of a sentence). Returns None if the provider is unavailable.
    """
    if PROVIDER == "openrouter":
        return _ask_openrouter(messages)
    return _ask_ollama(messages)


def _post_json(url, payload, headers):
    """Helper: POST a JSON `payload` to `url` and return the parsed JSON.

    Returns None on any network/parse error so callers can fall back.
    """
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", **headers}
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.URLError:
        return None
    except Exception:
        return None


def _ask_ollama(messages):
    """Get a reply from the local Ollama server."""
    result = _post_json(OLLAMA_URL, {"model": MODEL, "messages": messages, "stream": False}, {})
    if result is None or "error" in result:
        return None
    # Ollama's chat endpoint returns {"message": {"content": ...}}.
    reply = result.get("message", {}).get("content", "").strip()
    return reply or None


def _ask_openrouter(messages):
    """Get a reply from a cloud model via OpenRouter."""
    if not OPENROUTER_API_KEY:
        return None  # no key set -> fall back (set OPENROUTER_API_KEY)

    result = _post_json(
        OPENROUTER_URL,
        {"model": OPENROUTER_MODEL, "messages": messages},
        {"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
    )
    if result is None or "error" in result:
        return None
    # OpenRouter (OpenAI-style) returns {"choices": [{"message": {"content"}}]}.
    choices = result.get("choices")
    if not choices:
        return None
    reply = choices[0].get("message", {}).get("content", "").strip()
    return reply or None


# ---------------------------------------------------------------------------
# STREAMING: instead of waiting for the whole reply, we ask the model to send
# it back in small pieces ("tokens") as it's generated. Each function below is
# a GENERATOR -- it `yield`s chunks one at a time, which the web app forwards
# to the browser so the answer appears to "type" live, like ChatGPT.
# ---------------------------------------------------------------------------
def stream_ai(message, history=None, memories=None):
    """Yield the AI reply chunk-by-chunk from the configured provider.

    Yields nothing if the provider is unavailable (the caller then shows a
    normal fallback message).
    """
    messages = build_messages(message, history, memories)
    if PROVIDER == "openrouter":
        yield from _stream_openrouter(messages)
    else:
        yield from _stream_ollama(messages)


def _stream_ollama(messages):
    """Stream from local Ollama. It sends one JSON object PER LINE, each with
    a small piece of the reply in message.content."""
    payload = {"model": MODEL, "messages": messages, "stream": True}
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL, data=data, headers={"Content-Type": "application/json"}
    )

    try:
        response = urllib.request.urlopen(request, timeout=120)
    except Exception:
        return  # provider down -> yield nothing

    try:
        for raw_line in response:  # iterate the response line by line
            line = raw_line.decode("utf-8").strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            chunk = obj.get("message", {}).get("content", "")
            if chunk:
                yield chunk
            if obj.get("done"):
                break
    finally:
        response.close()


def _stream_openrouter(messages):
    """Stream from OpenRouter. It uses Server-Sent Events: lines that look
    like `data: {json}`, with each piece in choices[0].delta.content."""
    if not OPENROUTER_API_KEY:
        return

    payload = {"model": OPENROUTER_MODEL, "messages": messages, "stream": True}
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        },
    )

    try:
        response = urllib.request.urlopen(request, timeout=120)
    except Exception:
        return

    try:
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if not line or not line.startswith("data:"):
                continue
            payload_text = line[len("data:"):].strip()
            if payload_text == "[DONE]":
                break
            try:
                obj = json.loads(payload_text)
            except json.JSONDecodeError:
                continue
            delta = obj.get("choices", [{}])[0].get("delta", {}).get("content", "")
            if delta:
                yield delta
    finally:
        response.close()


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
