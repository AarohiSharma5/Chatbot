"""
A simple rule-based chatbot.

"Rule-based" means the bot doesn't actually "think" or "learn".
Instead, it follows rules YOU write: "if the user says X, reply with Y".
This is how the very first chatbots worked, and it's the best way to
understand the core ideas before moving on to AI/machine-learning bots.
"""

import random


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
}


def get_intent(message):
    """Return the intent that best matches the user's message, or None."""
    # Lower-casing makes matching case-insensitive ("Hi" == "hi").
    text = message.lower()

    for intent, words in KEYWORDS.items():
        for word in words:
            if word in text:
                return intent
    return None


# ---------------------------------------------------------------------------
# STEP 3: Producing a response.
# ---------------------------------------------------------------------------
def get_response(message):
    """Decide what the bot should say back."""
    intent = get_intent(message)

    if intent is None:
        return random.choice(FALLBACK)

    return random.choice(RESPONSES[intent])


# ---------------------------------------------------------------------------
# STEP 4: The conversation loop.
#
# A chatbot is really just a loop: read input -> respond -> repeat,
# until the user decides to leave.
# ---------------------------------------------------------------------------
def main():
    print("ChatBot: Hi! I'm a simple chatbot. Type 'bye' to leave.\n")

    while True:
        # 1. Read what the user typed.
        user_message = input("You: ")

        # 2. Figure out a reply.
        reply = get_response(user_message)

        # 3. Print the reply.
        print("ChatBot:", reply)

        # 4. Stop the loop if the user said goodbye.
        if get_intent(user_message) == "goodbye":
            break


# This line means: only run main() if we execute THIS file directly
# (not if it's imported by another file). It's a common Python pattern.
if __name__ == "__main__":
    main()
