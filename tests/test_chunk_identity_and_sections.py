"""
What a chunk knows about itself.

Two additions, for two different jobs.

A deterministic id, so re-indexing a document can be compared with what
was there before. Today the only identity a chunk has is an
autoincrementing primary key, which changes on every reindex, so nothing
can answer "did this document's chunks actually change?" -- and that is
the question a consistency check has to ask.

A section, so a chunk knows where in a filing it came from. Docling
recovers a filing's headings; the chunker threw them away, leaving a
passage about margins with nothing to say it came from Item 7.
"""
from backend.ingestion.chunking import chunk_text, chunk_uid, chunk_with_sections


class TestDeterministicChunkIds:
    def test_the_same_chunk_gets_the_same_id_every_time(self):
        first = chunk_uid(document_id=7, chunk_index=0, content="Revenue rose.")
        second = chunk_uid(document_id=7, chunk_index=0, content="Revenue rose.")

        assert first == second

    def test_different_content_gets_a_different_id(self):
        assert chunk_uid(
            document_id=7, chunk_index=0, content="Revenue rose."
        ) != chunk_uid(document_id=7, chunk_index=0, content="Revenue fell.")

    def test_the_same_text_in_two_documents_gets_different_ids(self):
        """
        Boilerplate repeats across filings. Two documents sharing a
        sentence must not share a chunk identity, or one document's
        reindex would appear to change the other's.
        """
        assert chunk_uid(
            document_id=7, chunk_index=0, content="See accompanying notes."
        ) != chunk_uid(
            document_id=8, chunk_index=0, content="See accompanying notes."
        )

    def test_position_is_part_of_the_identity(self):
        assert chunk_uid(
            document_id=7, chunk_index=0, content="Revenue rose."
        ) != chunk_uid(document_id=7, chunk_index=1, content="Revenue rose.")

    def test_the_id_fits_the_column(self):
        uid = chunk_uid(document_id=7, chunk_index=0, content="Revenue rose.")

        assert len(uid) == 64


class TestSections:
    def test_a_chunk_carries_the_heading_it_falls_under(self):
        chunks = chunk_with_sections(
            "# Item 7. Management's Discussion\n\nGross margin expanded."
        )

        assert chunks[0].section == "Item 7. Management's Discussion"
        assert "Gross margin expanded." in chunks[0].content

    def test_text_before_any_heading_has_no_section(self):
        chunks = chunk_with_sections("A cover page.\n\n# Item 1. Business\n\nWe design.")

        assert chunks[0].section is None

    def test_a_later_heading_replaces_an_earlier_one(self):
        chunks = chunk_with_sections(
            "# Item 1. Business\n\nWe design phones.\n\n"
            "# Item 7. Discussion\n\nGross margin expanded."
        )

        sections = {c.section for c in chunks}

        assert "Item 1. Business" in sections
        assert "Item 7. Discussion" in sections

    def test_a_document_with_no_headings_still_chunks(self):
        """
        Every news article in the corpus is this case. Sections are an
        addition for filings, not a requirement.
        """
        text = "Apple reported revenue above consensus for the quarter."

        chunks = chunk_with_sections(text)

        assert [c.content for c in chunks] == chunk_text(text)
        assert all(c.section is None for c in chunks)

    def test_the_heading_line_is_not_repeated_as_content(self):
        """
        The heading is metadata now. Leaving it in the body as well spends
        embedding budget twice on the same words.
        """
        chunks = chunk_with_sections("# Item 1. Business\n\nWe design phones.")

        assert not chunks[0].content.lstrip().startswith("#")

    def test_empty_input_yields_nothing(self):
        assert chunk_with_sections("") == []
