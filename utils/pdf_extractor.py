"""
pdf_extractor.py
Text extraction for StudyGenie: PDF, Word (.docx) and PowerPoint (.pptx).
Use extract_text(uploaded_file), which picks the right reader from the file name.
"""

import os
from typing import Tuple

from pypdf import PdfReader
from pypdf.errors import PdfReadError

SUPPORTED_TYPES = ["pdf", "docx", "pptx"]


def _rewind(f):
    if hasattr(f, "seek"):
        f.seek(0)


# ----------------------------------------------------------------- PDF
def extract_text_from_pdf(uploaded_file) -> Tuple[str, int]:
    """Return (full_text, num_pages) from a PDF file-like object."""
    _rewind(uploaded_file)
    try:
        reader = PdfReader(uploaded_file)
    except PdfReadError as e:
        raise ValueError(f"Could not read this PDF (it may be corrupted or encrypted): {e}")

    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception:
            raise ValueError("This PDF is password-protected. Please upload an unlocked PDF.")

    page_texts = []
    for page in reader.pages:
        try:
            page_texts.append(page.extract_text() or "")
        except Exception:
            page_texts.append("")
    return "\n\n".join(page_texts).strip(), len(reader.pages)


# ----------------------------------------------------------------- Word
def extract_text_from_docx(uploaded_file) -> str:
    """Paragraphs and tables of a .docx file, in document order."""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    _rewind(uploaded_file)
    try:
        doc = Document(uploaded_file)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Could not read this Word file (it may be corrupted or password-protected): {e}")

    parts = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            text = Paragraph(child, doc).text.strip()
            if text:
                parts.append(text)
        elif tag == "tbl":
            for row in Table(child, doc).rows:
                cells = []
                for cell in row.cells:
                    ct = cell.text.strip()
                    if ct and (not cells or cells[-1] != ct):  # merged cells repeat
                        cells.append(ct)
                if cells:
                    parts.append(" | ".join(cells))
    return "\n\n".join(parts).strip()


# ----------------------------------------------------------------- PowerPoint
def _shape_texts(shape, out: list):
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        for s in shape.shapes:
            _shape_texts(s, out)
        return
    if getattr(shape, "has_table", False) and shape.has_table:
        for row in shape.table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                out.append(" | ".join(cells))
    elif getattr(shape, "has_text_frame", False) and shape.has_text_frame:
        text = shape.text_frame.text.strip()
        if text:
            out.append(text)


def extract_text_from_pptx(uploaded_file) -> Tuple[str, int]:
    """Return (text, num_slides). Includes tables and speaker notes."""
    from pptx import Presentation

    _rewind(uploaded_file)
    try:
        prs = Presentation(uploaded_file)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Could not read this PowerPoint file (it may be corrupted or password-protected): {e}")

    slides = []
    for i, slide in enumerate(prs.slides, start=1):
        items: list = []
        for shape in slide.shapes:
            _shape_texts(shape, items)
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip() if slide.notes_slide.notes_text_frame else ""
            if notes:
                items.append(f"Speaker notes: {notes}")
        if items:
            slides.append(f"Slide {i}:\n" + "\n".join(items))
    return "\n\n".join(slides).strip(), len(prs.slides)


# ----------------------------------------------------------------- entry point
def extract_text(uploaded_file) -> Tuple[str, int, str]:
    """
    Returns (text, count, unit). unit is "pages", "slides" or "document"
    (Word files have no reliable page count, so count is 0 for them).
    """
    ext = os.path.splitext(getattr(uploaded_file, "name", "") or "")[1].lower().lstrip(".")
    if ext == "pdf":
        text, n = extract_text_from_pdf(uploaded_file)
        return text, n, "pages"
    if ext == "docx":
        return extract_text_from_docx(uploaded_file), 0, "document"
    if ext == "pptx":
        text, n = extract_text_from_pptx(uploaded_file)
        return text, n, "slides"
    raise ValueError("Unsupported file type. Upload a PDF, Word (.docx) or PowerPoint (.pptx) file. "
                     "For older .doc or .ppt files, save them as .docx or .pptx first.")


def estimate_reading_stats(text: str) -> dict:
    words = len(text.split())
    return {"word_count": words, "reading_minutes": max(1, round(words / 200))}