"""
Turning an uploaded PDF into text worth indexing.

A PDF dropped in the raw bucket by hand is the one document in this
corpus that arrives as bytes rather than as JSON a fetcher wrote, so
every assumption the rest of the pipeline makes about content -- that it
exists, and that it is text -- has to be established here.

Docling does the parsing: it runs a layout model over the rendered page
rather than dumping the text objects in file order, which is what makes a
two-column filing come out in reading order instead of interleaved.

Tested against real PDF files in tests/fixtures, generated once and
committed. An earlier version of these tests built PDFs byte by byte at
run time; Docling silently dropped a page of that synthetic file, because
a layout model needs a page that renders like a real document. A stub
would have hidden the same problem.
"""
from pathlib import Path

import pytest


FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class TestExtractingText:
    def test_the_text_of_a_filing_is_read(self):
        from backend.ingestion.extract import extract_text

        text = extract_text(_fixture("filing_with_text_layer.pdf"))

        assert "revenue above consensus" in text

    def test_every_page_contributes_its_text(self):
        """
        A 10-K is not one page, and dropping all but the first would index
        a document that looks complete and answers nothing.
        """
        from backend.ingestion.extract import extract_text

        text = extract_text(_fixture("filing_with_text_layer.pdf"))

        assert "Item 1. Business" in text
        assert "Gross margin expanded" in text

    def test_a_scanned_filing_is_read_by_ocr(self):
        """
        The reason for Docling over a text-object dump. This fixture has no
        text layer at all -- it is a rendered image of a page -- and a
        plain extractor returns an empty string for it.

        OCR is left on for exactly this case. It costs nothing on a
        document that already has a text layer, because it only runs where
        there is no text to find.
        """
        from backend.ingestion.extract import extract_text

        text = extract_text(_fixture("filing_scanned_no_text_layer.pdf"))

        # OCR is imperfect on spacing -- the title comes back with its
        # spaces dropped -- so this asserts on body text, not fidelity.
        assert "revenue above consensus" in text.lower()

    def test_bytes_that_are_not_a_pdf_raise(self):
        """
        Anything uploaded with a .pdf suffix reaches this code. Returning
        empty text would look identical to a page with nothing on it and
        be skipped without anyone noticing.
        """
        from backend.ingestion.extract import UnreadableDocument, extract_text

        with pytest.raises(UnreadableDocument):
            extract_text(b"this is not a PDF at all")

    def test_a_password_protected_filing_raises(self):
        """
        A protected upload is a mistake worth seeing, not a document with
        no content. There is nowhere to ask a queue worker for a password.
        """
        from backend.ingestion.extract import UnreadableDocument, extract_text

        with pytest.raises(UnreadableDocument):
            extract_text(_fixture("filing_password_protected.pdf"))


class TestTheConverterIsReused:
    def test_the_same_converter_is_handed_back(self):
        """
        Building it loads the layout and OCR models: 3.6s the first time,
        0.3s per document afterwards. Constructing one per message would
        spend an order of magnitude more time on setup than on parsing.
        """
        from backend.ingestion.extract import _converter

        assert _converter() is _converter()
