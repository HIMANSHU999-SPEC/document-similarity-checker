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
    pairs = analyse(PEOPLE[:2], min_words=5).pairs
    assert pairs[0].passages == []
    assert pairs[0].copied == 0


def test_copied_share_is_directional():
    small = P1
    big = " ".join([P1, P2, FILL[0], FILL[1]])
    pairs = analyse([small, big], min_words=8).pairs
    p = pairs[0]
    assert p.copied_a_in_b == 1.0
    assert 0.2 < p.copied_b_in_a < 0.5


def test_shared_template_text_is_ignored_across_a_batch():
    docs = [TEMPLATE + " " + person for person in PEOPLE]
    result = analyse(docs, min_words=8)
    pairs, boilerplate = result.pairs, result.boilerplate
    assert boilerplate > 0
    assert all(p.copied == 0 for p in pairs)
    assert all(p.score < 0.5 for p in pairs)


def test_uploaded_template_is_ignored_for_two_documents():
    docs = [TEMPLATE + " " + PEOPLE[0], TEMPLATE + " " + PEOPLE[1]]
    without = analyse(docs, min_words=8).pairs
    with_template = analyse(docs, min_words=8, template_texts=[TEMPLATE]).pairs
    assert without[0].copied > 0.5
    assert with_template[0].copied == 0


def test_copying_on_top_of_a_template_is_still_caught():
    docs = [TEMPLATE + " " + person for person in PEOPLE]
    docs.append(TEMPLATE + " " + PEOPLE[0])
    pairs = analyse(docs, min_words=8).pairs
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


def test_passages_carry_original_wording_and_sections():
    a = "Profile\nI led a team of Five Engineers to deliver a cloud migration project for a retail client."
    b = "Work Experience\nAt my placement I led a team of five engineers to deliver a cloud migration project for a retail client."
    p = analyse([a, b], min_words=8).pairs[0].passages[0]
    assert p.text_a.startswith("I led a team of Five Engineers")
    assert (p.section_a, p.section_b) == ("Profile", "Experience")


def test_contact_details_and_stock_phrases_do_not_count():
    from cvchecker.prepare import load_phrases
    a = ("Email: aisha.khan@example.com Phone: 07700 900123 Address: 12 High Street, London E1 6AN "
         "references available on request excellent communication skills team player hard working")
    b = ("Email: bilal.ahmed@example.com Phone: 07700 900456 Address: 12 High Street, London E1 6AN "
         "references available on request excellent communication skills team player hard working")
    pairs = analyse([a, b], min_words=8, phrases=load_phrases()).pairs
    assert pairs[0].passages == []


def test_passage_section_is_where_most_of_it_sits():
    copied = "I build reliable tools that people actually enjoy using every single day at work."
    a = f"Aisha Khan London\nProfile\n{copied}"
    b = f"Bilal Ahmed London\nPersonal Statement\n{copied}"
    p = analyse([a, b], min_words=8).pairs[0].passages[0]
    assert p.text_a.startswith("London")
    assert (p.section_a, p.section_b) == ("Profile", "Profile")
