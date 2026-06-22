"""
LONG-TERM MEMORY using embeddings + retrieval (a mini "RAG" system).

The idea (Retrieval-Augmented Generation):
  1. remember(): turn a piece of text into an embedding (a vector capturing
     its MEANING) and store it.
  2. recall(): turn the new question into an embedding too, then find the
     stored memories whose vectors are most SIMILAR in meaning, and return
     them so they can be fed to the AI.

This is the same idea as your typo-tolerance (difflib compared spelling),
but here we compare MEANING. "What do I study?" can match a stored
"I'm learning Python" even though they share almost no words.

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


def remember(text):
    """Store `text` as a long-term memory (if embeddings are available)."""
    vector = ai_brain.embed(text)
    if vector is None:
        return False  # embedding model not installed -> skip silently
    storage.add_memory(text, vector)
    return True


def recall(query, k=TOP_K):
    """Return up to `k` stored memories most similar in meaning to `query`."""
    query_vector = ai_brain.embed(query)
    if query_vector is None:
        return []  # no embeddings available -> no long-term recall

    scored = []
    for text, vector in storage.get_all_memories():
        similarity = cosine_similarity(query_vector, vector)
        if similarity >= MIN_SIMILARITY:
            scored.append((similarity, text))

    # Sort by similarity, highest first, and keep the top k texts.
    scored.sort(reverse=True)
    return [text for (similarity, text) in scored[:k]]
