"""
Text out of an uploaded document, via Docling.

A filing that arrives as bytes -- an uploaded PDF, an EDGAR HTML
document -- is not JSON a fetcher wrote, so the assumptions the rest
of the pipeline makes about content -- that it exists, and that it is
text -- have to be established here rather than inherited.

Docling rather than a text-object dump, because a filing is a laid-out
document and not a stream of strings. It runs a layout model over the
rendered page, so a two-column page comes out in reading order and a
table comes out as a table, and it falls back to OCR -- optical character
recognition, reading the words out of a picture of a page -- when a page
has no text layer at all -- which is what a scanned filing is, and what a plain
extractor returns nothing for.

The output is Markdown. That is Docling's structural export, and it is
what lets the chunker split on a document's real section headings
instead of on character count alone.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any


logger = logging.getLogger(__name__)


class UnreadableDocument(Exception):
    """The bytes could not be opened as a document."""


@lru_cache(maxsize=1)
def _converter() -> Any:
    """
    One converter, reused for the life of the worker.

    Building it loads the layout and OCR models: measured at 3.6s the
    first time and 0.3s per document afterwards. Constructing one per
    message would spend an order of magnitude more time on setup than on
    parsing.

    OCR is left at its default of on. It costs nothing measurable on a
    document that already has a text layer -- it only runs where there is
    no text to find -- and it is the whole reason a scanned filing is
    readable at all.
    """
    from docling.document_converter import DocumentConverter

    return DocumentConverter()


def extract_text(raw: bytes, *, filename: str = "document.pdf") -> str:
    """
    A PDF's text as Markdown, in reading order.

    Raises UnreadableDocument for bytes that are not a readable PDF, including
    a password-protected one: there is nowhere to ask a queue worker for
    a password, and a protected upload is a mistake worth seeing rather
    than a document with no content.

    Returns an empty string only for a PDF that genuinely has nothing on
    its pages. The caller turns that into a skip.
    """
    import io

    from docling.datamodel.base_models import DocumentStream
    from docling.exceptions import ConversionError

    # Docling picks its backend from the name, so the suffix has to survive
    # even though the bytes came from S3 rather than a filesystem.
    source = DocumentStream(name=filename, stream=io.BytesIO(raw))

    try:
        result = _converter().convert(source)
    except ConversionError as exc:
        raise UnreadableDocument(f"Could not read {filename}: {exc}") from exc

    return result.document.export_to_markdown().strip()
