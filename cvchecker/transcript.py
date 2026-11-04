import io
import re
from collections import defaultdict
from dataclasses import dataclass

import docx

TIME = r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?"
CUE = re.compile(rf"^\s*({TIME})\s*-->\s*({TIME})")
VOICE = re.compile(r"<v(?:\.[^ >]*)?\s+([^>]+)>(.*?)(?:</v>|$)", re.S)
HEADER = re.compile(rf"^\s*(?P<name>[^\d:][^:]{{0,80}}?)\s+(?P<time>{TIME})\s*$")
BRACKET = re.compile(rf"^\s*\[?(?P<time>{TIME})\]?\s+(?P<name>[^:]{{1,80}}):\s*(?P<text>.+)$")

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<![\w:])\+?\(?\d[\d\s().-]{8,}\d(?![\w:])")


@dataclass
class Line:
    start: float
    end: float
    speaker: str
    text: str


def parse_time(value: str) -> float:
    """'14:30' is minutes:seconds; '1:02:03' and '00:14:30.120' are hours:minutes:seconds."""
    value = value.strip().replace(",", ".")
    if not value:
        raise ValueError("empty time")
    parts = value.split(":")
    if len(parts) > 3 or not all(re.fullmatch(r"\d+(?:\.\d+)?", p) for p in parts):
        raise ValueError(f"not a time: {value}")
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + float(p)
    return seconds


def format_time(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:d}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:d}:{s % 60:02d}"


def _parse_cues(text: str) -> list[Line]:
    lines, block, times = [], [], None

    def flush():
        if times and block:
            body = "\n".join(block)
            voices = VOICE.findall(body)
            if voices:
                for name, said in voices:
                    lines.append(Line(times[0], times[1], name.strip(), " ".join(said.split())))
            elif len(block) >= 2 and not block[0].endswith((".", "?", "!")) and len(block[0]) <= 60:
                lines.append(Line(times[0], times[1], block[0].strip(), " ".join(" ".join(block[1:]).split())))
            elif ":" in block[0]:
                name, _, said = block[0].partition(":")
                lines.append(Line(times[0], times[1], name.strip(), " ".join((said + " " + " ".join(block[1:])).split())))

    for raw in text.splitlines():
        m = CUE.match(raw)
        if m:
            flush()
            times, block = (parse_time(m.group(1)), parse_time(m.group(2))), []
        elif raw.strip() and times is not None:
            block.append(raw.strip())
        elif not raw.strip():
            flush()
            times, block = None, []
    flush()
    return lines


def _looks_like_name(value: str) -> bool:
    return len(value.split()) <= 6 and not re.search(r"[.?!,;]", value)


def _parse_headers(text: str) -> list[Line]:
    lines, current = [], None
    for raw in text.splitlines():
        if not raw.strip():
            continue
        bracket = BRACKET.match(raw)
        header = HEADER.match(raw)
        if header and not _looks_like_name(header["name"]):
            header = None
        if bracket:
            lines.append(Line(parse_time(bracket["time"]), 0, bracket["name"].strip(), bracket["text"].strip()))
            current = None
        elif header:
            current = Line(parse_time(header["time"]), 0, header["name"].strip(), "")
            lines.append(current)
        elif current is not None:
            current.text = f"{current.text} {raw.strip()}".strip()
    lines = [ln for ln in lines if ln.text]
    for a, b in zip(lines, lines[1:]):
        a.end = max(a.start, b.start)
    if lines:
        lines[-1].end = lines[-1].start + 30
    return lines


def parse_text(text: str) -> list[Line]:
    text = text.lstrip("﻿")
    return _parse_cues(text) if "-->" in text else _parse_headers(text)


def load(name: str, data: bytes) -> list[Line]:
    if name.lower().endswith(".docx"):
        document = docx.Document(io.BytesIO(data))
        text = "\n".join(p.text for p in document.paragraphs)
    else:
        text = data.decode("utf-8-sig", errors="replace")
    return parse_text(text)


def speakers(lines):
    """Speaker -> (words, first time, last time), most words first."""
    stats = defaultdict(lambda: [0, None, 0.0])
    for ln in lines:
        s = stats[ln.speaker]
        s[0] += len(ln.text.split())
        s[1] = ln.start if s[1] is None else min(s[1], ln.start)
        s[2] = max(s[2], ln.end or ln.start)
    return dict(sorted(((k, tuple(v)) for k, v in stats.items()), key=lambda kv: -kv[1][0]))


def likely_interviewer(lines):
    """The person who speaks across the most of the recording, e.g. the one asking every student questions."""
    stats = speakers(lines)
    if not stats:
        return None
    return max(stats, key=lambda k: (stats[k][2] - stats[k][1], stats[k][0]))


def window(lines, start, end):
    return [ln for ln in lines if ln.start < end and (ln.end or ln.start) >= start]


def labelled(lines, interviewers):
    """Lines as text for Claude, with only two roles: the interviewer, and the student."""
    out = []
    for ln in lines:
        role = "INTERVIEWER" if ln.speaker in interviewers else "STUDENT"
        out.append(f"[{format_time(ln.start)}] {role}: {ln.text}")
    return "\n".join(out)


def redact(text: str):
    """Replace emails and phone numbers with placeholders. Returns (text, {placeholder: original})."""
    mapping, seen = {}, {}

    def swap(kind):
        def repl(m):
            value = m.group()
            if value not in seen:
                n = sum(1 for k in mapping if k.startswith(f"[{kind}_")) + 1
                seen[value] = f"[{kind}_{n}]"
                mapping[seen[value]] = value
            return seen[value]
        return repl

    text = EMAIL.sub(swap("EMAIL"), text)
    text = PHONE.sub(swap("PHONE"), text)
    return text, mapping


def restore(value, mapping):
    if isinstance(value, str):
        for placeholder, original in mapping.items():
            value = value.replace(placeholder, original)
        return value
    if isinstance(value, list):
        return [restore(v, mapping) for v in value]
    if isinstance(value, dict):
        return {k: restore(v, mapping) for k, v in value.items()}
    return value
