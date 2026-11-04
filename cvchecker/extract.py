import hashlib
import io
import zipfile
from dataclasses import dataclass

import docx
import fitz
from docx.oxml.ns import qn

PDF = "pdf"
DOCX = "docx"
MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


@dataclass
class Extracted:
    name: str
    text: str
    kind: str | None
    sha256: str
    problem: str | None = None

    @property
    def ok(self) -> bool:
        return self.problem is None


def detect_kind(name: str, data: bytes) -> str | None:
    if data.startswith(b"%PDF"):
        return PDF
    if data.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if "word/document.xml" in z.namelist():
                    return DOCX
        except zipfile.BadZipFile:
            return None
    return None


def _paragraph_texts(root):
    for p in root.iter(qn("w:p")):
        # Text boxes are stored twice (modern + legacy fallback); skip the fallback copy.
        if any(a.tag == MC_FALLBACK for a in p.iterancestors()):
            continue
        text = "".join(t.text or "" for t in p.iter(qn("w:t")))
        if text.strip():
            yield text


def _docx_text(data: bytes) -> str:
    document = docx.Document(io.BytesIO(data))
    parts = []
    for section in document.sections:
        for part in (section.header, section.first_page_header, section.even_page_header):
            if not part.is_linked_to_previous:
                parts.extend(_paragraph_texts(part._element))
    parts.extend(_paragraph_texts(document.element.body))
    for section in document.sections:
        for part in (section.footer, section.first_page_footer, section.even_page_footer):
            if not part.is_linked_to_previous:
                parts.extend(_paragraph_texts(part._element))
    return "\n".join(dict.fromkeys(parts))


def _pdf_text(data: bytes) -> str:
    with fitz.open(stream=data, filetype="pdf") as pdf:
        return "\n".join(page.get_text() for page in pdf)


def extract(name: str, data: bytes) -> Extracted:
    digest = hashlib.sha256(data).hexdigest()
    kind = detect_kind(name, data)
    if kind is None:
        return Extracted(name, "", None, digest, "Not a PDF or Word (.docx) file")
    try:
        text = _pdf_text(data) if kind == PDF else _docx_text(data)
    except Exception as e:
        return Extracted(name, "", kind, digest, f"Could not be read: {e}")
    if len(text.split()) < 5:
        problem = (
            "No readable text, probably a scanned or image-only PDF"
            if kind == PDF
            else "No readable text in this Word file"
        )
        return Extracted(name, text, kind, digest, problem)
    return Extracted(name, text, kind, digest)
