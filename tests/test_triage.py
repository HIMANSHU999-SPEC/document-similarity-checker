import io
import random
import zipfile

import docx

from conftest import P1, P2
from cvchecker.feedback import feedback_docx, feedback_zip
from cvchecker.similarity import analyse
from cvchecker.triage import AMBER, GREEN, RED, copying_groups, summarise

T = (0.8, 0.25)
OWN = [
    "Profile\nAlice built a weather app in Python and enjoys football and photography with friends at weekends.",
    "Profile\nBilal repaired laptops at a local shop and enjoys cricket and cooking for his family every week.",
    "Profile\nChen designed posters for a charity event and enjoys swimming and reading fantasy novels at night.",
]


def _cv(profile, experience):
    return f"Profile\n{profile}\nWork Experience\n{experience}"


def test_status_original_share_and_sections():
    docs = [_cv(OWN[0], P1), _cv(OWN[1], P1), _cv(OWN[2], P2)]
    a = analyse(docs, min_words=10)
    by_index = {s.index: s for s in summarise(a, T)}
    assert by_index[0].status == RED and by_index[1].status == RED
    assert by_index[2].status == GREEN and by_index[2].original == 1.0
    assert by_index[0].main_source == 1
    assert set(by_index[0].sections) == {"Experience"}
    assert 0.3 < by_index[0].original < 0.7


def test_short_match_is_amber_not_red():
    shared = "I volunteered at the local food bank organising weekly donations for families"
    filler = " ".join(f"unique{i} word{i}" for i in range(60))
    docs = [f"{filler} {shared}", f"{shared} " + " ".join(f"other{i} term{i}" for i in range(60))]
    s = summarise(analyse(docs, min_words=10), T)
    assert {x.status for x in s} == {AMBER}


def test_reds_are_listed_first():
    docs = [_cv(OWN[2], P2), _cv(OWN[0], P1), _cv(OWN[1], P1)]
    order = [s.status for s in summarise(analyse(docs, min_words=10), T)]
    assert order == [RED, RED, GREEN]


def test_copying_group_of_three():
    rng = random.Random(7)
    vocab = [f"w{i}" for i in range(2000)]
    others = [_cv(" ".join(rng.choices(vocab, k=40)), " ".join(rng.choices(vocab, k=40))) for _ in range(5)]
    docs = [_cv(o, P1 + " " + P2) for o in OWN] + others
    a = analyse(docs, min_words=10)
    groups = copying_groups(a, T)
    assert [g.docs for g in groups] == [[0, 1, 2]]
    assert groups[0].section == "Experience"


def _docx_text(data):
    return "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)


def test_feedback_sheet_quotes_section_and_hides_other_applicant():
    docs = [_cv(OWN[0], P1), _cv(OWN[1], P1)]
    names = ["Alice CV.pdf", "Bilal Secret CV.pdf"]
    summary = next(s for s in summarise(analyse(docs, min_words=10), T) if s.index == 0)
    text = _docx_text(feedback_docx(names[0], summary))
    assert "Experience" in text
    assert "cloud migration project" in text
    assert "Bilal" not in text and "Doc #" not in text


def test_feedback_zip_contains_only_flagged_students():
    docs = [_cv(OWN[0], P1), _cv(OWN[1], P1), _cv(OWN[2], P2)]
    names = ["Alice.pdf", "Bilal.pdf", "Chen.pdf"]
    data = feedback_zip(names, summarise(analyse(docs, min_words=10), T))
    assert sorted(zipfile.ZipFile(io.BytesIO(data)).namelist()) == [
        "Alice - feedback.docx", "Bilal - feedback.docx",
    ]


def test_two_separate_copies_are_not_merged_into_one_group():
    rng = random.Random(11)
    vocab = [f"w{i}" for i in range(3000)]
    words = lambda n: " ".join(rng.choices(vocab, k=n))
    statement, job = words(30), words(30)
    docs = []
    for i in range(10):
        profile = statement if i in (0, 1, 2) else words(30)
        experience = job if i in (3, 4) else words(30)
        docs.append(_cv(profile, experience))
    a = analyse(docs, min_words=10)
    assert [(g.docs, g.section) for g in copying_groups(a, T)] == [([0, 1, 2], "Profile")]
