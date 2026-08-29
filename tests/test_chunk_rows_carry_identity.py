"""
What actually gets written to document_chunks.

The insert used to carry position, text and a vector. It now also carries
the chunk's stable identity and the section it came from, and those have
to be right at the point of writing -- a null uid is indistinguishable
from a chunk that predates the column.
"""
from backend.ingestion.indexing_service import chunk_rows
from backend.ingestion.chunking import SectionChunk, chunk_uid


class TestRowsWrittenForADocument:
    def test_each_row_carries_its_position_and_text(self):
        rows = chunk_rows(
            document_id=7,
            chunks=[
                SectionChunk("Revenue rose.", None),
                SectionChunk("Margin fell.", None),
            ],
            vectors=[[0.1], [0.2]],
        )

        assert [r["chunk_index"] for r in rows] == [0, 1]
        assert [r["content"] for r in rows] == ["Revenue rose.", "Margin fell."]

    def test_each_row_carries_the_identity_it_will_be_compared_by(self):
        rows = chunk_rows(
            document_id=7,
            chunks=[SectionChunk("Revenue rose.", None)],
            vectors=[[0.1]],
        )

        assert rows[0]["chunk_uid"] == chunk_uid(
            document_id=7, chunk_index=0, content="Revenue rose."
        )

    def test_the_section_travels_to_the_row(self):
        rows = chunk_rows(
            document_id=7,
            chunks=[SectionChunk("Gross margin expanded.", "Item 7. Discussion")],
            vectors=[[0.1]],
        )

        assert rows[0]["section"] == "Item 7. Discussion"

    def test_reindexing_unchanged_content_reproduces_the_same_ids(self):
        """
        The whole point of the identity: run it twice, get the same uids,
        so a consistency check can tell a real change from a reindex.
        """
        chunks = [SectionChunk("Revenue rose.", "Item 7")]

        first = chunk_rows(document_id=7, chunks=chunks, vectors=[[0.1]])
        second = chunk_rows(document_id=7, chunks=chunks, vectors=[[0.9]])

        assert first[0]["chunk_uid"] == second[0]["chunk_uid"]

    def test_the_vector_is_formatted_for_pgvector(self):
        rows = chunk_rows(
            document_id=7,
            chunks=[SectionChunk("Revenue rose.", None)],
            vectors=[[0.1, 0.2]],
        )

        assert rows[0]["embedding"] == "[0.1,0.2]"
