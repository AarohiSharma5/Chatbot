"""
A simple rule-based chatbot.

"Rule-based" means the bot doesn't actually "think" or "learn".
Instead, it follows rules YOU write: "if the user says X, reply with Y".
This is how the very first chatbots worked, and it's the best way to
understand the core ideas before moving on to AI/machine-learning bots.
"""

import json
import os
import random
import string


# ---------------------------------------------------------------------------
# STEP 1: The "knowledge" of the bot.
#
# This dictionary maps an "intent" (what the user wants) to a list of replies.
# We keep several replies per intent and pick one at random so the bot feels
# a little less robotic.
# ---------------------------------------------------------------------------
RESPONSES = {
    "greeting": [
        "Hello! How can I help you today?",
        "Hi there! What's on your mind?",
        "Hey! Nice to see you.",
    ],
    "goodbye": [
        "Goodbye! Have a great day.",
        "See you later!",
        "Bye! Come back anytime.",
    ],
    "thanks": [
        "You're welcome!",
        "Anytime!",
        "Happy to help.",
    ],
    "how_are_you": [
        "I'm just a program, but I'm doing great! How about you?",
        "Running smoothly, thanks for asking!",
    ],
    "name": [
        "I'm ChatBot, your friendly assistant.",
        "You can call me ChatBot.",
    ],
}

# A fallback list used when we don't understand the user.
FALLBACK = [
    "Sorry, I didn't quite understand that.",
    "Hmm, I'm not sure how to respond to that yet.",
    "Could you rephrase that for me?",
]


# ---------------------------------------------------------------------------
# STEP 2: Understanding the user ("intent recognition").
#
# We look for KEYWORDS in the user's message to guess their intent.
# This is a very simple version of what real chatbots call NLU
# (Natural Language Understanding).
# ---------------------------------------------------------------------------
KEYWORDS = {
    "greeting": ["hello", "hi", "hey", "good morning", "good evening"],
    "goodbye": ["bye", "goodbye", "see you", "exit", "quit"],
    "thanks": ["thanks", "thank you", "thx"],
    "how_are_you": ["how are you", "how's it going", "how are u"],
    "name": ["your name", "who are you", "what are you"],
    "ask_my_name": ["my name", "remember my name", "who am i"],
}


def get_intent(message):
    """Return the intent that best matches the user's message, or None."""
    # Lower-casing makes matching case-insensitive ("Hi" == "hi").
    text = message.lower()

    # TOKENIZATION: split the sentence into a list of individual words.
    # "hi there!" -> ["hi", "there!"]
    words = text.split()

    # Clean punctuation off each word so "hello!" becomes "hello".
    # str.strip(chars) removes the given characters from BOTH ends of a word.
    words = [word.strip(string.punctuation) for word in words]

    for intent, keywords in KEYWORDS.items():
        for keyword in keywords:
            if " " in keyword:
                # The keyword is a PHRASE (e.g. "how are you").
                # We look for it inside the full text.
                if keyword in text:
                    return intent
            else:
                # The keyword is a SINGLE WORD (e.g. "hi").
                # It must match a WHOLE word in the message, not just a
                # piece of one. This is what stops "this" matching "hi".
                if keyword in words:
                    return intent
    return None


# ---------------------------------------------------------------------------
# STEP 3: Producing a response.
# ---------------------------------------------------------------------------
def get_response(message, user_name):
    """Decide what the bot should say back.

    We now pass in `user_name` (the bot's "memory") so replies can be
    personalised.
    """
    intent = get_intent(message)

    if intent is None:
        return random.choice(FALLBACK)

    # Special case: the user is asking us to recall their name.
    # We use the stored value instead of a fixed reply.
    if intent == "ask_my_name":
        return f"Your name is {user_name}, of course!"

    # Personalise greetings with the remembered name.
    if intent == "greeting":
        return f"{random.choice(RESPONSES['greeting'])} Nice to see you, {user_name}!"

    return random.choice(RESPONSES[intent])


# ---------------------------------------------------------------------------
# PERSISTENCE: saving memory to a file so it survives after the program ends.
#
# A normal variable disappears when the program closes. To REMEMBER things
# between runs, we write them to a file on disk and read them back next time.
# We use JSON, a simple text format for storing data like dictionaries.
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
# STEP 4: The conversation loop.
#
# A chatbot is really just a loop: read input -> respond -> repeat,
# until the user decides to leave.
# ---------------------------------------------------------------------------
def main():
    print("ChatBot: Hi! I'm a simple chatbot. Type 'bye' to leave.")

    # Load whatever we saved during previous runs.
    memory = load_memory()

    # memory.get("user_name") returns the saved name, or None if we've
    # never met this user before.
    user_name = memory.get("user_name")

    if user_name:
        # We've met before: the file remembered the name across restarts!
        print(f"ChatBot: Welcome back, {user_name}!\n")
    else:
        # First time: ask for the name and SAVE it for next time.
        user_name = input("ChatBot: What's your name?\nYou: ").strip()
        memory["user_name"] = user_name
        save_memory(memory)
        print(f"ChatBot: Nice to meet you, {user_name}! I'll remember you.\n")

    while True:
        # 1. Read what the user typed.
        user_message = input("You: ")

        # 2. Figure out a reply (passing in our memory of the name).
        reply = get_response(user_message, user_name)

        # 3. Print the reply.
        print("ChatBot:", reply)

        # 4. Stop the loop if the user said goodbye.
        if get_intent(user_message) == "goodbye":
            break


# This line means: only run main() if we execute THIS file directly
# (not if it's imported by another file). It's a common Python pattern.
if __name__ == "__main__":
    main()
