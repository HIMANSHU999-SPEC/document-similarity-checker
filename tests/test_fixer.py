import hashlib
import io
import itertools
import json
import os
import re
import stat
import zipfile
from types import SimpleNamespace

import docx

from cvchecker import fixer
from cvchecker.ai import Review
from cvchecker.prepare import load_phrases, prepare
from cvchecker.similarity import analyse
from cvchecker.special import can_use, code_matches
from cvchecker.triage import summarise

T = (0.8, 0.25)
COPIED = ("I am a passionate and curious software engineering student who loves turning messy real world "
          "problems into simple reliable tools that people actually enjoy using every day")
OWN = ["Aisha mends bicycles for neighbours and runs a small repair stall at the Saturday market.",
       "Bilal volunteers at a food bank and keeps the stock spreadsheet up to date every week.",
       "Chen paints murals for local cafes and designs posters for school drama productions.",
       "Dara writes short programs to sort photos and teaches younger cousins basic coding."]
COUNTER = itertools.count(1)


def _cv(name, profile, own):
    first = name.split()[0].lower()
    return (f"{name}\n{first}@example.com | 07700 900{100 + len(name)}\nProfile\n{profile}\n"
            f"Interests\n{own}")


def _results(cvs):
    phrases = load_phrases()
    analysis = analyse(cvs, 10, [], phrases)
    return {"names": [f"{c.splitlines()[0]} CV.pdf" for c in cvs], "ids": [f"Doc #{i + 1}" for i in range(len(cvs))],
            "texts": cvs, "analysis": analysis, "summaries": summarise(analysis, T), "thresholds": T,
            "settings": {"min_words": 10, "template_texts": [], "phrases": phrases}}


class Rewriter:
    """Stand-in Claude: replaces each marked passage with unique words (or echoes it back if lazy)."""

    def __init__(self, lazy_first=0):
        self.calls, self.lazy_first = [], lazy_first
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        cv = json.loads(kw["messages"][0]["content"])["cv"]
        lazy = len(self.calls) <= self.lazy_first
        rewrites = []
        for n, text in re.findall(r"\[\[(\d+)\]\](.*?)\[\[/\1\]\]", cv, re.S):
            new = text if lazy else " ".join(f"fresh{next(COUNTER)}" for _ in text.split())
            rewrites.append({"id": int(n), "text": new})
        body = {"rewrites": rewrites, "questions": ["When did you start?"]}
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(body))],
                               usage=SimpleNamespace(input_tokens=1500, output_tokens=500))


def _batch():
    cvs = [_cv("Aisha Khan", COPIED, OWN[0]), _cv("Bilal Ahmed", COPIED, OWN[1]),
           _cv("Chen Li", "Chen enjoys art and has organised two exhibitions at the youth centre.", OWN[2]),
           _cv("Dara Patel", "Dara likes puzzles and has built three small websites for family members.", OWN[3])]
    return _results(cvs)


def test_only_copied_passages_are_rewritten_and_contact_details_are_kept():
    results = _batch()
    client = Rewriter()
    fixes = fixer.fix_batch(client, results, [0, 1], {}, workers=1)
    sent = " ".join(c["messages"][0]["content"] for c in client.calls)
    assert "@" not in sent and "07700" not in sent
    for i in (0, 1):
        f = fixes[i]
        assert COPIED not in f.text and f.changes
        assert "@example.com" in f.text and "07700 900" in f.text
        assert OWN[i] in f.text
        assert f.after > f.before and not f.still_matches and f.passes == 1


def test_fixed_cvs_are_rechecked_against_each_other():
    results = _batch()
    fixes = fixer.fix_batch(Rewriter(), results, [0, 1], {}, workers=1)
    _, after = fixer.test_run(results, {i: f.text for i, f in fixes.items()})
    assert after[0].status == "Original" and after[1].status == "Original"


def test_second_pass_when_the_first_still_matches():
    results = _batch()
    client = Rewriter(lazy_first=2)
    fixes = fixer.fix_batch(client, results, [0, 1], {}, workers=1)
    assert len(client.calls) == 4
    assert all(f.passes == 2 and not f.still_matches for f in fixes.values())


def test_still_matching_after_two_passes_is_flagged():
    results = _batch()
    fixes = fixer.fix_batch(Rewriter(lazy_first=99), results, [0, 1], {}, workers=1)
    assert all(f.still_matches for f in fixes.values())


def test_template_wording_judged_by_claude_is_left_alone():
    results = _batch()
    s = next(x for x in results["summaries"] if x.index == 0)
    review = Review("no_action", "", {1: ("template_or_stock", "")}, [],
                    [{"id": 1, "passage": m.text, "section": m.section} for m in s.matches[:1]])
    assert fixer.regions(s, review) == []
    assert fixer.regions(s) != []


