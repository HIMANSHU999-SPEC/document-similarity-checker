import io
import json
from types import SimpleNamespace

import docx
import pytest

from conftest import P1, P2
from cvchecker import ai
from cvchecker.feedback import feedback_docx
from cvchecker.similarity import analyse
from cvchecker.triage import summarise

T = (0.8, 0.25)


class FakeClient:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, str):
            return SimpleNamespace(stop_reason=answer, content=[], usage=SimpleNamespace(input_tokens=10, output_tokens=0))
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=json.dumps(answer))],
            usage=SimpleNamespace(input_tokens=3000, output_tokens=800),
        )


ANSWER = {
    "overall": "rewrite_needed",
    "staff_note": "Shared statement.",
    "one_line": "Experience is copied: rewrite it using the stock-tracking work.",
    "common_phrases": [],
    "matches": [{"id": 1, "verdict": "copied", "reason": "Personal experience copied word for word."}],
    "sections": [{
        "section": "Experience",
        "problem": "Your experience section repeats another applicant's description.",
        "what_to_change": "Describe the stock-tracking work you mention in your Interests.",
        "questions": ["What did you build yourself?", "What changed because of it?"],
    }],
}


def _cv(name, profile, experience):
    return (f"{name}\n{name.split()[0].lower()}@example.com | 07700 900123\n"
            f"Profile\n{profile}\nWork Experience\n{experience}")


def _setup(n_copies=2):
    profiles = [
        "Aisha built a weather app in Python and enjoys football and photography with her friends.",
        "Bilal repaired laptops at a local shop and enjoys cricket and cooking for his whole family.",
        "Chen designed posters for a charity event and enjoys swimming and reading fantasy novels.",
    ]
    names = ["Aisha Khan", "Bilal Ahmed", "Chen Li"]
    docs = [_cv(names[i], profiles[i], P1 if i < n_copies else P2) for i in range(3)]
    docs += [_cv(f"Extra Person{i}", f"Unique profile words number {i} about hobby{i} and goal{i} here.",
                 f"Worked at place{i} doing task{i} for client{i} with outcome{i}.") for i in range(4)]
    analysis = analyse(docs, min_words=10)
    summaries = {s.index: s for s in summarise(analysis, T)}
    return analysis, summaries


def test_request_uses_sonnet_fallback_effort_and_schema():
    analysis, summaries = _setup()
    client = FakeClient([ANSWER])
    review = ai.review_cv(client, summaries[0], analysis)
    call = client.calls[0]
    assert call["model"] == "claude-sonnet-5-5"
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["output_config"]["effort"] == "low"
    assert call["output_config"]["format"]["schema"] == ai.REVIEW_SCHEMA
    assert review.overall == "rewrite_needed"
    assert review.verdicts[1][0] == "copied"
    assert round(review.usage.cost, 4) == 0.014


def test_payload_has_context_but_no_contact_details_or_other_names():
    analysis, summaries = _setup()
    client = FakeClient([ANSWER])
    ai.review_cv(client, summaries[0], analysis)
    sent = client.calls[0]["messages"][0]["content"]
    payload = json.loads(sent)
    item = payload["matched_passages"][0]
    assert "cloud migration project" in item["passage"]
    assert item["section"] == "Experience"
    assert item["words_before"]
    assert "@" not in sent and "07700" not in sent
    assert "Bilal" not in sent


def test_same_passage_in_several_cvs_is_sent_once():
    analysis, summaries = _setup(n_copies=3)
    items = ai.review_items(summaries[0], analysis)
    assert len(items) == 1
    assert items[0]["also_in_other_cvs"] == 2


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_refusal_or_cut_off_answer_raises_a_readable_error(stop):
    analysis, summaries = _setup()
    with pytest.raises(ai.AIError):
        ai.review_cv(FakeClient([stop]), summaries[0], analysis)


def test_review_many_keeps_going_when_one_fails():
    analysis, summaries = _setup()
    flagged = [s for s in summaries.values() if s.status != "Original"]
    client = FakeClient(["refusal", ANSWER])
    results = ai.review_many(client, flagged, analysis, workers=1)
    assert len(results) == len(flagged)
    kinds = sorted(type(r).__name__ for r in results.values())
    assert kinds == ["AIError", "Review"]


def _text(data):
    return "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)


def test_feedback_sheet_uses_claude_advice_and_questions():
    analysis, summaries = _setup()
    review = ai.review_cv(FakeClient([ANSWER]), summaries[0], analysis)
    text = _text(feedback_docx("Aisha.pdf", summaries[0], review))
    assert "Describe the stock-tracking work" in text
    assert "What did you build yourself?" in text
    assert "cloud migration project" in text


def test_no_action_review_tells_student_nothing_to_change():
    analysis, summaries = _setup()
    answer = dict(ANSWER, overall="no_action", sections=[],
                  matches=[{"id": 1, "verdict": "template_or_stock", "reason": "Course description."}])
    review = ai.review_cv(FakeClient([answer]), summaries[0], analysis)
    text = _text(feedback_docx("Aisha.pdf", summaries[0], review))
    assert "No changes needed" in text
    assert "cloud migration project" not in text


def test_batch_summary_sends_no_cv_text():
    analysis, summaries = _setup()
    client = FakeClient([{"summary": "Two CVs share a paragraph.", "priorities": ["Check Doc #1"]}])
    ids = [f"Doc #{i + 1}" for i in range(7)]
    data, _ = ai.summarise_check(client, ids, list(summaries.values()), [], {})
    sent = client.calls[0]["messages"][0]["content"]
    assert "cloud migration" not in sent and "Aisha" not in sent
    assert data["priorities"] == ["Check Doc #1"]


def test_review_returns_one_line_and_common_phrases_and_requires_them():
    analysis, summaries = _setup()
    answer = dict(ANSWER, common_phrases=["references available on request"])
    review = ai.review_cv(FakeClient([answer]), summaries[0], analysis)
    assert review.one_line.startswith("Experience is copied")
    assert review.common_phrases == ["references available on request"]
    assert {"one_line", "common_phrases"} <= set(ai.REVIEW_SCHEMA["required"])
