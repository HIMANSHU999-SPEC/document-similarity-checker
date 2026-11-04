from dataclasses import dataclass

from cvchecker.ai import Review
from cvchecker.triage import AMBER, GREEN, RED

CLAUDE_STATUS = {
    "rewrite_needed": ("🔴", "Rewrite needed", 0),
    "small_fixes": ("🟠", "Small fixes", 1),
    "no_action": ("✅", "OK", 2),
}
MATCHING_STATUS = {RED: ("🔴", "Needs review", 0), AMBER: ("🟠", "Check", 1), GREEN: ("✅", "OK", 2)}
NOTHING = "Nothing to change."


@dataclass
class FixRow:
    index: int
    doc_id: str
    cv: str
    icon: str
    status: str
    what: str
    rank: int
    original: float
    from_claude: bool


def _join(names):
    names = list(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def fallback_text(summary) -> str:
    if summary.status == GREEN or not summary.sections:
        return NOTHING
    sections = [s for s, _ in summary.sections.most_common()]
    verb = "matches" if len(sections) == 1 else "match"
    return f"{_join(sections)} {verb} another CV: rewrite {'this section' if len(sections) == 1 else 'these sections'} in your own words."


def fix_rows(names, ids, summaries, reviews) -> list[FixRow]:
    rows = []
    for s in summaries:
        review = reviews.get(s.index)
        if isinstance(review, Review):
            icon, status, rank = CLAUDE_STATUS[review.overall]
            what = NOTHING if review.overall == "no_action" else (review.one_line or fallback_text(s))
            from_claude = True
        else:
            icon, status, rank = MATCHING_STATUS[s.status]
            what, from_claude = fallback_text(s), False
        rows.append(FixRow(s.index, ids[s.index], names[s.index].rsplit(".", 1)[0], icon, status, what,
                           rank, s.original, from_claude))
    return sorted(rows, key=lambda r: (r.rank, r.original))


def counts(rows):
    out = {}
    for r in rows:
        out[r.status] = out.get(r.status, 0) + 1
    return out
