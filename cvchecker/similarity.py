import itertools
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

WORD = re.compile(r"[a-z0-9]+(?:['’][a-z]+)?")


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return WORD.findall(text)


def shingles(tokens: list[str], k: int) -> dict[tuple, list[int]]:
    index = defaultdict(list)
    for i in range(len(tokens) - k + 1):
        index[tuple(tokens[i:i + k])].append(i)
    return index


@dataclass
class Passage:
    a_start: int
    b_start: int
    length: int
    text: str


@dataclass
class PairResult:
    a: int
    b: int
    similarity: float
    copied_a_in_b: float
    copied_b_in_a: float
    passages: list[Passage] = field(default_factory=list)

    @property
    def copied(self) -> float:
        return max(self.copied_a_in_b, self.copied_b_in_a)

    @property
    def score(self) -> float:
        return max(self.similarity, self.copied)

    def flagged(self, thresholds) -> bool:
        similarity_threshold, copied_threshold = thresholds
        return self.similarity >= similarity_threshold or self.copied >= copied_threshold


def boilerplate_shingles(token_lists, k, template_token_lists=(), share=0.5, min_docs=3):
    """Shingles shared by most of the batch, or present in a template, are not evidence of copying."""
    common = set()
    for t in template_token_lists:
        common.update(shingles(t, k))
    n = len(token_lists)
    if n >= min_docs:
        counts = Counter(s for t in token_lists for s in set(shingles(t, k)))
        cutoff = max(min_docs, share * n)
        common.update(s for s, c in counts.items() if c >= cutoff)
    return common


def _mask(tokens, k, banned):
    keep = [True] * len(tokens)
    for i in range(len(tokens) - k + 1):
        if tuple(tokens[i:i + k]) in banned:
            for j in range(i, i + k):
                keep[j] = False
    return keep


def matching_passages(ta, tb, k, banned=frozenset()) -> list[Passage]:
    """All shared runs of at least k words, wherever they appear in either document."""
    index_b = shingles(tb, k)
    runs = {}
    for i in range(len(ta) - k + 1):
        sh = tuple(ta[i:i + k])
        if sh in banned:
            continue
        for j in index_b.get(sh, ()):
            if (i - 1, j - 1) in runs:
                start = runs.pop((i - 1, j - 1))
                runs[(i, j)] = start
            else:
                runs[(i, j)] = (i, j)
    found = []
    for (end_i, _), (si, sj) in runs.items():
        found.append((si, sj, end_i - si + k))
    found.sort(key=lambda r: -r[2])
    taken_a, taken_b, passages = set(), set(), []
    for si, sj, length in found:
        # Adjacent passages can share a word at their edges; trim it rather than drop the passage.
        while length and (si in taken_a or sj in taken_b):
            si, sj, length = si + 1, sj + 1, length - 1
        while length and (si + length - 1 in taken_a or sj + length - 1 in taken_b):
            length -= 1
        span_a, span_b = range(si, si + length), range(sj, sj + length)
        if length < k or taken_a.intersection(span_a) or taken_b.intersection(span_b):
            continue
        taken_a.update(span_a)
        taken_b.update(span_b)
        passages.append(Passage(si, sj, length, " ".join(ta[si:si + length])))
    passages.sort(key=lambda p: p.a_start)
    return passages


def _copied_share(tokens, keep, passages, side):
    countable = sum(keep)
    if not countable:
        return 0.0
    covered = set()
    for p in passages:
        start = p.a_start if side == "a" else p.b_start
        covered.update(range(start, start + p.length))
    return sum(1 for i in covered if keep[i]) / countable


def analyse(texts, min_words=10, template_texts=()):
    tokens = [tokenize(t) for t in texts]
    k = max(3, min_words)
    banned = boilerplate_shingles(tokens, k, [tokenize(t) for t in template_texts])
    keeps = [_mask(t, k, banned) for t in tokens]
    cleaned = [" ".join(w for w, keep in zip(t, m) if keep) for t, m in zip(tokens, keeps)]

    if any(cleaned) and len(texts) >= 2:
        vectorizer = TfidfVectorizer(stop_words="english")
        try:
            matrix = cosine_similarity(vectorizer.fit_transform(cleaned))
        except ValueError:
            matrix = [[0.0] * len(texts) for _ in texts]
    else:
        matrix = [[0.0] * len(texts) for _ in texts]

    pairs = []
    for a, b in itertools.combinations(range(len(texts)), 2):
        passages = matching_passages(tokens[a], tokens[b], k, banned)
        pairs.append(PairResult(
            a, b,
            similarity=float(matrix[a][b]),
            copied_a_in_b=_copied_share(tokens[a], keeps[a], passages, "a"),
            copied_b_in_a=_copied_share(tokens[b], keeps[b], passages, "b"),
            passages=passages,
        ))
    return matrix, pairs, len(banned)
