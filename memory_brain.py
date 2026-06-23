"""
LONG-TERM MEMORY using embeddings + retrieval (a mini "RAG" system).

The idea (Retrieval-Augmented Generation):
  1. remember(): pull the durable FACTS out of a message, turn each into an
     embedding (a vector capturing its MEANING), and store it.
  2. recall(): turn the new question into an embedding too, then find the
     stored facts whose vectors are most SIMILAR in meaning, and return
     them so they can be fed to the AI.

Why extract facts instead of storing raw messages? Most of what people type
is noise for long-term memory ("ok", "what time is it", "lol"). Saving it
all clutters recall. So we use the LLM as a TOOL: it reads the message and
writes back only the lasting facts ("User is learning Python", "User prefers
short answers"). This is a common pattern -- using a model not to chat, but
to transform text into clean, structured data.

This is the same idea as your typo-tolerance (difflib compared spelling),
but here we compare MEANING. "What do I study?" can match a stored
"User is learning Python" even though they share almost no words.

We use Ollama to make the embeddings and SQLite to store them, so there
are no extra installs -- and we write the similarity search ourselves.
"""

import math

import ai_brain
import storage

# How many memories to retrieve, and how similar they must be (0..1) to
# count. Cosine similarity of 1.0 is identical meaning; below ~0.5 is
# usually unrelated, so we ignore weak matches as noise.
TOP_K = 3
MIN_SIMILARITY = 0.5

# Instructions for the "fact extractor". We ask the model to behave like a
# note-taker: read the message and write down only what's worth remembering.
FACT_SYSTEM_PROMPT = (
    "You extract durable facts about the user from their message. A durable "
    "fact is worth remembering long-term: their name, preferences, goals, "
    "what they are learning, their job, hobbies, likes and dislikes, or "
    "important personal details. Ignore small talk, questions, greetings, "
    "and one-off remarks. Write each fact on its own line, in the third "
    "person, starting with 'User '. Keep each fact short. If there is "
    "nothing worth remembering, reply with exactly: NONE"
)


def cosine_similarity(vec_a, vec_b):
    """Measure how similar two vectors are, from -1 to 1 (1 = same meaning).

    It's the "angle" between the two vectors: we take their dot product and
    divide by their lengths. Don't worry about the math -- the takeaway is
    that closer meanings give a number nearer to 1.
    """
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    length_a = math.sqrt(sum(a * a for a in vec_a))
    length_b = math.sqrt(sum(b * b for b in vec_b))
    if length_a == 0 or length_b == 0:
        return 0.0
    return dot / (length_a * length_b)


def extract_facts(text):
    """Use the LLM to pull durable facts out of `text`.

    Returns a list of short fact strings (possibly empty). The model decides
    what's worth keeping; if there's nothing, it answers "NONE" and we return
    an empty list. If the AI is unavailable, we also return an empty list.
    """
    reply = ai_brain.chat_once(
        [
            {"role": "system", "content": FACT_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ]
    )
    if not reply:
        return []

    facts = []
    for line in reply.splitlines():
        # Strip bullet characters/numbering the model might add.
        line = line.strip().lstrip("-*0123456789. ").strip()
        if not line or line.upper().strip(".") == "NONE":
            continue
        facts.append(line)
    return facts


def remember(user_id, text):
    """Extract durable facts from `text` and store each as a long-term memory
    FOR THIS USER. Returns True if at least one new fact was saved.

    Skips silently when the AI or embedding model is unavailable, or when
    there's nothing worth remembering -- so it never breaks the chatbot.
    """
    facts = extract_facts(text)
    if not facts:
        return False

    stored = 0
    for fact in facts:
        if storage.memory_exists(user_id, fact):
            continue  # this user already knows this -> don't duplicate
        vector = ai_brain.embed(fact)
        if vector is None:
            return stored > 0  # embedding model not installed -> stop
        storage.add_memory(user_id, fact, vector)
        stored += 1
    return stored > 0


def recall(user_id, query, k=TOP_K):
    """Return up to `k` of THIS user's memories most similar to `query`."""
    query_vector = ai_brain.embed(query)
    if query_vector is None:
        return []  # no embeddings available -> no long-term recall

    scored = []
    for text, vector in storage.get_all_memories(user_id):
        similarity = cosine_similarity(query_vector, vector)
        if similarity >= MIN_SIMILARITY:
            scored.append((similarity, text))

    # Sort by similarity, highest first, and keep the top k texts.
    scored.sort(reverse=True)
    return [text for (similarity, text) in scored[:k]]
