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
import sys
import urllib.error
import urllib.request


def _log(message):
    """Print a diagnostic line to stderr (shows up in server logs)."""
    print(f"[ai_brain] {message}", file=sys.stderr, flush=True)

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

# Free models are shared and often "rate-limited upstream" (HTTP 429). So we
# keep a CHAIN of free models: if the first is busy, we automatically try the
# next. Your chosen OPENROUTER_MODEL goes first; the rest are smaller, usually
# less-congested backups. (We de-duplicate while preserving order.)
OPENROUTER_MODELS = list(dict.fromkeys([
    OPENROUTER_MODEL,
    "openai/gpt-oss-20b:free",
    "google/gemma-4-31b-it:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "meta-llama/llama-3.2-3b-instruct:free",
]))

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
    "You are a warm, friendly chatbot helping a friend. Keep replies kind, "
    "supportive, and fairly concise. You may use simple markdown (bold, "
    "lists, code blocks) when it makes the answer clearer."
)

# PERSONAS let each conversation have its own personality. The user picks one
# per thread; we feed the matching instructions to the model as its system
# prompt. This is just prompt-engineering: same model, different "character".
PERSONAS = {
    "friend": SYSTEM_PROMPT,
    "tutor": (
        "You are a patient tutor. Explain concepts step by step in plain "
        "language, give small examples, and check understanding. Use markdown "
        "headings, lists, and code blocks where helpful."
    ),
    "coder": (
        "You are an expert programming assistant. Be precise and practical. "
        "Prefer working code in fenced code blocks, note edge cases, and keep "
        "prose short."
    ),
    "concise": (
        "You are a concise assistant. Answer in as few words as possible -- "
        "ideally one or two sentences. No fluff, no preamble."
    ),
}
DEFAULT_PERSONA = "friend"


def persona_prompt(key):
    """Return the system prompt for a persona key (falling back to default)."""
    return PERSONAS.get(key or DEFAULT_PERSONA, PERSONAS[DEFAULT_PERSONA])


def build_messages(message, history, memories=None, system_prompt=None, context=None):
    """Turn our chat history into the message list the model expects.

    The format is a list of {"role", "content"} items, where role is
    "system", "user", or "assistant". We start with the system prompt
    (optionally a persona, plus long-term memories and document excerpts),
    replay the recent conversation, then add the new user message.
    """
    system = system_prompt or SYSTEM_PROMPT
    # Always mirror the user's language -- reply in whatever language they wrote.
    system += (
        "\n\nAlways reply in the same language the user writes in. If they "
        "switch languages, switch with them. "
        "Answer the user's MOST RECENT message directly; don't assume they "
        "want code or a continuation of an earlier topic unless they ask. "
        "If they ask how to say something in another language, simply say it "
        "in that language with a short note."
    )
    if context:
        # Excerpts retrieved from the user's uploaded documents (doc RAG).
        system += "\n\nUse these excerpts from the user's documents to answer:\n" + context
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


def ask_ai(message, history=None, memories=None, system_prompt=None, context=None):
    """Send `message` (plus context) to the configured AI and return its reply."""
    messages = build_messages(message, history, memories, system_prompt, context)

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


