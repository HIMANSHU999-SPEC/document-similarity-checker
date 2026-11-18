import json
import os
import stat

from conftest import P1, P2
from cvchecker.guide import SeenStore, should_show
from cvchecker.names import same_student_files
from cvchecker.similarity import analyse
from cvchecker.triage import same_student_twice

OWN = "Aisha built a weather station for the science fair and runs the coding club at lunchtime."
OTHER = "Bilal repairs bicycles for neighbours and volunteers at the food bank on Saturdays."
THIRD = "Chen designs posters for charity events and paints murals at the youth centre."


def test_same_student_from_file_names():
    assert same_student_files("Aisha Khan CV.pdf", "aisha khan - CV (2).docx")
    assert same_student_files("Khan, Aisha.pdf", "Aisha Khan updated CV final.docx")
    assert not same_student_files("Aisha Khan CV.pdf", "Bilal Ahmed CV.pdf")
    assert not same_student_files("CV.pdf", "CV (1).pdf")          # no name: can't tell
    assert not same_student_files("Aisha CV.pdf", "Aisha CV.docx")  # one name only: too risky


def test_same_cv_uploaded_twice_is_found_and_the_fuller_one_kept():
    names = ["Aisha Khan CV.pdf", "Bilal Ahmed CV.pdf", "Aisha Khan CV.docx", "Chen Li CV.pdf"]
    texts = [f"{OWN} {P1}", OTHER, f"{OWN} {P1} I also mentor younger students.", THIRD]
    found = same_student_twice(names, texts, analyse(texts, min_words=8))
    assert [(k, d) for k, d, _ in found] == [(2, 0)]
    assert found[0][2] > 0.9


def test_copying_between_two_students_is_not_mistaken_for_a_duplicate():
    names = ["Aisha Khan CV.pdf", "Bilal Ahmed CV.pdf", "Chen Li CV.pdf"]
    texts = [f"{OWN} {P1} {P2}", f"{OWN} {P1} {P2}", THIRD]   # Bilal copied Aisha's whole CV
    assert same_student_twice(names, texts, analyse(texts, min_words=8)) == []


def test_guide_shows_until_dismissed_and_remembers_who(tmp_path):
    store = SeenStore(tmp_path / "data")
    assert store.load() == set()
    assert should_show("Muskan.Agarwal@laat.ac.uk", store.load(), {})
    store.mark("Muskan.Agarwal@laat.ac.uk")
    assert not should_show("muskan.agarwal@laat.ac.uk", store.load(), {})
    assert should_show("richa.goyal@laat.ac.uk", store.load(), {})
    assert not should_show("richa.goyal@laat.ac.uk", store.load(), {"guide_opened": True})
    assert stat.S_IMODE(os.stat(store.path).st_mode) == 0o600
    assert list(json.loads(store.path.read_text())["seen"]) == ["muskan.agarwal@laat.ac.uk"]


def test_guide_store_survives_a_damaged_file(tmp_path):
    store = SeenStore(tmp_path)
    store.path.write_text("{broken")
    assert store.load() == set()
    store.mark("a@laat.ac.uk")
    assert store.load() == {"a@laat.ac.uk"}
