from collections import Counter, defaultdict
from dataclasses import dataclass, field

RED, AMBER, GREEN = "Needs review", "Check", "Original"
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

    for p in analysis.pairs:
        if p.flagged(thresholds):
            flagged[p.a] = flagged[p.b] = True
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
