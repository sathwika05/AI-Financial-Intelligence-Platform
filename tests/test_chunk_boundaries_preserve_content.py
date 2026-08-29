"""
A chunk must say what the document said.

The chunker used to strip leading periods and whitespace from every
chunk, to clean an artefact of the sentence separator. Measured against
the whole corpus it never once fired on real prose -- and meanwhile it
silently rewrote any chunk that legitimately began with a period.

In a corpus of financial filings that is not cosmetic: a leading decimal
is a number, and dropping it changes the number.
"""
from backend.ingestion.chunking import chunk_text


class TestLeadingCharactersAreContent:
    def test_a_leading_decimal_survives(self):
        """'.75 percent' and '75 percent' differ by two orders of magnitude."""
        assert chunk_text(".75 percent of revenue")[0].startswith(".75")

    def test_a_leading_ellipsis_survives(self):
        assert chunk_text("...continued from the prior page")[0].startswith("...")

    def test_a_leading_dotted_name_survives(self):
        assert ".NET" in chunk_text(".NET revenue grew this year.")[0]


class TestWhatTheStripWasFor:
    def test_chunks_still_have_no_surrounding_whitespace(self):
        """
        The guard that mattered stays: a chunk padded with whitespace
        wastes embedding budget and reads badly as evidence.
        """
        chunks = chunk_text("  First paragraph.  \n\n  Second paragraph.  ")

        for chunk in chunks:
            assert chunk == chunk.strip()

    def test_empty_chunks_are_still_dropped(self):
        assert chunk_text("Real text.\n\n\n\n   \n\nMore text.") == [
            c for c in chunk_text("Real text.\n\n\n\n   \n\nMore text.") if c.strip()
        ]
        assert all(c.strip() for c in chunk_text("A.\n\n\n\n   \n\nB."))
