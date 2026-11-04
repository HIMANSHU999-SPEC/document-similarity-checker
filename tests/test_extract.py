import fitz

from conftest import P1, P2, make_docx, make_pdf
from cvchecker.extract import extract


def test_pdf_text_across_pages():
    r = extract("a.pdf", make_pdf(P1, P2))
    assert r.ok and r.kind == "pdf"
    assert "budget" in r.text and "Volunteered" in r.text


def test_docx_body_table_and_header():
    r = extract("cv.docx", make_docx([P1], table=[P2], header="Aisha Khan CV"))
    assert r.ok
    assert "cloud migration" in r.text
    assert "food bank" in r.text
    assert "Aisha Khan" in r.text


def test_type_detected_from_contents_not_name():
    assert extract("upload.bin", make_docx([P1])).kind == "docx"
    assert extract("cv.docx", make_pdf(P1)).kind == "pdf"


def test_scanned_pdf_is_reported():
    doc = fitz.open()
    doc.new_page()
    r = extract("scan.pdf", doc.tobytes())
    assert not r.ok
    assert "scanned" in r.problem


def test_unsupported_file_is_reported():
    r = extract("notes.txt", b"plain text")
    assert not r.ok and r.kind is None


def test_corrupt_docx_is_reported():
    r = extract("broken.docx", b"PK\x03\x04 not really a zip")
    assert not r.ok


def test_identical_bytes_share_a_fingerprint():
    data = make_pdf(P1)
    assert extract("a.pdf", data).sha256 == extract("b.pdf", data).sha256
