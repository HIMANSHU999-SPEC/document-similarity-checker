import io
import json
import os
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import docx
import pandas as pd

from cvchecker.ai import AIError, Review, Usage, ask
from cvchecker.prepare import _heading, prepare
from cvchecker.similarity import analyse
from cvchecker.triage import RED, summarise

FIX_SYSTEM = """You help a UK college admissions team. One applicant's CV is below. Passages marked [[n]] ... [[/n]] use wording identical to another applicant's CV. Rewrite only each marked passage so it says the same true things about this applicant in fresh wording of their own.

Rules:
- Keep every fact in the passage: roles, organisations, places, dates, numbers, skills, qualifications. Never add a fact, achievement or detail that is not in this CV.
- Use different sentence structure and vocabulary from the original. Avoid reusing any run of four or more of its words, except names, job titles, qualification titles and numbers.
- The rewrite replaces exactly the marked text, so it must read naturally with the words just before and after the marker.
- Match the rest of the CV: same person (I or no pronoun), tense, and bullet or sentence style, and roughly the same length.
- Plain UK English. Avoid stock CV phrases such as "team player", "hard-working", "passionate about", "excellent communication skills".
- If a passage can't be rewritten faithfully without information the applicant didn't give, write the best faithful version and add a short question for the applicant to questions.
- Return one rewrite per marked id, as plain text without the markers."""

FIX_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["rewrites", "questions"],
    "properties": {
        "rewrites": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "text"],
            "properties": {"id": {"type": "integer"}, "text": {"type": "string"}},
        }},
        "questions": {"type": "array", "items": {"type": "string"}},
    },
}
MERGE_GAP = 3


@dataclass
class Fix:
    index: int
    original_text: str
    text: str = ""
    changes: list[tuple[str, str]] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    before: float = 0.0
    after: float | None = None
    still_matches: bool = False
    passes: int = 0
    error: str = ""
    usage: Usage = field(default_factory=Usage)
    tested: str = ""


def regions(summary, review=None):
    """Token ranges to rewrite: copied passages, merged where they touch. Template or coincidental wording is left."""
    keep_out = set()
    if isinstance(review, Review):
        for item in review.items:
            verdict = review.verdicts.get(item["id"], ("copied",))[0]
            if verdict != "copied":
                keep_out.add(item["passage"])
    spans = sorted((m.start, m.start + m.words) for m in summary.matches if m.text not in keep_out)
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1] + MERGE_GAP:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [tuple(r) for r in merged]


MIN_PIECE_WORDS = 4
_BULLET_LINE = re.compile(r"\n\s*[•\-*▪●◦]")


WRAPPED_LINE_CHARS = 60


def _breaks(text: str, prev_end: int, next_start: int) -> bool:
    """Must the line break between two words stay? Yes for a skipped heading, a blank line, a new bullet point,
    or after a short or finished line (a title, a date line, a bullet). Long lines that simply wrap are joined."""
    gap = text[prev_end:next_start]
    if "\n" not in gap:
        return False
    if re.search(r"[^\W_]", gap) or re.search(r"\n\s*\n", gap) or _BULLET_LINE.search(gap):
        return True
    line = text[text.rfind("\n", 0, prev_end) + 1:prev_end + gap.index("\n")].strip()
    return len(line) < WRAPPED_LINE_CHARS or line.endswith((".", "!", "?", ":"))


def char_spans(doc, token_regions):
    """Character spans to rewrite, split wherever the CV's structure must be kept. Tiny pieces are left."""
    spans = []
    for a, b in token_regions:
        start = a
        for t in range(a + 1, b + 1):
            if t == b or _breaks(doc.text, doc.spans[t - 1][1], doc.spans[t][0]):
                if t - start >= MIN_PIECE_WORDS:
                    spans.append((doc.spans[start][0], doc.spans[t - 1][1]))
                start = t
    return spans


def marked_text(masked: str, spans) -> str:
    out, last = [], 0
    for n, (a, b) in enumerate(spans, 1):
        out += [masked[last:a], f"[[{n}]]", masked[a:b], f"[[/{n}]]"]
        last = b
    out.append(masked[last:])
    return "".join(out)


def apply(text: str, spans, rewrites: dict[int, str]) -> tuple[str, list[tuple[str, str]]]:
    changes = []
    for n, (a, b) in reversed(list(enumerate(spans, 1))):
        new = rewrites.get(n)
        if new is None:
            continue
        new = " ".join(new.split())
        if text[b:b + 1] in tuple(".,;:!?"):
            new = new.rstrip(".,;:!?")
        changes.append((" ".join(text[a:b].split()), new))
        text = text[:a] + new + text[b:]
    return text, list(reversed(changes))


def rewrite_once(client, text: str, doc, token_regions):
    """One Claude pass over one CV. `doc` is the prepared (contact-masked) version of `text`."""
    spans = char_spans(doc, token_regions)
    payload = {"cv": marked_text(doc.text, spans), "passages_to_rewrite": len(spans)}
    data, usage = ask(client, FIX_SYSTEM, payload, FIX_SCHEMA, effort="medium")
    rewrites = {r["id"]: r["text"] for r in data["rewrites"] if r["text"].strip()}
    new_text, changes = apply(text, spans, rewrites)
    return new_text, changes, data["questions"], usage


