import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

HEADER = "Top of CV"
SECTIONS = {
    "Profile": ["profile", "personal profile", "personal statement", "about me", "summary",
                "professional summary", "career objective", "objective", "career summary"],
    "Skills": ["skills", "key skills", "technical skills", "core skills", "skills and abilities",
               "core competencies", "competencies"],
    "Experience": ["experience", "work experience", "employment", "employment history", "work history",
                   "professional experience", "volunteering", "voluntary work", "volunteer experience",
                   "work placement", "placements", "projects"],
    "Education": ["education", "qualifications", "education and qualifications", "academic history",
                  "training", "certifications", "courses"],
    "Achievements": ["achievements", "awards", "awards and achievements", "accomplishments"],
    "Interests": ["interests", "hobbies", "hobbies and interests", "interests and hobbies",
                  "extracurricular activities"],
    "References": ["references", "referees"],
    "Contact": ["contact", "contact details", "contact information", "personal details",
                "personal information"],
}
_HEADINGS = {alias: name for name, aliases in SECTIONS.items() for alias in aliases}

MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
PERSONAL = re.compile("|".join([
    r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",                       # email
    r"(?:https?://|www\.)\S+|\b[\w-]+\.(?:com|co\.uk|org|net|io|ac\.uk)/\S*",  # web links
    r"\+?\(?\d[\d\s().-]{7,}\d",                            # phone numbers and long digit runs
    r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b",               # UK postcode
    rf"\b(?:\d{{1,2}}(?:st|nd|rd|th)?\s+)?{MONTHS}\s+\d{{4}}\b",  # 3 March 2024, Sept 2023
    r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b",                 # 03/09/2024
    r"\b(?:19|20)\d{2}\b",                                  # years
]), re.IGNORECASE)

TOKEN = re.compile(r"[^\W_]+(?:['’][^\W_]+)?")
_WORDS = re.compile(r"[^\W_]+")
DEFAULT_PHRASES_FILE = Path(__file__).with_name("common_phrases.txt")


def normalize(word: str) -> str:
    word = unicodedata.normalize("NFKD", word.replace("’", "'"))
    return "".join(c for c in word if not unicodedata.combining(c)).lower()


@dataclass
class Prepared:
    text: str
    tokens: list[str] = field(default_factory=list)
    spans: list[tuple[int, int]] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)

    def excerpt(self, start: int, length: int) -> str:
        parts = []
        for i in range(start, start + length):
            a, b = self.spans[i]
            if i > start:
                gap = self.text[self.spans[i - 1][1]:a]
                # A line break between two counted words may hide a skipped heading; keep only its punctuation.
                parts.append(_WORDS.sub(" ", gap) if "\n" in gap else gap)
            parts.append(self.text[a:b])
        return " ".join("".join(parts).split())


def load_phrases(path=DEFAULT_PHRASES_FILE, extra: str = "") -> list[list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines += extra.splitlines()
    phrases = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#"):
            words = [normalize(m.group()) for m in TOKEN.finditer(line)]
            if words:
                phrases.append(words)
    return sorted(phrases, key=len, reverse=True)


def _heading(line: str):
    """Return (section, rest of line) when the line starts a CV section."""
    stripped = line.strip().strip("•*-–—:|").strip()
    key = " ".join(normalize(w) for w in TOKEN.findall(stripped))
    if key in _HEADINGS and len(stripped) <= 40:
        return _HEADINGS[key], ""
    head, sep, rest = stripped.partition(":")
    key = " ".join(normalize(w) for w in TOKEN.findall(head))
    if sep and key in _HEADINGS:
        return _HEADINGS[key], rest
    return None, line


def prepare(text: str, phrases=()) -> Prepared:
    masked = PERSONAL.sub(lambda m: " " * len(m.group()), text)
    doc = Prepared(text=masked)
    section = HEADER
    offset = 0
    for line in masked.splitlines(keepends=True):
        found, rest = _heading(line)
        if found:
            section = found
            start = offset + line.rfind(rest) if rest else offset + len(line)
            body = rest
        else:
            start, body = offset, line
        for m in TOKEN.finditer(body):
            doc.tokens.append(normalize(m.group()))
            doc.spans.append((start + m.start(), start + m.end()))
            doc.sections.append(section)
        offset += len(line)
    if phrases:
        _strip_phrases(doc, phrases)
    return doc


def _strip_phrases(doc: Prepared, phrases):
    by_first = {}
    for p in phrases:
        by_first.setdefault(p[0], []).append(p)
    keep = [True] * len(doc.tokens)
    i = 0
    while i < len(doc.tokens):
        for p in by_first.get(doc.tokens[i], ()):
            if doc.tokens[i:i + len(p)] == p:
                for j in range(i, i + len(p)):
                    keep[j] = False
                i += len(p) - 1
                break
        i += 1
    doc.tokens = [t for t, k in zip(doc.tokens, keep) if k]
    doc.spans = [s for s, k in zip(doc.spans, keep) if k]
    doc.sections = [s for s, k in zip(doc.sections, keep) if k]
