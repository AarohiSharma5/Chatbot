"""
A simple rule-based chatbot.

"Rule-based" means the bot doesn't actually "think" or "learn".
Instead, it follows rules YOU write: "if the user says X, reply with Y".
This is how the very first chatbots worked, and it's the best way to
understand the core ideas before moving on to AI/machine-learning bots.
"""

import datetime
import difflib
import json
import random
import re
import string
import time

import ai_brain  # optional AI upgrade (used only as a smart fallback)
import storage   # where the bot's memory is saved (SQLite database)


# ---------------------------------------------------------------------------
# STEP 1: The "knowledge" of the bot (loaded from a separate data file).
#
# Previously the keywords and responses lived right here in the code. We've
# now moved them into "knowledge.json". This is a big real-world idea:
# SEPARATING DATA FROM CODE. You can teach the bot new things by editing a
# plain text file, without touching the program logic at all.
# ---------------------------------------------------------------------------
KNOWLEDGE_FILE = "knowledge.json"


def load_knowledge():
    """Read the bot's keywords and responses from the JSON data file."""
    with open(KNOWLEDGE_FILE, "r") as file:
        return json.load(file)


knowledge = load_knowledge()
KEYWORDS = knowledge["keywords"]    # which words signal which intent
RESPONSES = knowledge["responses"]  # what the bot can say per intent
FALLBACK = knowledge["fallback"]    # replies for "I didn't understand"


# ---------------------------------------------------------------------------
# PERSISTENCE: the bot's memory now lives in a SQLite database.
#
# All the database details (tables, SQL queries) live in storage.py. From
# here we just call storage.load_memory(), storage.save_user_name(), and
# storage.add_message() -- we don't care HOW they store the data. That clean
# separation is exactly why we could later swap SQLite for PostgreSQL by
# editing only storage.py.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# STEP 2: Understanding the user ("intent recognition") with SCORING.
#
# Instead of returning the FIRST intent that matches, we now count how many
# keywords match for each intent and pick the BEST one (highest score). This
# handles messages that contain several clues, e.g. "hi, what's the time?".
# ---------------------------------------------------------------------------
def is_similar(word_a, word_b, threshold=0.8):
    """Return True if two words are SIMILAR enough (handles typos).

    difflib compares the words and gives a ratio from 0.0 (totally
    different) to 1.0 (identical). "helo" vs "hello" scores about 0.89,
    so with a threshold of 0.8 it counts as a match.
    """
    ratio = difflib.SequenceMatcher(None, word_a, word_b).ratio()
    return ratio >= threshold


def get_intent(message):
    """Return the best-matching intent for the message, or None."""
    # Lower-casing makes matching case-insensitive ("Hi" == "hi").
    text = message.lower()

    # TOKENIZATION: split the sentence into a list of individual words, then
    # strip punctuation so "hello!" becomes "hello".
    words = [word.strip(string.punctuation) for word in text.split()]

    # Count keyword matches per intent. {"greeting": 2, "time": 1, ...}
    scores = {}
    for intent, keywords in KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if " " in keyword:
                # A PHRASE (e.g. "how are you"): look in the full text.
                if keyword in text:
                    score += 1
            else:
                # A SINGLE WORD (e.g. "hi"): must match a WHOLE word...
                if keyword in words:
                    score += 1
                # ...or a CLOSE word, to forgive typos like "helo" -> "hello".
                elif any(is_similar(keyword, word) for word in words):
                    score += 1
        if score > 0:
            scores[intent] = score

    # No keyword matched anything -> we don't understand.
    if not scores:
        return None

    # Return the intent with the HIGHEST score.
    # max(..., key=scores.get) means "the key whose value is largest".
    return max(scores, key=scores.get)


# ---------------------------------------------------------------------------
# A SIMPLE CALCULATOR.
#
# This lets the bot answer things like "what is 5 + 3?". We use a "regular
# expression" (regex) to FIND a math pattern inside the sentence: a number,
# an operator (+ - * /), and another number.
# ---------------------------------------------------------------------------
def try_calculate(message):
    """If the message contains simple math, return the answer text.

    Returns None if there's no math to do, so the caller knows to fall
    back to normal chatbot replies.
    """
    # \d+ means "one or more digits". (?:\.\d+)? optionally allows decimals.
    # [+\-*/] means "one of these operators". \s* allows optional spaces.
    pattern = r"(\d+(?:\.\d+)?)\s*([+\-*/])\s*(\d+(?:\.\d+)?)"
    match = re.search(pattern, message)

    if match is None:
        return None  # no math found

    # The three "groups" captured by the parentheses in the pattern.
    left = float(match.group(1))
    operator = match.group(2)
    right = float(match.group(3))

    if operator == "+":
        result = left + right
    elif operator == "-":
        result = left - right
    elif operator == "*":
        result = left * right
    else:  # division
        if right == 0:
            return "I can't divide by zero!"
        result = left / right

    # Show whole numbers without a trailing ".0" (4.0 -> 4).
    if result == int(result):
        result = int(result)

    return f"The answer is {result}."


