import json
import multiprocessing
import os
import stat

import pytest

from cvchecker import phrases_store as ps
from cvchecker.ai import Review
from cvchecker.prepare import load_phrases, prepare
from cvchecker.similarity import analyse


def _store(tmp_path):
    return ps.PhraseStore(tmp_path / "data" / "learned_phrases.json")


def test_missing_file_is_empty_and_first_add_creates_private_folder_and_file(tmp_path):
    store = _store(tmp_path)
    assert store.load().learned == [] and store.load().warning == ""
    store.add("References available on request", "a@laat.ac.uk")
    assert stat.S_IMODE(os.stat(store.path.parent).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(store.path).st_mode) == 0o600
    data = json.loads(store.path.read_text())
    assert data["version"] == 1
    entry = data["learned"][0]
    assert entry["key"] == "references available on request"
    assert entry["added_by"] == "a@laat.ac.uk" and entry["source"] == "claude" and entry["added_at"].endswith("Z")


def test_same_phrase_twice_is_kept_once(tmp_path):
    store = _store(tmp_path)
    store.add("Team player", "a@laat.ac.uk")
    store.add("team-player!", "b@laat.ac.uk")
    assert [p["key"] for p in store.load().learned] == ["team player"]


def test_ignore_and_remove(tmp_path):
    store = _store(tmp_path)
    store.add("worked in a busy shop", "a@laat.ac.uk")
    store.ignore("good with customers every day", "b@laat.ac.uk")
    phrases = store.load()
    assert phrases.keys == {"worked in a busy shop", "good with customers every day"}
    store.remove("worked in a busy shop")
    phrases = store.load()
    assert phrases.learned == [] and [p["key"] for p in phrases.ignored] == ["good with customers every day"]


def _adder(path, prefix):
    store = ps.PhraseStore(path)
    for i in range(15):
        store.add(f"{prefix} phrase number {chr(97 + i)} here", "x@laat.ac.uk")


def test_two_processes_adding_at_once_lose_nothing(tmp_path):
    path = tmp_path / "data" / "learned_phrases.json"
    procs = [multiprocessing.Process(target=_adder, args=(path, p)) for p in ("alpha", "beta")]
    for p in procs:
        p.start()
    for p in procs:
        p.join(30)
    assert len(ps.PhraseStore(path).load().learned) == 30


def test_corrupt_file_is_kept_aside_and_not_overwritten(tmp_path):
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text("{not json")
    phrases = store.load()
    assert phrases.learned == [] and "couldn't be read" in phrases.warning
    kept = [f for f in store.path.parent.iterdir() if ".corrupt-" in f.name]
    assert len(kept) == 1 and kept[0].read_text() == "{not json"
    store.add("references available on request", "a@laat.ac.uk")
    assert kept[0].read_text() == "{not json"
    assert len(store.load().learned) == 1


def test_write_failure_raises_and_leaves_the_file_alone(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.add("references available on request", "a@laat.ac.uk")
    before = store.path.read_text()

    def fail(*_):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(ps.os, "replace", fail)
    with pytest.raises(ps.StoreError, match="No space left"):
        store.add("another stock phrase here", "a@laat.ac.uk")
    assert store.path.read_text() == before
    assert not [f for f in store.path.parent.iterdir() if f.suffix == ".tmp"]


CV = ("Aisha Khan\nProfile\nI study the Extended Diploma in Information Technology at the college and "
      "I built a weather station with my friend for the science fair.")


def _review(verdict, phrases, passage="Extended Diploma in Information Technology at the college and"):
    return Review("no_action", "", {1: (verdict, "")}, [], [{"id": 1, "passage": passage, "section": "Profile"}],
                  common_phrases=phrases)


def test_valid_suggestion_from_a_stock_passage_is_accepted():
    doc = prepare(CV)
    got = ps.validate_suggestions(_review("template_or_stock", ["Extended Diploma in Information Technology"]),
                                  doc, "Aisha Khan CV.pdf", set())
    assert got == [("Extended Diploma in Information Technology", "extended diploma in information technology")]


@pytest.mark.parametrize("phrase", [
    "Information Technology",                                   # too short
    "the " * 16,                                                # too long
    "weather station with my friend",                           # not inside a stock passage
    "Extended Diploma in Information Technology level 3",       # digit, and not in the passage
    "Diploma in Information Technology at aisha@x.com",         # email
    "Khan Extended Diploma in Information",                     # name word
])
def test_bad_suggestions_are_rejected(phrase):
    passage = "Aisha Khan Extended Diploma in Information Technology at the college and"
    doc = prepare(CV)
    assert ps.validate_suggestions(_review("template_or_stock", [phrase], passage), doc, "Aisha Khan CV.pdf", set()) == []


def test_suggestion_inside_a_copied_passage_is_rejected():
    doc = prepare(CV)
    assert ps.validate_suggestions(_review("copied", ["Extended Diploma in Information Technology"]),
                                   doc, "Aisha Khan CV.pdf", set()) == []


def test_known_phrases_are_not_suggested_again():
    doc = prepare(CV)
    known = {"extended diploma in information technology"}
    assert ps.validate_suggestions(_review("template_or_stock", ["Extended Diploma in Information Technology"]),
                                   doc, "Aisha Khan CV.pdf", known) == []


def test_at_most_five_suggestions_per_cv():
    words = [f"stockword{c}" for c in "abcdefghijklmnop"]
    text = "Aisha Khan\n" + " ".join(words)
    phrases = [" ".join(words[i:i + 3]) for i in range(0, 15, 2)]
    review = _review("template_or_stock", phrases, passage=" ".join(words))
    assert len(ps.validate_suggestions(review, prepare(text), "Aisha Khan CV.pdf", set())) == 5


def test_a_learned_phrase_removes_that_wording_from_matching():
    shared = "completed a work placement at a local primary school helping the teacher every week"
    a = f"Alice writes code for robots at home.\n{shared}"
    b = f"Bilal fixes old bicycles for neighbours.\n{shared}"
    assert analyse([a, b], min_words=8).pairs[0].passages
    learned = analyse([a, b], min_words=8, phrases=load_phrases(learned=[shared])).pairs[0]
    assert learned.passages == [] and learned.copied == 0


def test_common_words_at_the_top_of_a_cv_dont_block_suggestions():
    doc = prepare("Grace Mensah\nI am studying the Extended Diploma in Information Technology at the college")
    review = _review("template_or_stock", ["I am studying the Extended Diploma"],
                     passage="I am studying the Extended Diploma in Information Technology")
    assert ps.validate_suggestions(review, doc, "Grace Mensah CV.pdf", set())