def test_run(results, fixed: dict[int, str]):
    """Re-check the whole batch with fixed CVs swapped in, so fixed CVs are compared with each other too."""
    texts = [fixed.get(i, t) for i, t in enumerate(results["texts"])]
    settings = results["settings"]
    analysis = analyse(texts, settings["min_words"], settings["template_texts"], settings["phrases"])
    return analysis, {s.index: s for s in summarise(analysis, results["thresholds"])}


def fix_batch(client, results, indices, reviews, on_done=None, workers=6) -> dict[int, Fix]:
    by_index = {s.index: s for s in results["summaries"]}
    analysis = results["analysis"]
    fixes = {i: Fix(i, results["texts"][i], results["texts"][i], before=by_index[i].original) for i in indices}

    def first(i):
        fix = fixes[i]
        try:
            token_regions = regions(by_index[i], reviews.get(i))
            if token_regions:
                fix.text, fix.changes, fix.questions, fix.usage = rewrite_once(
                    client, fix.text, analysis.docs[i], token_regions)
                fix.passes = 1
        except AIError as e:
            fix.error = str(e)
        return i

    def second(i, summary):
        fix = fixes[i]
        try:
            text, changes, questions, usage = rewrite_once(client, fix.text, prepare(fix.text, results["settings"]["phrases"]),
                                                           regions(summary))
            fix.text, fix.changes = text, fix.changes + changes
            fix.questions += [q for q in questions if q not in fix.questions]
            fix.usage += usage
            fix.passes = 2
        except AIError as e:
            fix.error = str(e)
        return i

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for _ in pool.map(first, indices):
            done += 1
            if on_done:
                on_done(done, len(indices))

    _, after = test_run(results, {i: f.text for i, f in fixes.items()})
    retry = [i for i in indices if not fixes[i].error and after[i].status == RED and after[i].matches]
    if retry:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda i: second(i, after[i]), retry))
        _, after = test_run(results, {i: f.text for i, f in fixes.items()})
    record(fixes, after)
    return fixes


def record(fixes, after):
    for i, fix in fixes.items():
        fix.after = after[i].original
        fix.still_matches = after[i].status == RED
        fix.tested = fix.text


def text_to_docx(text: str) -> bytes:
    d = docx.Document()
    props = d.core_properties
    props.author = props.last_modified_by = props.comments = props.title = props.subject = props.keywords = ""
    first = True
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        found, rest = _heading(line)
        if first:
            d.add_paragraph(line, style="Title")
            first = False
        elif found and not rest.strip():
            d.add_paragraph(line.strip(":"), style="Heading 1")
        elif re.match(r"^[•\-*▪●◦]\s*", line):
            d.add_paragraph(re.sub(r"^[•\-*▪●◦]\s*", "", line), style="List Bullet")
        else:
            d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def fix_report(names, ids, fixes) -> bytes:
    rows = [{
        "Doc ID": ids[i], "CV": names[i], "Original wording before": round(f.before, 4),
        "Original wording after": round(f.after, 4) if f.after is not None else None,
        "Result": "Error: " + f.error if f.error else ("Still matches: fix by hand" if f.still_matches else "Unique"),
        "Passages rewritten": len(f.changes), "Questions for the applicant": "\n".join(f.questions),
    } for i, f in sorted(fixes.items())]
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    return buf.getvalue()


def fixed_zip(names, ids, fixes, original_report_pdf: bytes) -> bytes:
    buf = io.BytesIO()
    used = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, fix in sorted(fixes.items()):
            if fix.error or not fix.changes:
                continue
            stem = re.sub(r"[^\w\- ]+", "", names[i].rsplit(".", 1)[0]).strip() or "CV"
            if stem in used:
                stem = f"{stem} ({ids[i].replace('#', '')})"
            used.add(stem)
            z.writestr(f"CVs/{stem}.docx", text_to_docx(fix.text))
        z.writestr("Reports (staff only)/fix-report.xlsx", fix_report(names, ids, fixes))
        z.writestr("Reports (staff only)/original-check.pdf", original_report_pdf)
    return buf.getvalue()


def log_event(folder: Path, email: str, action: str, detail: str = ""):
    """Staff-only record of special actions, kept next to the learned phrases file."""
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = folder / "special_actions.log"
    line = json.dumps({"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "by": email,
                       "action": action, "detail": detail})
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def recent_failures(folder: Path, email: str, minutes: int = 60) -> int:
    path = folder / "special_actions.log"
    if not path.exists():
        return 0
    cutoff = datetime.now(timezone.utc).timestamp() - minutes * 60
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
            at = datetime.strptime(event["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        except (ValueError, KeyError):
            continue
        if event.get("by") == email and event.get("action") == "wrong code" and at >= cutoff:
            count += 1
    return count
