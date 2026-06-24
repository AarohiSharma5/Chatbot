"""
TOOLS -- letting the bot DO things, not just talk (a mini "agent").

Modern AI assistants don't answer every question from the model's memory.
For live facts (weather) or lookups (a quick web answer) they call a TOOL: a
real function that fetches real data. This is the "function calling" pattern.

We keep it simple and keyless:
  * weather   -> Open-Meteo (free, no API key)
  * web answer -> DuckDuckGo Instant Answer (free, no API key)

A tiny router (`try_tool`) looks at the message, decides if a tool applies,
runs it, and returns text. If nothing matches (or the network call fails) it
returns None, so the caller falls through to the normal AI reply.

Math isn't here on purpose -- the chatbot already has a calculator that runs
before we ever get to tools.
"""

import ast
import datetime
import json
import operator
import re
import urllib.parse
import urllib.request

# Open-Meteo returns weather as a numeric WMO code; this maps the common ones
# to a human description. (We don't need every code -- unknowns say "unclear".)
_WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "rimy fog", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers",
    81: "rain showers", 82: "violent rain showers", 95: "a thunderstorm",
    96: "a thunderstorm with hail", 99: "a severe thunderstorm with hail",
}


def _get_json(url, timeout=8):
    """GET a URL and parse JSON, or return None on any failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "chatbot/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except Exception:
        return None


def get_weather(place):
    """Return a one-line weather report for `place`, or None."""
    geo = _get_json(
        "https://geocoding-api.open-meteo.com/v1/search?"
        + urllib.parse.urlencode({"name": place, "count": 1})
    )
    results = (geo or {}).get("results")
    if not results:
        return None
    spot = results[0]
    lat, lon = spot["latitude"], spot["longitude"]
    label = spot["name"] + (f", {spot['country']}" if spot.get("country") else "")

    data = _get_json(
        "https://api.open-meteo.com/v1/forecast?"
        + urllib.parse.urlencode(
            {"latitude": lat, "longitude": lon, "current": "temperature_2m,weather_code,wind_speed_10m"}
        )
    )
    current = (data or {}).get("current")
    if not current:
        return None

    temp = current.get("temperature_2m")
    wind = current.get("wind_speed_10m")
    desc = _WEATHER_CODES.get(current.get("weather_code"), "unclear conditions")
    return f"Right now in {label} it's {temp}°C with {desc} (wind {wind} km/h)."


def web_answer(query):
    """Return a short factual answer for `query` via DuckDuckGo, or None."""
    data = _get_json(
        "https://api.duckduckgo.com/?"
        + urllib.parse.urlencode({"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"})
    )
    if not data:
        return None

    text = (data.get("AbstractText") or "").strip()
    if text:
        source = data.get("AbstractSource")
        return text + (f" (source: {source})" if source else "")

    # No direct abstract -> try the first related topic.
    for topic in data.get("RelatedTopics", []):
        if isinstance(topic, dict) and topic.get("Text"):
            return topic["Text"]
    return None


def try_tool(message):
    """Decide whether a tool applies to `message`; run it and return text, or None.

    This is the OLD keyword router. With native LLM tool calling (see
    TOOL_SCHEMAS below) the model decides which tool to use, so this is no
    longer on the main path -- it's kept as a simple, keyless fallback.
    """
    text = message.strip()
    lowered = text.lower()

    # --- Weather ---
    weather_match = re.search(r"(?:weather|temperature|forecast)\b.*?\bin\s+(.+)", lowered)
    if not weather_match:
        weather_match = re.search(r"\bin\s+(.+?)\s+(?:weather|temperature|forecast)\b", lowered)
    if ("weather" in lowered or "temperature" in lowered or "forecast" in lowered) and weather_match:
        place = weather_match.group(1).strip(" ?.!")
        if place:
            return get_weather(place)

    # --- Web answer ("search for X", "look up X", "who is X", "what is X") ---
    search_match = re.match(r"(?:search(?: for)?|look up|google)\s+(.+)", lowered)
    if search_match:
        return web_answer(search_match.group(1).strip(" ?.!"))

    return None


# ---------------------------------------------------------------------------
# A safe calculator (no eval of arbitrary code!). We parse the expression into
# an Abstract Syntax Tree and walk it, allowing ONLY numbers and basic math
# operators. Anything else raises, so "import os" or function calls can't run.
# ---------------------------------------------------------------------------
_MATH_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _eval_node(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _MATH_OPS:
        return _MATH_OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _MATH_OPS:
        return _MATH_OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError("unsupported expression")


def calculate(expression):
    """Safely evaluate an arithmetic expression like '12 * (3 + 4)'."""
    try:
        value = _eval_node(ast.parse(expression, mode="eval").body)
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return f"{expression} = {value}"
    except Exception:
        return "I couldn't evaluate that expression."


def current_datetime():
    """Return the current local date and time as a sentence."""
    now = datetime.datetime.now()
    return now.strftime("It is %I:%M %p on %A, %d %B %Y.")


# ---------------------------------------------------------------------------
# TOOL SCHEMAS -- the JSON descriptions we hand to the LLM so it knows what
# tools exist, what they do, and which arguments they take. The model reads
# these and decides (on its own) when to "call" one. This is the heart of
# native function calling.
# ---------------------------------------------------------------------------
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a city or place name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "place": {"type": "string", "description": "City or place, e.g. 'Tokyo'"}
                },
                "required": ["place"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_answer",
            "description": "Look up a short factual answer from the web (people, places, definitions).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look up"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate an arithmetic expression and return the result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "e.g. '12 * (3 + 4)'"}
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "current_datetime",
            "description": "Get the current date and time.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember_fact",
            "description": "Save a durable fact about the user to long-term memory for future chats.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The fact to remember, e.g. 'User prefers Python'"}
                },
                "required": ["text"],
            },
        },
    },
]
