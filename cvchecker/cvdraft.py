import copy
import io

import docx
from docx.text.paragraph import Paragraph
from docx.shared import Pt

from cvchecker.ai import ask

PLACEHOLDER = "{{CV}}"

SYSTEM = """You turn a Teams interview transcript into a first-draft CV for a student at a UK college (London Academy for Applied Technology).

The transcript has two roles. INTERVIEWER lines are questions: use them only to understand what the student is answering. STUDENT lines are the only source of facts.

Rules:
- Use only what the student said. Never invent or assume a job, date, grade, skill or achievement. If something is unclear, leave it out and ask about it in missing.
- Keep the student's own words and phrasing wherever they read well; tidy grammar only. Avoid stock CV phrases such as "team player", "hard-working", "excellent communication skills", "passionate about". Each CV must read as this student's own.
- Write the profile in the first person, 3 to 4 short sentences, from what the student said about themselves and their goals.
- Experience bullet points are short, start with a verb, and describe what the student actually did.
- Every item has evidence: a short verbatim quote from a STUDENT line that supports it.
- name_as_said: the student's full name exactly as they say it when asked (for example "My name is Aisha Khan"). Empty if they never say it.
- Emails and phone numbers appear as placeholders like [EMAIL_1] or [PHONE_1]. Copy a placeholder into email or phone if the student gives one; never guess real values.
- missing: up to 6 short questions staff could ask the student to complete the CV (for example missing dates or results).
- UK English and UK date style. Leave a field as an empty string or empty list when there is nothing for it.
- conflicts: always an empty list for a new CV."""

UPDATE_SYSTEM = """You update a student's existing CV using a Teams interview transcript, for a UK college (London Academy for Applied Technology).

You get existing_cv (the student's current CV) and transcript. In the transcript, INTERVIEWER lines are questions: use them only to understand the answers. STUDENT lines and the existing CV are the only sources of facts.

Rules:
- Keep every accurate fact from the existing CV. Add what the student said in the interview that the CV is missing, and use the interview to make vague CV lines specific.
- Never invent or assume a job, date, grade, skill or achievement.
- Where the CV and the interview disagree (for example different dates, roles or results), keep the CV's version in the CV and add the disagreement to conflicts, quoting both. Never settle a conflict yourself.
- Keep the student's own words and phrasing wherever they read well; tidy grammar only. Avoid stock CV phrases such as "team player", "hard-working", "excellent communication skills", "passionate about".
- Profile in the first person, 3 to 4 short sentences. Experience bullet points are short, start with a verb, and describe what the student actually did.
- Every item has evidence: a short verbatim quote starting "CV: " or "Interview: " (or both, separated by " | ") showing where it came from.
- name_as_said: the student's full name exactly as they say it in the interview. Empty if they never say it.
- email and phone: copy the CV's or the student's placeholders such as [EMAIL_1] or [PHONE_1]; never guess real values.
- missing: up to 6 short questions staff could ask the student to complete the CV.
- UK English and UK date style. Leave a field as an empty string or empty list when there is nothing for it."""

_ITEM = {"type": "object", "additionalProperties": False, "required": ["text", "evidence"],
         "properties": {"text": {"type": "string"}, "evidence": {"type": "string"}}}

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name_as_said", "email", "phone", "profile", "skills", "experience", "education",
                 "achievements", "interests", "missing", "conflicts"],
    "properties": {
        "name_as_said": {"type": "string"},
        "email": {"type": "string"},
        "phone": {"type": "string"},
        "profile": _ITEM,
        "skills": {"type": "array", "items": _ITEM},
        "experience": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["role", "organisation", "dates", "points", "evidence"],
            "properties": {"role": {"type": "string"}, "organisation": {"type": "string"},
                           "dates": {"type": "string"}, "points": {"type": "array", "items": {"type": "string"}},
                           "evidence": {"type": "string"}},
        }},
        "education": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["qualification", "institution", "dates", "evidence"],
            "properties": {"qualification": {"type": "string"}, "institution": {"type": "string"},
                           "dates": {"type": "string"}, "evidence": {"type": "string"}},
        }},
        "achievements": {"type": "array", "items": _ITEM},
        "interests": {"type": "array", "items": _ITEM},
        "missing": {"type": "array", "items": {"type": "string"}},
        "conflicts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["topic", "cv_says", "interview_says"],
            "properties": {"topic": {"type": "string"}, "cv_says": {"type": "string"},
                           "interview_says": {"type": "string"}},
        }},
    },
}