# ---------------------------------------------------------------------------
# NATIVE TOOL (FUNCTION) CALLING.
#
# We send the model a list of tool SCHEMAS. The model may answer normally, or
# it may reply asking us to run a tool (a "tool_call") with some arguments. We
# run the real function, feed the result back as a role:"tool" message, and ask
# again -- looping until the model is happy to give a final text answer.
#
# `dispatch(name, args_dict) -> str` is supplied by the caller (app.py), which
# knows how to actually run each tool (and has the user's id for memory).
# ---------------------------------------------------------------------------
def _chat_with_tools(messages, schemas):
    """One non-streaming chat turn WITH tools. Returns the assistant message
    dict (which may contain `tool_calls`), or None if the provider failed."""
    if PROVIDER == "openrouter":
        if not OPENROUTER_API_KEY:
            _log("OPENROUTER_API_KEY not set -> tools unavailable")
            return None
        for model in OPENROUTER_MODELS:
            result = _post_json(
                OPENROUTER_URL,
                {"model": model, "messages": messages, "tools": schemas, "tool_choice": "auto"},
                {"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            )
            if result is None:
                continue
            if "error" in result:
                _log(f"{model} tools error: {str(result['error'])[:160]} -> trying next")
                continue
            choices = result.get("choices")
            if choices:
                return choices[0].get("message") or {}
        return None

    # Ollama (local). Models like llama3.2 support tools on /api/chat.
    result = _post_json(
        OLLAMA_URL, {"model": MODEL, "messages": messages, "tools": schemas, "stream": False}, {}
    )
    if result is None or "error" in result:
        return None
    return result.get("message") or {}


def run_with_tools(messages, schemas, dispatch, max_rounds=4):
    """Run the model+tool loop and return the FINAL text answer (or None if the
    provider is unavailable). `messages` is mutated to include tool exchanges.

    Because tools need a non-streaming round-trip, the final answer comes back
    whole -- the caller can "fake stream" it for the usual typing effect.
    """
    for _ in range(max_rounds):
        msg = _chat_with_tools(messages, schemas)
        if msg is None:
            return None
        calls = msg.get("tool_calls") or []
        if not calls:
            return (msg.get("content") or "").strip() or None

        # The model wants tools. Record its request, run each tool, feed results.
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for call in calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            raw_args = fn.get("arguments")
            try:
                args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args or "{}")
            except Exception:
                args = {}
            output = dispatch(name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id", ""),
                "name": name,
                "content": str(output),
            })

    # Ran out of rounds -> one last attempt for a plain answer.
    msg = _chat_with_tools(messages, schemas)
    if msg is None:
        return None
    return (msg.get("content") or "").strip() or None


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
    except urllib.error.HTTPError as error:
        # The server replied with an error code (401 bad key, 402 no credit,
        # 404 bad model, 429 rate limit...). Log the body so we can see why.
        try:
            body = error.read().decode("utf-8")[:300]
        except Exception:
            body = "<no body>"
        _log(f"HTTP {error.code} from {url}: {body}")
        return None
    except urllib.error.URLError as error:
        _log(f"network error contacting {url}: {error.reason}")
        return None
    except Exception as error:
        _log(f"unexpected error contacting {url}: {error}")
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
    """Get a reply from a cloud model via OpenRouter, trying each model in the
    chain until one succeeds (free models are often rate-limited)."""
    if not OPENROUTER_API_KEY:
        _log("OPENROUTER_API_KEY is not set -> using rule-based fallback")
        return None

    for model in OPENROUTER_MODELS:
        result = _post_json(
            OPENROUTER_URL,
            {"model": model, "messages": messages},
            {"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
        )
        if result is None:
            continue  # error already logged -> try the next model
        if "error" in result:
            _log(f"{model} error: {str(result['error'])[:200]} -> trying next")
            continue
        # OpenRouter (OpenAI-style) returns {"choices":[{"message":{"content"}}]}.
        choices = result.get("choices")
        if choices:
            reply = choices[0].get("message", {}).get("content", "").strip()
            if reply:
                return reply
    return None


# ---------------------------------------------------------------------------
# STREAMING: instead of waiting for the whole reply, we ask the model to send
# it back in small pieces ("tokens") as it's generated. Each function below is
# a GENERATOR -- it `yield`s chunks one at a time, which the web app forwards
# to the browser so the answer appears to "type" live, like ChatGPT.
# ---------------------------------------------------------------------------
def stream_ai(message, history=None, memories=None, system_prompt=None, context=None):
    """Yield the AI reply chunk-by-chunk from the configured provider.

    Yields nothing if the provider is unavailable (the caller then shows a
    normal fallback message).
    """
    messages = build_messages(message, history, memories, system_prompt, context)
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
    """Stream from OpenRouter, trying each model in the chain until one
    accepts the request (free models are often rate-limited with HTTP 429).

    It uses Server-Sent Events: lines like `data: {json}`, with each piece in
    choices[0].delta.content."""
    if not OPENROUTER_API_KEY:
        _log("OPENROUTER_API_KEY is not set -> using rule-based fallback")
        return

    for model in OPENROUTER_MODELS:
        payload = {"model": model, "messages": messages, "stream": True}
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
        except urllib.error.HTTPError as error:
            try:
                body = error.read().decode("utf-8")[:200]
            except Exception:
                body = "<no body>"
            _log(f"{model} stream HTTP {error.code}: {body} -> trying next")
            continue  # this model is busy -> try the next one
        except Exception as error:
            _log(f"{model} stream error: {error} -> trying next")
            continue

        # This model accepted the request: stream its reply and stop here.
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
        return  # done streaming from a working model


# Dimensions for the LOCAL embedding fallback (below). Any fixed size works;
# 384 is a reasonable balance between detail and speed.
LOCAL_EMBED_DIM = 384


def _local_embed(text):
    """A tiny, dependency-free embedding used when no embedding model is
    available (e.g. in the cloud, where there's no local Ollama).

    It's the classic "hashing trick": we split the text into words, hash each
    word into one of LOCAL_EMBED_DIM buckets, and count how often each bucket
    is hit. Then we normalise to unit length. It captures word OVERLAP rather
    than deep meaning -- weaker than a real model, but it works everywhere and
    keeps semantic-ish search (and document RAG) functioning in production.
    """
    import hashlib
    import math
    import re

    vector = [0.0] * LOCAL_EMBED_DIM
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        # md5 is a STABLE hash (unlike Python's built-in hash(), which is
        # randomised per process) -- so stored vectors stay valid after a
        # restart and still match freshly-embedded queries.
        bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % LOCAL_EMBED_DIM
        vector[bucket] += 1.0

    length = math.sqrt(sum(v * v for v in vector))
    if length == 0:
        return None
    return [v / length for v in vector]


def embed(text):
    """Turn `text` into an EMBEDDING: a list of numbers (a vector) that
    captures its MEANING. Texts with similar meaning produce similar
    vectors, which is what powers semantic memory and document search.

    Tries the real embedding model (Ollama) first; if it isn't reachable,
    falls back to a simple local embedding so memory/RAG still work.
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
        if "error" not in result:
            vector = result.get("embedding")
            if vector:
                return vector
    except Exception:
        pass  # model unreachable -> fall through to the local fallback

    return _local_embed(text)


def is_available():
    """Quick check: is the Ollama server reachable right now?"""
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        return True
    except Exception:
        return False
