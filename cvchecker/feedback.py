import io
import re
import zipfile
from datetime import date

import docx
from docx.shared import Pt

from cvchecker.triage import GREEN, RED

ADVICE = {
    "Profile": "Describe yourself in your own words: what you're interested in and what you've actually done.",
    "Experience": "Describe what you did in this role yourself, with a specific example or result.",
    "Skills": "Show each skill with an example of when you used it.",
    "Education": "List your own course, modules and results in your own words.",
    "Achievements": "Explain your own achievement and why it mattered.",
    "Interests": "Write about your own interests and what you get from them.",
}
DEFAULT_ADVICE = "Rewrite this in your own words, using your own examples."


def _claude_feedback(d, summary, review):
    if review.overall == "no_action":
        d.add_paragraph("The wording that matched other CVs is standard course or template text. No changes needed.")
        return
    copied = {i["id"] for i in review.items if review.verdicts.get(i["id"], ("copied",))[0] == "copied"}
    lead = "Please revise your CV before it is submitted." if review.overall == "rewrite_needed" else \
        "A small part of your CV needs changing."
    d.add_paragraph(f"{lead} About {1 - summary.original:.0%} of your CV's own wording also appears in "
                    "another applicant's CV.")
    d.add_heading("What to change", level=2)
    for sec in review.sections:
        d.add_heading(sec["section"], level=3)
        for item in review.items:
            if item["id"] in copied and item["section"] == sec["section"]:
                d.add_paragraph(f"\u201c{item['passage']}\u201d", style="Intense Quote")
        d.add_paragraph(sec["problem"])
        d.add_paragraph(sec["what_to_change"])
        for q in sec["questions"]:
            d.add_paragraph(q, style="List Bullet")


def feedback_docx(file_name: str, summary, review=None) -> bytes:
    d = docx.Document()
    d.styles["Normal"].font.size = Pt(11)
    d.add_heading("CV originality feedback", level=1)
    d.add_paragraph(f"File: {file_name}\nChecked: {date.today():%d %B %Y}")

    copied = 1 - summary.original
    if review is not None and summary.status != GREEN:
        _claude_feedback(d, summary, review)
    elif summary.status == GREEN:
        d.add_paragraph("No wording in your CV matches another applicant's CV. No changes needed.")
    else:
        lead = "Please revise your CV before it is submitted." if summary.status == RED else \
            "A small part of your CV matches another applicant's CV. Please check it."
        d.add_paragraph(f"{lead} About {copied:.0%} of your CV's own wording also appears in "
                        "another applicant's CV.")
        d.add_heading("What to change", level=2)
        by_section = {}
        for m in summary.matches:
            by_section.setdefault(m.section, {}).setdefault(m.text, m)
        for section, items in by_section.items():
            d.add_heading(section, level=3)
            for text in items:
                d.add_paragraph(f"“{text}”", style="Intense Quote")
            d.add_paragraph(ADVICE.get(section, DEFAULT_ADVICE))

    d.add_paragraph(
        "Headings, contact details, dates, common CV phrases and the shared CV template were not counted."
    ).runs[0].italic = True
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def feedback_zip(names, summaries, reviews=None) -> bytes:
    buf = io.BytesIO()
    used = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for s in summaries:
            if s.status != GREEN:
                stem = re.sub(r"[^\w\- ]+", "", names[s.index].rsplit(".", 1)[0]).strip() or "cv"
                if stem in used:
                    stem = f"{stem} ({s.index + 1})"
                used.add(stem)
                review = (reviews or {}).get(s.index)
                review = review if hasattr(review, "overall") else None
                z.writestr(f"{stem} - feedback.docx", feedback_docx(names[s.index], s, review))
    return buf.getvalue()