CV_MARKER = "\n\n=== EXISTING CV ===\n"


def draft_cv(client, labelled_transcript: str, existing_cv: str = ""):
    """New CV from the transcript, or an update of existing_cv using it. Both inputs must already be redacted."""
    if existing_cv.strip():
        payload = {"existing_cv": existing_cv, "transcript": labelled_transcript}
        data, usage = ask(client, UPDATE_SYSTEM, payload, SCHEMA, effort="medium")
    else:
        data, usage = ask(client, SYSTEM, {"transcript": labelled_transcript}, SCHEMA, effort="medium")
    data.setdefault("conflicts", [])
    return data, usage


def cv_text(draft: dict) -> str:
    """Plain text of the CV body, for the originality check."""
    parts = ["Profile", draft["profile"]["text"], "Skills"]
    parts += [s["text"] for s in draft["skills"]]
    parts.append("Work Experience")
    for e in draft["experience"]:
        parts.append(" ".join(x for x in (e["role"], e["organisation"]) if x))
        parts += e["points"]
    parts.append("Education")
    parts += [" ".join(x for x in (e["qualification"], e["institution"]) if x) for e in draft["education"]]
    parts.append("Achievements")
    parts += [a["text"] for a in draft["achievements"]]
    parts.append("Interests")
    parts += [i["text"] for i in draft["interests"]]
    return "\n".join(p for p in parts if p)


def _blocks(name, draft):
    """(kind, text) blocks in reading order."""
    out = [("title", name)]
    contact = " | ".join(x for x in (draft["email"], draft["phone"]) if x)
    if contact:
        out.append(("contact", contact))
    if draft["profile"]["text"]:
        out += [("heading", "Profile"), ("para", draft["profile"]["text"])]
    if draft["skills"]:
        out.append(("heading", "Skills"))
        out += [("bullet", s["text"]) for s in draft["skills"]]
    experience = [e for e in draft["experience"] if e["role"] or e["organisation"] or e["points"]]
    if experience:
        out.append(("heading", "Experience"))
        for e in experience:
            line = " – ".join(x for x in (e["role"], e["organisation"]) if x)
            out.append(("role", f"{line}, {e['dates']}" if e["dates"] else line))
            out += [("bullet", p) for p in e["points"]]
    education = [e for e in draft["education"] if e["qualification"] or e["institution"]]
    if education:
        out.append(("heading", "Education"))
        for e in education:
            line = ", ".join(x for x in (e["qualification"], e["institution"]) if x)
            out.append(("para", f"{line} ({e['dates']})" if e["dates"] else line))
    for key, title in (("achievements", "Achievements"), ("interests", "Interests")):
        if draft[key]:
            out.append(("heading", title))
            out += [("bullet", a["text"]) for a in draft[key]]
    return out


def _style(d, wanted, fallback):
    names = {s.name for s in d.styles}
    return wanted if wanted in names else fallback


def build_docx(name: str, draft: dict, template: bytes | None = None, note: str = "") -> bytes:
    d = docx.Document(io.BytesIO(template)) if template else docx.Document()
    if not template:
        d.styles["Normal"].font.size = Pt(11)
    styles = {
        "title": _style(d, "Title", "Normal"), "heading": _style(d, "Heading 1", "Normal"),
        "role": _style(d, "Heading 2", "Normal"), "bullet": _style(d, "List Bullet", "Normal"),
        "contact": "Normal", "para": "Normal",
    }
    anchor = next((p for p in d.paragraphs if PLACEHOLDER in p.text), None)
    for kind, text in _blocks(name, draft):
        if anchor is not None:
            para = copy.deepcopy(anchor._p)
            anchor._p.addprevious(para)
            new = Paragraph(para, anchor._parent)
            for r in new.runs[1:]:
                r._r.getparent().remove(r._r)
            if new.runs:
                new.runs[0].text = text
            else:
                new.add_run(text)
            new.style = d.styles[styles[kind]]
        else:
            d.add_paragraph(text, style=styles[kind])
    if anchor is not None:
        anchor._p.getparent().remove(anchor._p)
    if note:
        d.core_properties.comments = note
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
