# My First Chatbot 🤖

A simple, **rule-based** chatbot written in pure Python. No libraries to install, no AI APIs — just the core ideas so you can understand exactly how a chatbot works.

## How to run it

Open a terminal in this folder and run:

```bash
python3 chatbot.py
```

Then type messages and press Enter. Try things like `hello`, `how are you`, `what's your name`, `thanks`, and `bye`.

---

## The fundamentals: how a chatbot works

Every chatbot, from this tiny one to ChatGPT, is built from the same 4 building blocks:

### 1. Input — listening to the user
The bot reads a message from the user. In our code that's:

```python
user_message = input("You: ")
```

### 2. Understanding — figuring out what the user *wants*
This is the most important part. The bot tries to map the message to an **intent** (the user's goal).

- `"hi"`, `"hello"`, `"hey"` → intent: **greeting**
- `"bye"`, `"see you"` → intent: **goodbye**

Our bot does this with simple **keyword matching**: it looks for known words in the message. This is a basic form of **NLU (Natural Language Understanding)**.

> Real AI chatbots replace this step with machine learning models that understand meaning, not just keywords — but the *goal* is identical: turn a sentence into an intent.

### 3. Response — deciding what to say back
Once the bot knows the intent, it picks a reply. We store replies in a dictionary and pick one at random so it feels less repetitive:

```python
RESPONSES = {
    "greeting": ["Hello!", "Hi there!", "Hey!"],
    ...
}
```

### 4. The conversation loop — keep going until done
A chatbot is just this cycle repeated:

```
read input → understand → respond → repeat
```

That's the `while True:` loop in `main()`. It keeps chatting until you say "bye".

---

## What happens when you type a message

```
You type:  "Hello there!"
   │
   ▼
get_intent()  →  finds the word "hello"  →  intent = "greeting"
   │
   ▼
get_response()  →  picks a random greeting reply
   │
   ▼
ChatBot: "Hi there! What's on your mind?"
```

If no keyword matches, the bot uses a **fallback** reply ("Sorry, I didn't understand"). Handling the "I don't know" case gracefully is a key part of good chatbot design.

---

## Key vocabulary

| Term | Meaning |
|------|---------|
| **Intent** | What the user wants (greet, say bye, ask a question). |
| **Keyword matching** | Detecting intent by looking for specific words. |
| **Fallback** | The reply used when the bot doesn't understand. |
| **Conversation loop** | The read → respond → repeat cycle. |
| **NLU** | Natural Language Understanding — turning text into meaning. |

---

## Make it your own (try these!)

1. **Add a new intent.** For example, teach it to respond to "tell me a joke".
   - Add keywords in `KEYWORDS` and replies in `RESPONSES`.
2. **Give it memory.** Ask the user's name and use it in replies.
3. **Add the time.** Make it answer "what time is it?" using Python's `datetime`.

When you're comfortable with all of this, the natural next steps are:
- Using a library like **ChatterBot**, or
- Connecting to an AI model (like the OpenAI API) for real "understanding".

But everything you learn here — intents, responses, fallbacks, the loop — still applies. You're building the right foundation. 🚀
