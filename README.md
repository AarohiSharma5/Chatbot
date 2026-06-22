# My First Chatbot 🤖

A simple, **rule-based** chatbot written in pure Python. No external libraries to install — just the core ideas so you can understand exactly how a chatbot works, built up feature by feature.

## How to run it

Open a terminal in this folder and run:

```bash
python3 chatbot.py
```

Then type messages and press Enter. Try things like `hello`, `how are you`, `what time is it`, `tell me a joke`, `what is 5 + 3`, `what is my name`, and `bye`.

## Files in this project

| File | What it's for |
|------|---------------|
| `chatbot.py` | The program logic (how the bot thinks). |
| `knowledge.json` | The bot's "knowledge" — keywords and responses (what it knows). |
| `memory.json` | Created automatically. Stores your name + chat history between runs. |

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

---

## Ideas for what to build next (Level 3)

- **Synonyms & typo tolerance** ("helo" → "hello") — string similarity.
- **Context** — remember the *previous* question so follow-ups make sense. This is the heart of real conversation flow.
- **Limit history size** — keep only the last N messages (`history[-50:]`).
- **A web interface** — chat in a browser using Flask/FastAPI.
- **Connect to a real AI model** (e.g. the OpenAI API) — real NLU and the modern approach.

Everything you've learned here — intents, responses, fallbacks, the loop, memory, persistence — still applies. You're building the right foundation. 🚀
