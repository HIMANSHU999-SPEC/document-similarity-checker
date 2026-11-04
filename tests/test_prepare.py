from cvchecker.prepare import HEADER, load_phrases, prepare


def test_personal_details_are_removed():
    text = ("Aisha Khan | aisha.khan@example.com | +44 7700 900123 | 020 7946 0958 | "
            "linkedin.com/in/aisha-khan | www.aisha.dev | E1 6AN | 03/09/2024 | Sept 2023 | 2019")
    tokens = prepare(text).tokens
    assert tokens == ["aisha", "khan"]


def test_headings_split_sections_and_are_not_counted():
    text = "Aisha Khan\nPROFILE\nI love robotics.\nWork Experience:\nShop assistant.\nKey Skills\nPython"
    doc = prepare(text)
    assert "profile" not in doc.tokens and "experience" not in doc.tokens
    sections = dict(zip(doc.tokens, doc.sections))
    assert sections["aisha"] == HEADER
    assert sections["robotics"] == "Profile"
    assert sections["shop"] == "Experience"
    assert sections["python"] == "Skills"


def test_heading_on_same_line_as_content():
    doc = prepare("Profile: I build websites for local charities.")
    assert doc.tokens[0] == "i"
    assert doc.sections[0] == "Profile"
    assert doc.excerpt(0, len(doc.tokens)) == "I build websites for local charities"


def test_stock_phrases_are_removed():
    doc = prepare("I am a Team Player with excellent communication skills, and I code.", load_phrases())
    assert doc.tokens == ["i", "am", "a", "with", "and", "i", "code"]


def test_extra_phrases_from_staff():
    phrases = load_phrases(extra="Cisco Networking Academy\n# a comment\n")
    assert prepare("Completed the Cisco Networking Academy course", phrases).tokens == ["completed", "the", "course"]


def test_excerpt_keeps_original_case_and_punctuation():
    doc = prepare("I led   a team of Five Engineers, ahead of schedule.")
    assert doc.excerpt(0, 6) == "I led a team of Five"


def test_excerpt_leaves_out_skipped_headings():
    doc = prepare("I love robotics,\nPERSONAL STATEMENT\nand I build drones.")
    assert doc.excerpt(0, len(doc.tokens)) == "I love robotics, and I build drones"
