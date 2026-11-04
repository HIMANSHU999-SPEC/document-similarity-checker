import io
import unicodedata

import fitz
import pandas as pd

from conftest import P1, P2
from cvchecker.report import to_excel, to_pdf
from cvchecker.similarity import analyse
from cvchecker.triage import Group, summarise

NAMES = ["aisha.pdf", "bilal & co <cv>.docx"]
IDS = ["Doc #1", "Doc #2"]
T = (0.5, 0.25)


def _run():
    a = analyse([P1 + " " + P2, P2 + " " + P1], min_words=8)
    return NAMES, IDS, a, summarise(a, T), T, [("scan.pdf", "No readable text")], [["x.pdf", "y.pdf"]]


def test_excel_has_all_sheets():
    sheets = pd.read_excel(io.BytesIO(to_excel(*_run())), sheet_name=None)
    assert set(sheets) == {"Triage", "Pairs", "Passages", "Issues"}
    assert sheets["Pairs"]["Flagged"].tolist() == [True]
    assert sheets["Triage"]["Status"].tolist() == ["Needs review", "Needs review"]
    assert len(sheets["Issues"]) == 2


def test_pdf_lists_cvs_to_review_and_escapes_names():
    data = to_pdf(*_run(), groups=[Group([0, 1], "Profile", "shared words")], run_by="staff@laat.ac.uk")
    with fitz.open(stream=data, filetype="pdf") as pdf:
        text = unicodedata.normalize("NFKC", "".join(page.get_text() for page in pdf))
    assert "bilal & co <cv>.docx" in text
    assert "1 flagged pairs" in text
    assert "Copying groups" in text
    assert "scan.pdf" in text
    assert "staff@laat.ac.uk" in text
