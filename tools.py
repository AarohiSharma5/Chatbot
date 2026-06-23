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

import json
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
    """Decide whether a tool applies to `message`; run it and return text, or None."""
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
