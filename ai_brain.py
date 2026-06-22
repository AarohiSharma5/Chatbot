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
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.2"

# A "system prompt" sets the AI's personality and rules. This is a core
# concept of modern AI chatbots: you steer behavior with instructions.
SYSTEM_PROMPT = (
    "You are a friendly, concise chatbot helping a beginner. "
    "Keep replies to 1-3 short sentences and avoid markdown."
)


def ask_ai(message):
    """Send `message` to the local Ollama model and return its reply.

    Returns the reply text, or None if Ollama is unavailable (so the
    caller can fall back to a normal rule-based reply).
    """
    payload = {
        "model": MODEL,
        "prompt": message,
        "system": SYSTEM_PROMPT,
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

    reply = result.get("response", "").strip()
    return reply or None


def is_available():
    """Quick check: is the Ollama server reachable right now?"""
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        return True
    except Exception:
        return False
