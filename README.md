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

**Optional — add a real AI brain (free, local, via Ollama):**

The bot works fine without this. But you can give it real "understanding" as a smart fallback (used only when the rules don't match). It's free and runs entirely on your computer.

1. Install Ollama from https://ollama.com/download (or `brew install ollama` on a Mac).
2. Download a small model (one time, a few GB):

```bash
ollama pull llama3.2
```

3. Make sure Ollama is running (`ollama serve`, or just open the Ollama app), then start the chatbot as usual. Now questions the rules don't recognise (e.g. "what's the capital of France?") get answered by the AI. If Ollama isn't running, the bot quietly falls back to its canned reply — nothing breaks.

You can change the model in `ai_brain.py` (the `MODEL` variable) to any model you've pulled.

**Optional — use cloud models via OpenRouter (free tier):**

Instead of running a model locally, you can use OpenRouter to reach large cloud models through one API (free models available). No install needed — it's just an HTTP API.

1. Get a free API key at https://openrouter.ai/keys
2. Set environment variables (the key is read from the environment — never hardcode secrets):

```bash
export OPENROUTER_API_KEY="sk-or-...your key..."
export CHATBOT_AI_PROVIDER="openrouter"
# optional: pick any model from https://openrouter.ai/models (":free" = no cost)
export OPENROUTER_MODEL="meta-llama/llama-3.3-70b-instruct:free"
```

3. Run the bot as usual. To switch back to local Ollama, set `CHATBOT_AI_PROVIDER=ollama` (or unset it). If the key is missing or a request fails, the bot falls back gracefully.

> Note: embeddings for long-term memory still use local Ollama (`nomic-embed-text`), independent of which chat provider you choose.

**Optional — long-term memory (semantic / RAG):**

This lets the bot remember *facts* across conversations (not just the last few messages). It needs an embedding model:

```bash
ollama pull nomic-embed-text
```

Once that's installed, open-ended things you tell the bot get stored as **embeddings** in the database, and relevant ones are automatically recalled later — even sessions afterward. Without the embedding model, the bot simply skips long-term memory and works exactly as before.

## Files in this project

| File | What it's for |
|------|---------------|
| `chatbot.py` | The program logic / "brain" (how the bot thinks). |
| `knowledge.json` | The bot's "knowledge" — keywords and responses (what it knows). |
| `storage.py` | The storage layer — saves memory in a SQLite database (`chatbot.db`). |
| `memory_brain.py` | Long-term memory: embeddings + similarity search (mini RAG). |
| `chatbot.db` | Created automatically. The SQLite database (your name + chat history). |
| `memory.json` | Legacy file. Auto-migrated into the database on first run. |
| `app.py` | The web server (Flask). Reuses the brain from `chatbot.py`. |
| `templates/index.html` | The web chat page (HTML + CSS + JavaScript). |
| `ai_brain.py` | Optional AI upgrade: talks to a local Ollama model. |
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
| **Save name + history** | **Persistence** — data that survives restarts |
| **SQLite database** (`storage.py`) | Real **SQL**: tables, `INSERT`/`SELECT`, a **storage layer**, data migration |
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
| **AI fallback** (local model via Ollama) | **Hybrid bots**: rules first, real AI when rules don't match; **system prompts** |
| **Long-term memory** (fact extraction + retrieval) | **RAG**: vectors, **cosine similarity**, semantic search, using the LLM to extract structured data |
| **Pluggable AI providers** (Ollama / OpenRouter) | **Provider abstraction**, env-var **config**, API keys, OpenAI-style APIs |
| **Streaming replies** (answer types itself, live) | **Streaming responses**, generators, reading a response body chunk-by-chunk |

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

### Memory & persistence (SQLite database)
The bot's memory now lives in a real database, `chatbot.db`, managed by
`storage.py`. There are two tables:

- `settings` — key/value pairs (e.g. `user_name`)
- `messages` — one row per exchange (`you`, `bot`, `created` timestamp)

The rest of the program doesn't know or care that it's SQLite — it just calls
`storage.load_memory()`, `storage.save_user_name()`, and `storage.add_message()`.
This is a **storage layer**: swap SQLite for PostgreSQL later by editing only
`storage.py`. Key SQL ideas you'll see there:

```sql
CREATE TABLE messages (id INTEGER PRIMARY KEY, you TEXT, bot TEXT, created TIMESTAMP);
INSERT INTO messages (you, bot) VALUES (?, ?);   -- ? prevents SQL injection
SELECT you, bot FROM messages ORDER BY id;
```

Unlike the old file approach (which rewrote everything every turn), the
database `INSERT`s just one new row per message — a big reason databases
scale better than files. Your old `memory.json` is migrated in automatically
on first run.

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

### Hybrid AI brain (Ollama)
The bot tries its **rules first** (math, time, jokes, memory). Only when no
rule matches does it ask the AI model — so fast, reliable rules stay in
control and the AI handles open-ended questions:

```
You: what is 5 + 3      -> rule (calculator)     "The answer is 8."
You: what time is it     -> rule (time)            "It's 05:20 PM ..."
You: why is the sky blue -> no rule -> AI fallback "Because sunlight scatters..."
```

`ai_brain.py` sends the message to Ollama over HTTP (the same client/server
idea). A **system prompt** shapes the AI's personality. If Ollama isn't
running, `ask_ai()` returns `None` and the bot uses a canned fallback.

### Long-term memory (embeddings + RAG + fact extraction)
Short-term memory (history) only covers the last few messages. Long-term
memory (`memory_brain.py`) remembers *facts* across sessions:

1. **extract facts** — instead of storing the raw message (much of which is
   noise), we use the LLM as a *tool*: `extract_facts()` asks it to read the
   message and write back only durable facts ("User is learning Python"),
   or `NONE` if there's nothing worth keeping.
2. **remember** — each new fact is turned into a vector by `embed()` (via
   Ollama) and stored in the `memories` table. Identical facts are skipped
   (`memory_exists()`) so we don't pile up duplicates.
3. **recall** — a new message is embedded too, then compared to every
   stored fact with **cosine similarity**; the closest in *meaning* are
   injected into the AI's system prompt.

```
You:  "I'm learning Python and prefer short answers"
      -> extracted: "User is learning Python", "User prefers short answers"
You:  "ok thanks" / "what time is it?"   -> nothing stored (just noise)
Later: "how should you explain things to me?"
      -> recalls the stored facts -> AI tailors its answer
```

Using a model to turn messy text into clean structured data (here, a list of
facts) is a hugely common real-world pattern -- the same trick powers tagging,
summarizing, and data extraction pipelines.

This is **RAG (Retrieval-Augmented Generation)**: retrieve relevant facts,
then generate. We use Ollama for embeddings and SQLite as a hand-built
vector store — no extra libraries. Needs `ollama pull nomic-embed-text`;
without it, long-term memory is skipped gracefully.

### Streaming replies (live "typing")
Normally the server waits for the *whole* AI reply, then sends it. With a
big model that means staring at an empty screen for seconds. **Streaming**
sends the answer in small pieces as the model produces them, so it appears
to type itself — exactly like ChatGPT.

How the pieces fit together:

1. **`ai_brain.stream_ai()`** is a Python **generator**: instead of
   `return`ing one string, it `yield`s chunks. It talks to the model with
   `"stream": True` and reads the reply line by line.
   - **Ollama** streams one JSON object per line (`message.content`).
   - **OpenRouter** streams *Server-Sent Events* (`data: {...}` lines with
     `choices[0].delta.content`).
2. **`/chat/stream`** in `app.py` returns a Flask streaming `Response`. The
   connection stays open and each yielded chunk is flushed immediately.
   Rule-based answers (math, jokes...) are instant, so they're yielded in
   one piece; only the AI fallback is streamed token-by-token.
3. **The browser** (`index.html`) uses `fetch()` + `response.body.getReader()`
   to read the stream and append each chunk to the message bubble live.

If the AI provider is offline, `stream_ai()` simply yields nothing and the
server falls back to a normal canned reply — so streaming never breaks the
rule-based bot. (The terminal version keeps its own simulated typing effect.)

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
| **Hybrid bot** | Rules for known tasks + an AI model for everything else. |
| **System prompt** | Instructions that shape an AI model's behavior. |
| **Database / SQL** | Tables, rows, `INSERT`/`SELECT`; a serverless DB (SQLite). |
| **Storage layer** | Hiding storage details so backends can be swapped. |
| **SQL injection** | Why query values use `?` placeholders, never string formatting. |
| **Embedding** | A vector of numbers capturing a text's *meaning*. |
| **Cosine similarity** | Measuring how close two vectors (meanings) are. |
| **RAG** | Retrieve relevant info, then let the AI generate using it. |
| **Vector store** | Where embeddings live (here, a SQLite table). |

---

## Ideas for what to build next

- **Limit / summarize history** — keep only the last N messages, or summarize old ones.
- **Per-user sessions** — so multiple people can chat without sharing memory.
- **A "memory viewer"** — a page that lists every fact the bot has stored about you.
- **Deploy it online** — host the web app so anyone can use it via a URL.

Everything you've learned here — intents, responses, fallbacks, the loop, memory, persistence, fuzzy matching, context, client/server, hybrid AI — still applies. You're building the right foundation. 🚀
