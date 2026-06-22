"""
A simple rule-based chatbot.

"Rule-based" means the bot doesn't actually "think" or "learn".
Instead, it follows rules YOU write: "if the user says X, reply with Y".
This is how the very first chatbots worked, and it's the best way to
understand the core ideas before moving on to AI/machine-learning bots.
"""

import datetime
import json
import os
import random
import re
import string
import time


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
# PERSISTENCE: saving memory to a file so it survives after the program ends.
#
# A normal variable disappears when the program closes. To REMEMBER things
# between runs, we write them to a file on disk and read them back next time.
# ---------------------------------------------------------------------------
MEMORY_FILE = "memory.json"


def load_memory():
    """Read saved memory from the file. Returns a dictionary."""
    # If the file doesn't exist yet (e.g. the very first run), start empty.
    if not os.path.exists(MEMORY_FILE):
        return {}

    # "with open(...)" safely opens the file and closes it automatically.
    # "r" means we're opening it to READ.
    with open(MEMORY_FILE, "r") as file:
        return json.load(file)  # turn the file's JSON text back into a dict


def save_memory(memory):
    """Write the memory dictionary to the file as JSON."""
    # "w" means we're opening it to WRITE (this overwrites the old contents).
    with open(MEMORY_FILE, "w") as file:
        json.dump(memory, file)  # turn the dict into JSON text and store it


# ---------------------------------------------------------------------------
# STEP 2: Understanding the user ("intent recognition") with SCORING.
#
# Instead of returning the FIRST intent that matches, we now count how many
# keywords match for each intent and pick the BEST one (highest score). This
# handles messages that contain several clues, e.g. "hi, what's the time?".
# ---------------------------------------------------------------------------
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
                # A SINGLE WORD (e.g. "hi"): must match a WHOLE word.
                if keyword in words:
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
def get_response(intent, user_name):
    """Decide what the bot should say back, based on the detected intent.

    `user_name` (the bot's "memory") lets us personalise some replies.
    """
    if intent is None:
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

    # Load whatever we saved during previous runs.
    memory = load_memory()
    user_name = memory.get("user_name")

    # Load the saved chat history (a list of past exchanges). The second
    # argument to .get() is the DEFAULT used when there's no history yet.
    history = memory.get("history", [])

    if user_name:
        print(f"ChatBot: Welcome back, {user_name}!")
        print(f"ChatBot: We've exchanged {len(history)} messages before.\n")
    else:
        user_name = input("ChatBot: What's your name?\nYou: ").strip()
        memory["user_name"] = user_name
        save_memory(memory)
        print(f"ChatBot: Nice to meet you, {user_name}! I'll remember you.\n")

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
            # Otherwise, detect the intent and pick a normal reply.
            intent = get_intent(user_message)
            reply = get_response(intent, user_name)

        # 3. "Type out" the reply.
        slow_print(f"ChatBot: {reply}")

        # 4. Record this exchange and save it to disk.
        history.append({"you": user_message, "bot": reply})
        memory["history"] = history
        save_memory(memory)

        # 5. A clean exit: if the user said goodbye, leave the loop.
        if intent == "goodbye":
            slow_print("ChatBot: Chat saved. See you next time!")
            break


# This line means: only run main() if we execute THIS file directly
# (not if it's imported by another file). It's a common Python pattern.
if __name__ == "__main__":
    main()