# ---------------------------------------------------------------------------
# STEP 3: Producing a response.
# ---------------------------------------------------------------------------
def get_response(intent, user_name, message="", history=None):
    """Decide what the bot should say back, based on the detected intent.

    `user_name` (the bot's "memory") lets us personalise some replies.
    `message` is the raw user text, used only for the AI fallback.
    `history` is the recent conversation, given to the AI for context.
    """
    if intent is None:
        # HYBRID BRAIN: no rule matched, so ask the local AI model, passing
        # recent history so it can handle follow-ups. If it's not running,
        # ask_ai() returns None and we use a canned fallback.
        ai_reply = ai_brain.ask_ai(message, history)
        if ai_reply:
            return ai_reply
        return random.choice(FALLBACK)

    # Special case: the user is asking us to recall their name.
    if intent == "ask_my_name":
        return f"Your name is {user_name}, of course!"

    # The date/time changes constantly, so we build this reply FRESH.
    if intent == "time":
        now = datetime.datetime.now()
        clock = now.strftime("%I:%M %p")          # e.g. "05:20 PM"
        day = now.strftime("%A, %d %B %Y")        # e.g. "Monday, 22 June 2026"
        return f"It's {clock} on {day}."

    # Personalise greetings with the remembered name.
    if intent == "greeting":
        return f"{random.choice(RESPONSES['greeting'])} Nice to see you, {user_name}!"

    return random.choice(RESPONSES[intent])


# ---------------------------------------------------------------------------
# A TYPING EFFECT.
#
# Printing the whole reply instantly feels robotic. Printing one character
# at a time (with a tiny pause) makes the bot feel like it's "typing".
# ---------------------------------------------------------------------------
def slow_print(text, delay=0.02):
    """Print text one character at a time, then move to a new line."""
    for char in text:
        # end="" stops print from adding a newline after each character.
        # flush=True forces the character to appear immediately.
        print(char, end="", flush=True)
        time.sleep(delay)  # pause briefly between characters
    print()  # finally, move to the next line


# ---------------------------------------------------------------------------
# STEP 4: The conversation loop.
#
# A chatbot is really just a loop: read input -> respond -> repeat,
# until the user decides to leave.
# ---------------------------------------------------------------------------
def main():
    print("ChatBot: Hi! I'm a simple chatbot. Type 'bye' to leave.")

    # Load whatever we saved during previous runs (from the database).
    memory = storage.load_memory()
    user_name = memory.get("user_name")

    # The chat history (a list of past exchanges). We keep it in memory too,
    # so we can pass recent turns to the AI for context.
    history = memory.get("history", [])

    if user_name:
        print(f"ChatBot: Welcome back, {user_name}!")
        print(f"ChatBot: We've exchanged {len(history)} messages before.\n")
    else:
        user_name = input("ChatBot: What's your name?\nYou: ").strip()
        storage.save_user_name(user_name)
        print(f"ChatBot: Nice to meet you, {user_name}! I'll remember you.\n")

    # CONTEXT: remember the intent of the PREVIOUS turn. This lets the bot
    # understand follow-ups like "another" (= do the last thing again).
    last_intent = None

    while True:
        # 1. Read what the user typed (.strip() removes stray spaces).
        user_message = input("You: ").strip()

        # If the user just pressed Enter, gently re-prompt. "continue"
        # skips the rest of this turn and starts the next one.
        if user_message == "":
            slow_print("ChatBot: Say something, or type 'bye' to leave.")
            continue

        # 2. Try math FIRST. If the message is a calculation, answer it.
        reply = try_calculate(user_message)
        if reply is not None:
            intent = "calc"  # label this turn for the history log
        else:
            intent = get_intent(user_message)

            # 3. CONTEXT in action: if the user said "another"/"again", swap
            #    in whatever they asked for last time.
            if intent == "repeat":
                if last_intent in (None, "repeat"):
                    intent = None  # nothing to repeat yet -> fallback reply
                else:
                    intent = last_intent

            reply = get_response(intent, user_name, user_message, history)

        # 4. "Type out" the reply.
        slow_print(f"ChatBot: {reply}")

        # 5. Record this exchange: keep it in memory (for AI context) AND
        #    insert it as a new row in the database.
        history.append({"you": user_message, "bot": reply})
        storage.add_message(user_message, reply)

        # 6. Remember this turn's intent for next time (so "another" works).
        if intent is not None:
            last_intent = intent

        # 7. A clean exit: if the user said goodbye, leave the loop.
        if intent == "goodbye":
            slow_print("ChatBot: Chat saved. See you next time!")
            break


# This line means: only run main() if we execute THIS file directly
# (not if it's imported by another file). It's a common Python pattern.
if __name__ == "__main__":
    main()
