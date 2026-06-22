# My First Chatbot 🤖

A simple, **rule-based** chatbot written in pure Python. No external libraries to install — just the core ideas so you can understand exactly how a chatbot works, built up feature by feature.

## How to run it

**Option A — in the terminal:**

```bash
python3 chatbot.py
```

Then type messages and press Enter. Try things like `hello`, `how are you`, `what time is it`, `tell me a joke`, `what is 5 + 3`, `what is my name`, and `bye`.

**Option B — in the browser (web app):**

```bash
pip install -r requirements.txt   # one-time: installs Flask
python3 app.py
```

Then open **http://127.0.0.1:5000** in your browser. Press `Ctrl+C` in the terminal to stop the server.

## Files in this project

| File | What it's for |
|------|---------------|
| `chatbot.py` | The program logic / "brain" (how the bot thinks). |
| `knowledge.json` | The bot's "knowledge" — keywords and responses (what it knows). |
| `memory.json` | Created automatically. Stores your name + chat history between runs. |
| `app.py` | The web server (Flask). Reuses the brain from `chatbot.py`. |
| `templates/index.html` | The web chat page (HTML + CSS + JavaScript). |
| `requirements.txt` | The list of external packages to install (just Flask). |

> Deleting `memory.json` makes the bot "forget" you. Editing `knowledge.json` teaches it new words/replies **without touching the code**.

---

## The fundamentals: how a chatbot works

Every chatbot, from this tiny one to ChatGPT, is built from the same 4 building blocks:

1. **Input** — read a message from the user (`input(...)`).
2. **Understanding** — map the message to an **intent** (the user's goal), using keyword matching. This is a basic form of **NLU (Natural Language Understanding)**.
3. **Response** — pick what to say back based on the intent.
4. **Conversation loop** — repeat *read → understand → respond* until the user leaves.

If nothing matches, the bot uses a **fallback** reply. Handling "I don't understand" gracefully is a key part of good chatbot design.

---

## Features (and the concepts each one teaches)

### Level 1 — Beginner

| Feature | Concept you learn |
|---|---|
| Keyword → intent → response | The core chatbot pipeline |
| **Whole-word matching** | **Tokenization** — splitting text into words so `"this"` doesn't match `"hi"` |
| **Remember the user's name** | **State/memory** — a variable that lives across the conversation |
| **Tell the time/date** | Using another **module** (`datetime`) + dynamic replies |
| **Tell a random joke** | Reusing `random` with bigger response lists |
| **Clean exit** | `break`, `continue`, and program flow |

### Level 2 — Intermediate

| Feature | Concept you learn |
|---|---|
| **Save name + history to a file** | **Persistence** — data that survives restarts (`json`, file read/write) |
| **Conversation history log** | A growing **list of dictionaries** |
| **Load responses from `knowledge.json`** | **Separating data from code** — change behavior by editing data, not logic |
| **Intent scoring** | Pick the *best* intent by counting keyword matches, not the first match |
| **Simple calculator** | Parsing numbers from text with a **regular expression** (`re`) |
| **Typing effect** | Loops + `time.sleep` for nicer UX |

### Level 3 — Advanced

| Feature | Concept you learn |
|---|---|
| **Typo tolerance** (`helo` → `hello`) | **Fuzzy matching** / string similarity with `difflib` |
| **Context** (`another` repeats the last request) | Tracking the previous turn — the basis of conversation flow |
| **Web interface** (chat in a browser) | **Client/server** apps: Flask backend + HTML/JS frontend talking over HTTP |

---

## How the trickier parts work

### Tokenization (whole-word matching)
We split the message into words and strip punctuation, then check whole words:

```python
words = [word.strip(string.punctuation) for word in text.split()]
# single-word keyword must be a WHOLE word; phrases are matched in the full text
```

This stops `"this"` (which contains the letters `hi`) from triggering a greeting.

### Intent scoring
Instead of returning the first match, we count how many keywords match each intent and choose the highest:

```python
return max(scores, key=scores.get)  # the intent with the most matches
```

### Memory & persistence
The bot's memory is a dictionary saved to `memory.json`:

```json
{ "user_name": "Aarohi", "history": [ { "you": "hello", "bot": "Hi there!" } ] }
```

`json.dump` writes it; `json.load` reads it back next time. That's why the bot greets you by name even after you close it.

### Calculator (regex)
A regular expression finds `number operator number` inside a sentence:

```python
pattern = r"(\d+(?:\.\d+)?)\s*([+\-*/])\s*(\d+(?:\.\d+)?)"
```

If found, we do the math; if not, the bot falls back to normal replies.

### Typo tolerance (fuzzy matching)
`difflib` measures how similar two words are (0.0 to 1.0). If a typed word is
close enough to a keyword, it still counts as a match:

```python
ratio = difflib.SequenceMatcher(None, "helo", "hello").ratio()  # ~0.89
```

### Context (remembering the last turn)
We keep a `last_intent` variable across turns. When the user says "another",
the bot repeats whatever they asked for last:

```
You: tell me a joke   -> a joke
You: another          -> a different joke (context: last_intent was "joke")
```

### Web interface (Flask)
The web app reuses the SAME brain — `app.py` imports `get_intent`,
`get_response`, and `try_calculate` from `chatbot.py`. The only thing that
changes is the "front door":

```
Terminal version:  input()  ->  brain  ->  print()
Web version:        browser  ->  HTTP POST /chat  ->  brain  ->  JSON reply  ->  browser
```

The browser (`templates/index.html`) sends your message to the Flask server
as JSON, the server runs the same logic, and the reply is sent back and
"typed out" on screen.

---

## Key vocabulary

| Term | Meaning |
|------|---------|
| **Intent** | What the user wants (greet, ask the time, do math). |
| **Tokenization** | Splitting text into individual words ("tokens"). |
| **State / memory** | Information the bot keeps during (and across) a conversation. |
| **Persistence** | Saving data so it survives the program closing. |
| **Fallback** | The reply used when the bot doesn't understand. |
| **NLU** | Natural Language Understanding — turning text into meaning. |
| **Regex** | A pattern language for finding text (used by the calculator). |
| **Fuzzy matching** | Matching words that are *similar*, not identical (typo tolerance). |
| **Context** | Using the previous turn to interpret the current one. |
| **Client/server** | A frontend (browser) and backend (Flask) talking over HTTP. |
| **API endpoint** | A URL like `/chat` that takes JSON in and sends JSON out. |

---

## Ideas for what to build next

- **Limit history size** — keep only the last N messages (`history[-50:]`).
- **Per-user sessions** — so multiple people can chat without sharing memory.
- **Connect to a real AI model** (e.g. the OpenAI API) — real NLU and the modern approach.

Everything you've learned here — intents, responses, fallbacks, the loop, memory, persistence, fuzzy matching, context, client/server — still applies. You're building the right foundation. 🚀
