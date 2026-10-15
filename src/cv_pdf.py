"""Read a candidate CV PDF and keep the file next to the event store.

The event stores the extracted text only. The PDF bytes stay in data/cvs.
"""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CV_DIR = PROJECT_ROOT / "data" / "cvs"
MAX_PDF_BYTES = 5 * 1024 * 1024
_APPLICATION_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class PdfError(ValueError):
    """The upload cannot be used as a CV. No event should be written."""


def extract_pdf_text(upload) -> tuple[str, bytes]:
    """Return the readable text and the original bytes. Reject anything else."""
    if upload is None or not getattr(upload, "filename", ""):
        raise PdfError("A CV PDF is required.")
    if not str(upload.filename).lower().endswith(".pdf"):
        raise PdfError("The CV must be a PDF file.")
    data = upload.read()
    if not data:
        raise PdfError("A CV PDF is required.")
    if len(data) > MAX_PDF_BYTES:
        raise PdfError("The CV PDF must be 5 MB or smaller.")
    if not data.startswith(b"%PDF"):
        raise PdfError("The CV must be a PDF file.")
    text = _text_from_pdf(data)
    if not text.strip():
        raise PdfError("This PDF has no readable text.")
    return text, data


def save_pdf(application_id: str, data: bytes) -> Path:
    path = cv_pdf_path(application_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def cv_pdf_path(application_id: str) -> Path:
    if not _APPLICATION_ID.match(application_id or ""):
        raise PdfError("Unknown application.")
    return CV_DIR / f"{application_id}.pdf"


def cv_pdf_exists(application_id: str) -> bool:
    try:
        return cv_pdf_path(application_id).is_file()
    except PdfError:
        return False


def _text_from_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(BytesIO(data))
    except PdfReadError as exc:
        raise PdfError("The CV must be a PDF file.") from exc
    parts = [page.extract_text() or "" for page in reader.pages]
    return readable_cv_text("\n".join(part.strip() for part in parts if part and part.strip()))


def readable_cv_text(text: str) -> str:
    """Join a PDF that put every word on its own line. Leave normal paragraphs alone."""
    lines = [line.strip() for line in str(text or "").splitlines()]
    content = [line for line in lines if line]
    if not content:
        return ""
    short = sum(1 for line in content if len(line.split()) <= 2)
    if len(content) >= 4 and short / len(content) >= 0.6:
        return " ".join(content)
    return "\n".join(content)
