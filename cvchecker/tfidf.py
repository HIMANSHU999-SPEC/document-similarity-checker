import re
from collections import Counter
from math import log
from pathlib import Path

import numpy as np

TOKEN = re.compile(r"(?u)\b\w\w+\b")
STOP_WORDS = frozenset(
    line.strip() for line in Path(__file__).with_name("stop_words.txt").read_text().splitlines()
    if line.strip() and not line.startswith("#")
)


def cosine_matrix(texts) -> np.ndarray:
    """Cosine similarity of TF-IDF vectors, matching scikit-learn's TfidfVectorizer(stop_words="english")
    followed by cosine_similarity, without loading scikit-learn. Raises ValueError on an empty vocabulary."""
    counts = [Counter(t for t in TOKEN.findall(text.lower()) if t not in STOP_WORDS) for text in texts]
    df = Counter(term for c in counts for term in c)
    if not df:
        raise ValueError("empty vocabulary")
    n = len(texts)
    idf = {term: log((1 + n) / (1 + d)) + 1 for term, d in df.items()}
    norms = np.array([sum((tf * idf[t]) ** 2 for t, tf in c.items()) ** 0.5 for c in counts])
    shared = {term: i for i, term in enumerate(t for t, d in df.items() if d > 1)}
    weights = np.zeros((n, len(shared)), dtype=np.float32)  # only words two or more CVs use affect any pair
    for row, c in enumerate(counts):
        if norms[row]:
            for t, tf in c.items():
                col = shared.get(t)
                if col is not None:
                    weights[row, col] = tf * idf[t] / norms[row]
    matrix = weights @ weights.T
    np.fill_diagonal(matrix, (norms > 0).astype(np.float32))
    return matrix
