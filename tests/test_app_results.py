import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import cvchecker.ai as ai
from cvchecker.similarity import analyse
from cvchecker.triage import copying_groups, summarise

APP = str(Path(__file__).resolve().parents[1] / "app.py")
T = (0.8, 0.25)
STOCK = "I am studying the Extended Diploma in Information Technology at the college and enjoying every module"
CVS = {
    "Priya Nair.pdf": f"Priya Nair\nProfile\n{STOCK}. Priya repaired laptops for neighbours on weekends.",
    "Aisha Rahman.pdf": f"Aisha Rahman\nProfile\n{STOCK}. Aisha coached the under twelve netball team.",
    "Grace Mensah.pdf": "Grace Mensah\nProfile\nGrace designs posters for charity events and paints murals at home.",
}
ANSWER = {
    "overall": "no_action", "staff_note": "Course description only.", "one_line": "Nothing to change.",
    "common_phrases": ["Extended Diploma in Information Technology"],
    "matches": [{"id": 1, "verdict": "template_or_stock", "reason": "Course title."}], "sections": [],
}


class FakeClient:
    def __init__(self):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(ANSWER))],
                               usage=SimpleNamespace(input_tokens=2000, output_tokens=400))


def _results():
    names = list(CVS)
    analysis = analyse(list(CVS.values()), 10)
    return {"names": names, "ids": [f"Doc #{i + 1}" for i in range(len(names))], "analysis": analysis,
            "summaries": summarise(analysis, T), "groups": copying_groups(analysis, T), "thresholds": T,
            "problems": [], "duplicates": []}


@pytest.fixture
def fake(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(ai, "make_client", lambda key: client)
    st.cache_resource.clear()
    yield client
    st.cache_resource.clear()


def _app(tmp_path, with_key=True):
    at = AppTest.from_file(APP, default_timeout=30)
    if with_key:
        at.secrets["anthropic"] = {"api_key": "sk-ant-test"}
    at.secrets["phrases"] = {"path": str(tmp_path / "data" / "learned_phrases.json")}
    at.session_state["results"] = _results()
    at.session_state["review_pending"] = True
    return at


def test_flagged_cvs_are_reviewed_automatically_and_shown_in_one_table(tmp_path, fake):
    at = _app(tmp_path).run()
    assert not at.exception
    assert len(fake.calls) == 2
    sent = " ".join(c["messages"][0]["content"] for c in fake.calls)
    assert "posters" not in sent
    assert len(at.tabs) == 0
    table = at.dataframe[0].value
    assert list(table.columns) == ["Doc ID", "CV", "Status", "What to change"]
    assert set(table["Status"]) == {"✅ OK"}
    assert any("Claude: about $" in c.value for c in at.caption)


def test_table_renders_with_fallback_text_when_claude_is_off(tmp_path, fake):
    at = _app(tmp_path, with_key=False).run()
    assert not at.exception and fake.calls == []
    table = at.dataframe[0].value
    assert "🔴 Needs review" in set(table["Status"])
    assert any("match another CV" in w or "matches another CV" in w for w in table["What to change"])


def test_add_suggested_phrase_writes_the_phrases_file(tmp_path, fake):
    at = _app(tmp_path).run()
    add = next(b for b in at.button if b.label == "Add")
    add.click().run()
    assert not at.exception
    saved = json.loads((tmp_path / "data" / "learned_phrases.json").read_text())
    assert [p["key"] for p in saved["learned"]] == ["extended diploma in information technology"]
    assert not any(b.label == "Add" for b in at.button)
