from collections import Counter

from cvchecker.ai import AIError, Review
from cvchecker.fix_table import NOTHING, fallback_text, fix_rows
from cvchecker.triage import AMBER, GREEN, RED, CvSummary


def _summary(i, status, original, sections=None):
    return CvSummary(i, status, original, None, 0.0, Counter(sections or {}))


def _review(overall, one_line=""):
    return Review(overall, "", {}, [], [], one_line=one_line)


NAMES = ["Priya Nair.pdf", "Aisha Rahman.docx", "Daniel Okafor.pdf", "Grace Mensah.pdf"]
IDS = ["Doc #1", "Doc #2", "Doc #3", "Doc #4"]


def test_claude_verdict_sets_status_and_beats_matching():
    summaries = [_summary(0, RED, 0.4, {"Profile": 30}), _summary(1, RED, 0.5, {"Profile": 20}),
                 _summary(2, AMBER, 0.9, {"Skills": 10}), _summary(3, GREEN, 1.0)]
    reviews = {0: _review("rewrite_needed", "Profile is copied: rewrite it."),
               1: _review("no_action", "ignored"), 2: _review("small_fixes", "Skills line is copied.")}
    rows = {r.doc_id: r for r in fix_rows(NAMES, IDS, summaries, reviews)}
    assert (rows["Doc #1"].icon, rows["Doc #1"].status, rows["Doc #1"].what) == ("🔴", "Rewrite needed", "Profile is copied: rewrite it.")
    assert (rows["Doc #2"].status, rows["Doc #2"].what) == ("OK", NOTHING)
    assert rows["Doc #3"].status == "Small fixes"
    assert (rows["Doc #4"].icon, rows["Doc #4"].status, rows["Doc #4"].what) == ("✅", "OK", NOTHING)
    assert rows["Doc #1"].cv == "Priya Nair"


def test_sort_order_is_rewrite_then_small_then_ok_then_original_share():
    summaries = [_summary(0, GREEN, 1.0), _summary(1, RED, 0.6), _summary(2, RED, 0.3), _summary(3, AMBER, 0.95)]
    reviews = {1: _review("rewrite_needed"), 2: _review("rewrite_needed"), 3: _review("small_fixes")}
    order = [r.doc_id for r in fix_rows(NAMES, IDS, summaries, reviews)]
    assert order == ["Doc #3", "Doc #2", "Doc #4", "Doc #1"]


def test_fallback_when_claude_missing_or_failed():
    summaries = [_summary(0, RED, 0.5, {"Profile": 30, "Experience": 10}), _summary(1, AMBER, 0.9, {"Skills": 12})]
    rows = {r.doc_id: r for r in fix_rows(NAMES, IDS, summaries, {0: AIError("Claude is rate limiting")})}
    assert rows["Doc #1"].status == "Needs review" and not rows["Doc #1"].from_claude
    assert rows["Doc #1"].what == "Profile and Experience match another CV: rewrite these sections in your own words."
    assert rows["Doc #2"].what == "Skills matches another CV: rewrite this section in your own words."
    assert fallback_text(_summary(2, GREEN, 1.0)) == NOTHING
