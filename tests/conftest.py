import io
import sys
from pathlib import Path

import docx
import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

P1 = ("I led a team of five engineers to deliver a cloud migration project "
      "for a retail client ahead of schedule and under budget.")
P2 = ("Volunteered every weekend at the local food bank organising donations "
      "and coordinating twenty volunteers across three sites.")


def make_pdf(*pages: str) -> bytes:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(50, 50, 550, 800), text, fontsize=10)
    return doc.tobytes()


def make_docx(paragraphs=(), table=(), header=None) -> bytes:
    doc = docx.Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    if table:
        t = doc.add_table(rows=len(table), cols=1)
        for i, text in enumerate(table):
            t.cell(i, 0).text = text
    if header:
        doc.sections[0].header.is_linked_to_previous = False
        doc.sections[0].header.paragraphs[0].text = header
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.fixture
def paragraphs():
    return P1, P2
