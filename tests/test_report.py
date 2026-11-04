import io
import unicodedata

import fitz
import pandas as pd

from conftest import P1, P2
from cvchecker.report import to_excel, to_pdf
from cvchecker.similarity import analyse

NAMES = ["aisha.pdf", "bilal & co <cv>.docx"]


def _run():
    _, pairs, _ = analyse([P1 + " " + P2, P2 + " " + P1], min_words=8)
    return NAMES, pairs, (0.5, 0.25), [("scan.pdf", "No readable text")], [["x.pdf", "y.pdf"]]


def test_excel_has_all_sheets():
    data = to_excel(*_run())
    sheets = pd.read_excel(io.BytesIO(data), sheet_name=None)
    assert set(sheets) == {"Pairs", "Passages", "Issues"}
    assert sheets["Pairs"]["Flagged"].tolist() == [True]
    assert len(sheets["Issues"]) == 2


def test_pdf_lists_flagged_pair_and_escapes_names():
    data = to_pdf(*_run(), run_by="staff@laat.ac.uk")
    with fitz.open(stream=data, filetype="pdf") as pdf:
        text = unicodedata.normalize("NFKC", "".join(page.get_text() for page in pdf))
    assert "bilal & co <cv>.docx" in text
    assert "1 flagged" in text
    assert "scan.pdf" in text
