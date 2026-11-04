import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import anthropic

MODEL = "claude-sonnet-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
PRICE_PER_MTOK = (2.00, 10.00)  # Sonnet 5.5 input, output (USD)
CONTEXT_WORDS = 25

OVERALL_LABEL = {"rewrite_needed": "Rewrite needed", "small_fixes": "Small fixes", "no_action": "No action"}
VERDICT_LABEL = {"copied": "Copied", "template_or_stock": "Template or stock wording", "coincidence": "Coincidence"}
OVERALL_ORDER = {"rewrite_needed": 0, "small_fixes": 1, "no_action": 2}

REVIEW_SYSTEM = """You review CVs written by students at a UK college (London Academy for Applied Technology) for copied wording.

A separate tool has already found passages in one student's CV that also appear word for word in other applicants' CVs. Headings, contact details, dates, stock CV phrases and shared template text were removed before matching, so every passage you see survived that filtering.

For each matched passage, decide its verdict:
- copied: personal content (the student's own motivation, experience, projects, achievements, interests) that another applicant has word for word.
- template_or_stock: wording many CVs would legitimately share, such as a course or qualification title, a job title, a standard description of a college programme or placement, or a generic phrase.
- coincidence: a short, ordinary overlap that means nothing.

Then write feedback for the student, one entry per CV section that has copied passages:
- problem: one sentence telling the student what is wrong, addressed as "you".
- what_to_change: concrete direction on what to write instead. Where the student's own CV mentions relevant experience elsewhere, point them to it.
- questions: one to three questions that help the student find their own content.

Rules:
- Never write replacement sentences or a rewritten version of any part of the CV. The student must write their own words.
- Never mention, describe or guess at the other applicant.
- UK English, plain words, short sentences.
- overall: rewrite_needed when copied personal content is a meaningful part of the CV; small_fixes when it is minor; no_action when every passage is template_or_stock or coincidence (then sections is empty).
- staff_note: one or two sentences for staff, for example when a passage is shared by several CVs."""

REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["overall", "staff_note", "matches", "sections"],
    "properties": {
        "overall": {"type": "string", "enum": list(OVERALL_LABEL)},
        "staff_note": {"type": "string"},
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "verdict", "reason"],
                "properties": {
                    "id": {"type": "integer"},
                    "verdict": {"type": "string", "enum": list(VERDICT_LABEL)},
                    "reason": {"type": "string"},
                },
            },
        },
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["section", "problem", "what_to_change", "questions"],
                "properties": {
                    "section": {"type": "string"},
                    "problem": {"type": "string"},
                    "what_to_change": {"type": "string"},
                    "questions": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}

SUMMARY_SYSTEM = """You summarise the results of a CV originality check for college admissions staff.
You get only counts and statuses, never CV text. Write for a busy staff meeting: UK English, plain words.
summary: at most 5 short sentences on how the batch looks overall and what needs doing.
priorities: up to 5 short action items, most important first, referring to CVs by their Doc ID."""

SUMMARY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "priorities"],
    "properties": {
        "summary": {"type": "string"},
        "priorities": {"type": "array", "items": {"type": "string"}},
    },
}


class AIError(Exception):
    pass


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def cost(self) -> float:
        return (self.input_tokens * PRICE_PER_MTOK[0] + self.output_tokens * PRICE_PER_MTOK[1]) / 1_000_000

    def __add__(self, other):
        return Usage(self.input_tokens + other.input_tokens, self.output_tokens + other.output_tokens)


@dataclass
class Review:
    overall: str
    staff_note: str
    verdicts: dict[int, tuple[str, str]]
    sections: list[dict]
    items: list[dict]
    usage: Usage = field(default_factory=Usage)


def make_client(api_key: str):
    return anthropic.Anthropic(api_key=api_key, max_retries=3)


def ask(client, system, payload, schema, effort, max_tokens=16000):
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=1)}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as e:
        raise AIError("Claude rejected the API key. Check [anthropic] api_key in secrets.toml.") from e
    except anthropic.RateLimitError as e:
        raise AIError("Claude is rate limiting requests. Wait a minute and try again.") from e
    except anthropic.APIStatusError as e:
        raise AIError(f"Claude returned an error ({e.status_code}). Try again shortly.") from e
    except anthropic.APIConnectionError as e:
        raise AIError("Couldn't reach Claude. Check the server's internet connection.") from e

    if response.stop_reason == "refusal":
        raise AIError("Claude declined this request. Please handle this one manually.")
    if response.stop_reason == "max_tokens":
        raise AIError("Claude's answer was cut off. Try again.")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise AIError("Claude's answer couldn't be read. Try again.") from e
    return data, Usage(response.usage.input_tokens or 0, response.usage.output_tokens or 0)


def review_items(summary, analysis):
    """The matched passages for one CV, deduplicated, with surrounding words for context."""
    doc = analysis.docs[summary.index]
    seen = {}
    for m in summary.matches:
        key = (m.start, m.words)
        if key in seen:
            seen[key]["also_in_other_cvs"] += 1
            continue
        before_start = max(0, m.start - CONTEXT_WORDS)
        after_start = m.start + m.words
        after_len = min(CONTEXT_WORDS, len(doc.tokens) - after_start)
        seen[key] = {
            "id": len(seen) + 1,
            "section": m.section,
            "words": m.words,
            "passage": m.text,
            "words_before": doc.excerpt(before_start, m.start - before_start) if m.start > before_start else "",
            "words_after": doc.excerpt(after_start, after_len) if after_len > 0 else "",
            "other_cv_version": m.other_text,
            "also_in_other_cvs": 1,
        }
    return list(seen.values())


def review_cv(client, summary, analysis) -> Review:
    items = review_items(summary, analysis)
    payload = {
        "original_share_of_cv": round(summary.original, 2),
        "copied_words_by_section": dict(summary.sections),
        "matched_passages": items,
    }
    data, usage = ask(client, REVIEW_SYSTEM, payload, REVIEW_SCHEMA, effort="low")
    verdicts = {m["id"]: (m["verdict"], m["reason"]) for m in data["matches"]}
    return Review(data["overall"], data["staff_note"], verdicts, data["sections"], items, usage)


def review_many(client, summaries, analysis, workers=6, on_done=None):
    """Reviews several CVs in parallel. Returns {cv index: Review or AIError}."""
    results = {}

    def one(s):
        try:
            return s.index, review_cv(client, s, analysis)
        except AIError as e:
            return s.index, e

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for index, result in pool.map(one, summaries):
            results[index] = result
            if on_done:
                on_done(len(results), len(summaries))
    return results


def summarise_check(client, ids, summaries, groups, reviews):
    payload = {
        "cvs_checked": len(summaries),
        "cvs": [{
            "doc_id": ids[s.index],
            "status": s.status,
            "original_share": round(s.original, 2),
            "copied_words_by_section": dict(s.sections),
            "claude_overall": OVERALL_LABEL[reviews[s.index].overall] if isinstance(reviews.get(s.index), Review) else None,
        } for s in summaries if s.status != "Original"],
        "copying_groups": [{"doc_ids": [ids[i] for i in g.docs], "section": g.section} for g in groups],
    }
    data, usage = ask(client, SUMMARY_SYSTEM, payload, SUMMARY_SCHEMA, effort="low", max_tokens=4000)
    return data, usage
