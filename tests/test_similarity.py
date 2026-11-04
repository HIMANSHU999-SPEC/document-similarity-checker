from conftest import P1, P2
from cvchecker.similarity import analyse, matching_passages, tokenize

FILL = [
    "Additional unique sentence about personal hobbies like chess and running every Sunday morning.",
    "Completely different text describing a love of baking bread and growing tomatoes in the garden.",
]
TEMPLATE = ("Personal Statement Key Skills Work Experience Education References available on request "
            "LAAT Level 3 Diploma in Software Engineering student profile prepared for employer review")
PEOPLE = [
    "Alice built a weather app in Python and enjoys football and photography with friends.",
    "Bilal repaired laptops at a local shop and enjoys cricket and cooking for his family.",
    "Chen designed posters for a charity event and enjoys swimming and reading fantasy novels.",
    "Dara wrote scripts to automate spreadsheets and enjoys hiking and playing the guitar.",
]


def test_reordered_copied_paragraphs_are_both_found():
    a = " ".join([P1, FILL[0], P2])
    b = " ".join([P2, FILL[1], P1])
    passages = matching_passages(tokenize(a), tokenize(b), 10)
    texts = [p.text for p in passages]
    assert len(passages) == 2
    assert any("cloud migration" in t for t in texts)
    assert any("food bank" in t for t in texts)


def test_swapped_adjacent_paragraphs_are_both_found():
    a = " ".join(["intro words here", P1, P2, "I enjoy football"])
    b = " ".join(["other start", P2, P1])
    passages = matching_passages(tokenize(a), tokenize(b), 10)
    assert len(passages) == 2


def test_unrelated_documents_have_no_passages():
    _, pairs, _ = analyse(PEOPLE[:2], min_words=5)
    assert pairs[0].passages == []
    assert pairs[0].copied == 0


def test_copied_share_is_directional():
    small = P1
    big = " ".join([P1, P2, FILL[0], FILL[1]])
    _, pairs, _ = analyse([small, big], min_words=8)
    p = pairs[0]
    assert p.copied_a_in_b == 1.0
    assert 0.2 < p.copied_b_in_a < 0.5


def test_shared_template_text_is_ignored_across_a_batch():
    docs = [TEMPLATE + " " + person for person in PEOPLE]
    _, pairs, boilerplate = analyse(docs, min_words=8)
    assert boilerplate > 0
    assert all(p.copied == 0 for p in pairs)
    assert all(p.score < 0.5 for p in pairs)


def test_uploaded_template_is_ignored_for_two_documents():
    docs = [TEMPLATE + " " + PEOPLE[0], TEMPLATE + " " + PEOPLE[1]]
    _, without, _ = analyse(docs, min_words=8)
    _, with_template, _ = analyse(docs, min_words=8, template_texts=[TEMPLATE])
    assert without[0].copied > 0.5
    assert with_template[0].copied == 0


def test_copying_on_top_of_a_template_is_still_caught():
    docs = [TEMPLATE + " " + person for person in PEOPLE]
    docs.append(TEMPLATE + " " + PEOPLE[0])
    _, pairs, _ = analyse(docs, min_words=8)
    copied = [p for p in pairs if p.copied > 0]
    assert [(p.a, p.b) for p in copied] == [(0, 4)]


def test_case_accents_and_punctuation_do_not_hide_a_match():
    a = "Managed the café’s social media, growing followers from 200 to 5,000 in six months."
    b = "managed the CAFE'S social-media growing followers from 200 to 5 000 in six months"
    assert matching_passages(tokenize(a), tokenize(b), 8)


def test_minimum_passage_length_is_respected():
    a = "one two three four five six seven alpha"
    b = "one two three four five six seven beta"
    assert matching_passages(tokenize(a), tokenize(b), 7)
    assert not matching_passages(tokenize(a), tokenize(b), 8)
