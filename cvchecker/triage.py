import itertools
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from cvchecker.names import file_person
from cvchecker.similarity import matching_passages

RED, AMBER, GREEN = "Needs review", "Check", "Original"
SAME_CV_SHARE = 0.6  # two files named for the same student, at least this alike, are one CV uploaded twice
STATUS_ORDER = {RED: 0, AMBER: 1, GREEN: 2}


@dataclass
class Match:
    other: int
    section: str
    other_section: str
    text: str
    words: int
    start: int = 0
    other_text: str = ""


@dataclass
class CvSummary:
    index: int
    status: str
    original: float
    main_source: int | None
    main_source_share: float
    sections: Counter
    matches: list[Match] = field(default_factory=list)


def summarise(analysis, thresholds) -> list[CvSummary]:
    n = len(analysis.docs)
    covered = [set() for _ in range(n)]
    flagged = [False] * n
    best = [(None, 0.0)] * n
    matches = [[] for _ in range(n)]

    for p in analysis.flagged_pairs(thresholds):
        flagged[p.a] = flagged[p.b] = True
    for p in analysis.pairs:
        if p.copied_a_in_b > best[p.a][1]:
            best[p.a] = (p.b, p.copied_a_in_b)
        if p.copied_b_in_a > best[p.b][1]:
            best[p.b] = (p.a, p.copied_b_in_a)
        for s in p.passages:
            covered[p.a].update(range(s.a_start, s.a_start + s.length))
            covered[p.b].update(range(s.b_start, s.b_start + s.length))
            matches[p.a].append(Match(p.b, s.section_a, s.section_b, s.text_a, s.length, s.a_start, s.text_b))
            matches[p.b].append(Match(p.a, s.section_b, s.section_a, s.text_b, s.length, s.b_start, s.text_a))

    out = []
    for i, doc in enumerate(analysis.docs):
        keep = analysis.keeps[i]
        countable = sum(keep) or 1
        copied_positions = [j for j in covered[i] if keep[j]]
        status = RED if flagged[i] else AMBER if copied_positions else GREEN
        out.append(CvSummary(
            index=i,
            status=status,
            original=1 - len(copied_positions) / countable,
            main_source=best[i][0],
            main_source_share=best[i][1],
            sections=Counter(doc.sections[j] for j in copied_positions),
            matches=sorted(matches[i], key=lambda m: (m.section, -m.words)),
        ))
    return sorted(out, key=lambda s: (STATUS_ORDER[s.status], s.original))


@dataclass
class Group:
    docs: list[int]
    section: str
    text: str


def copying_groups(analysis, thresholds, min_size=3) -> list[Group]:
    """Three or more CVs sharing the same copied passage, e.g. one personal statement passed around."""
    k = analysis.k
    items = []
    for p in analysis.pairs:
        if p.flagged(thresholds):
            for s in p.passages:
                words = s.text.split()
                items.append(({p.a, p.b}, {tuple(words[i:i + k]) for i in range(len(words) - k + 1)}, s))

    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner = {}
    for i, (_, shingle_set, _) in enumerate(items):
        for sh in shingle_set:
            if sh in owner:
                parent[find(i)] = find(owner[sh])
            else:
                owner[sh] = i
    merged = defaultdict(lambda: (set(), []))
    for i, (docs, _, passage) in enumerate(items):
        docs_so_far, passages = merged[find(i)]
        docs_so_far.update(docs)
        passages.append(passage)
    groups = []
    for docs, passages in merged.values():
        if len(docs) >= min_size:
            longest = max(passages, key=lambda s: s.length)
            groups.append(Group(sorted(docs), longest.section_a, longest.text_a))
    return sorted(groups, key=lambda g: len(g.docs), reverse=True)


def _direct_share(ta, tb, k) -> float:
    """How much of either CV the other contains word for word, without batch-wide filtering."""
    passages = matching_passages(ta, tb, k)
    if not passages or not ta or not tb:
        return 0.0
    covered = sum(p.length for p in passages)
    return max(covered / len(ta), covered / len(tb))


def same_student_twice(names, texts, analysis):
    """Files that look like one student's CV uploaded more than once: the same person's name in the file names
    and mostly the same wording. Returns (kept index, dropped index, share); the fullest version is kept.

    Versions are compared directly, not through the batch analysis: there, wording shared by several versions
    (or copied by another student too) can count as batch-wide boilerplate and hide the match."""
    by_person = defaultdict(list)
    for i, name in enumerate(names):
        person = tuple(file_person(name))
        if len(person) >= 2:
            by_person[person].append(i)
    found = []
    for members in by_person.values():
        if len(members) < 2:
            continue
        parent = {i: i for i in members}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        shares = {}
        for a, b in itertools.combinations(members, 2):
            share = _direct_share(analysis.docs[a].tokens, analysis.docs[b].tokens, analysis.k)
            shares[(a, b)] = shares[(b, a)] = share
            if share >= SAME_CV_SHARE:
                parent[find(a)] = find(b)
        clusters = defaultdict(list)
        for i in members:
            clusters[find(i)].append(i)
        for cluster in clusters.values():
            if len(cluster) < 2:
                continue
            keep = max(cluster, key=lambda i: (len(texts[i]), -i))
            found += [(keep, d, shares[(keep, d)]) for d in sorted(cluster) if d != keep]
    return found