def test_regions_merge_when_they_touch():
    m = lambda start, words, text: SimpleNamespace(start=start, words=words, text=text)
    s = SimpleNamespace(matches=[m(10, 12, "a"), m(20, 10, "b"), m(40, 10, "c")])
    assert fixer.regions(s) == [(10, 30), (40, 50)]


def _docx_info(data):
    d = docx.Document(io.BytesIO(data))
    p = d.core_properties
    return "\n".join(x.text for x in d.paragraphs), [p.author, p.comments, p.title, p.last_modified_by]


def test_zip_has_clean_cvs_and_staff_reports():
    results = _batch()
    fixes = fixer.fix_batch(Rewriter(), results, [0, 1], {}, workers=1)
    data = fixer.fixed_zip(results["names"], results["ids"], fixes, b"%PDF-original")
    z = zipfile.ZipFile(io.BytesIO(data))
    assert sorted(z.namelist()) == ["CVs/Aisha Khan CV.docx", "CVs/Bilal Ahmed CV.docx",
                                    "Reports (staff only)/fix-report.xlsx", "Reports (staff only)/original-check.pdf"]
    text, props = _docx_info(z.read("CVs/Aisha Khan CV.docx"))
    assert text.splitlines()[0] == "Aisha Khan" and "Profile" in text
    assert props == ["", "", "", ""]
    assert not re.search(r"claude|rewrit|fixed|python-docx", text + " ".join(props), re.I)


def test_special_access_needs_named_email_and_the_code(tmp_path):
    config = {"code_sha256": hashlib.sha256(b"new-secret-code").hexdigest(), "allowed_emails": ["Himanshu@laat.ac.uk"]}
    assert can_use("himanshu@laat.ac.uk", config)
    assert not can_use("someone@laat.ac.uk", config)
    assert not can_use("himanshu@laat.ac.uk", {"allowed_emails": ["himanshu@laat.ac.uk"]})
    assert code_matches(" new-secret-code ", config) and not code_matches("ug@123", config)


def test_wrong_codes_are_counted_from_the_private_log(tmp_path):
    for _ in range(3):
        fixer.log_event(tmp_path, "a@laat.ac.uk", "wrong code")
    fixer.log_event(tmp_path, "b@laat.ac.uk", "wrong code")
    fixer.log_event(tmp_path, "a@laat.ac.uk", "unlock")
    assert fixer.recent_failures(tmp_path, "a@laat.ac.uk") == 3
    assert stat.S_IMODE(os.stat(tmp_path / "special_actions.log").st_mode) == 0o600


def test_rewrites_keep_headings_bullets_and_line_structure():
    copied_lines = ("London\nPERSONAL STATEMENT\n" + COPIED + "\nWork Experience\n"
                    "• Built a stock spreadsheet that cut the weekly count from four hours to one\n"
                    "• Trained two new Saturday staff on the till and the returns process")
    cvs = [f"Aisha Khan\n{copied_lines}\nInterests\n{OWN[0]}", f"Bilal Ahmed\n{copied_lines}\nInterests\n{OWN[1]}",
           _cv("Chen Li", "Chen enjoys art and has organised two exhibitions at the youth centre.", OWN[2]),
           _cv("Dara Patel", "Dara likes puzzles and has built three small websites for family members.", OWN[3])]
    results = _results(cvs)
    fixes = fixer.fix_batch(Rewriter(), results, [0], {}, workers=1)
    lines = fixes[0].text.splitlines()
    assert lines[:3] == ["Aisha Khan", "London", "PERSONAL STATEMENT"]
    assert "Work Experience" in lines and lines.count("Interests") == 1
    assert sum(line.startswith("• ") for line in lines) == 2
    assert len(lines) == len(cvs[0].splitlines())
    assert COPIED not in fixes[0].text and not fixes[0].still_matches


def test_no_double_punctuation_where_the_rewrite_meets_the_original():
    text = "Profile\nI love building robots with my brother at home on weekends. Next sentence."
    start = text.index("I love")
    end = text.index(" on weekends") + len(" on weekends")
    new, _ = fixer.apply(text, [(start, end)], {1: "Robot building at home is my favourite hobby."})
    assert "hobby. Next sentence." in new and ".." not in new


def test_short_lines_keep_their_break_but_wrapped_lines_are_joined():
    text = ("Sales Assistant, Corner Shop\nBuilt a stock tracking spreadsheet for the shop manager that cut the weekly\n"
            "stock count from four hours to under one hour and reduced ordering mistakes")
    doc = prepare(text)
    spans = fixer.char_spans(doc, [(0, len(doc.tokens))])
    pieces = [text[a:b] for a, b in spans]
    assert pieces[0] == "Sales Assistant, Corner Shop"
    assert pieces[1].startswith("Built a stock") and pieces[1].endswith("ordering mistakes")
