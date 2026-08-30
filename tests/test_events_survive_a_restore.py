"""
The processing log outlives the documents it describes.

It records that a file was attempted. That an attempt happened is a fact
about the past, and no later change to the corpus makes it untrue -- a
document being deleted, or the whole corpus being replaced from a
snapshot, does not unmake the upload that failed last Tuesday.

This is a regression test with a specific cause. document_id originally
carried a foreign key to documents, and seeds/snapshot.py restores with
TRUNCATE ... CASCADE, so restoring the benchmark corpus silently emptied
the log -- as did running the test suite, which exercises restore.
"""
import pytest
from sqlalchemy import text

from backend.services.postgres_service import engine


class TestTheLogIsNotCollateral:
    @pytest.mark.asyncio
    async def test_nothing_ties_it_to_the_documents_table(self):
        """
        Asserted on the schema rather than by running a restore, because
        proving it the other way means truncating the corpus.
        """
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid = 'ingestion_events'::regclass
                      AND contype = 'f'
                    """
                )
            )

            foreign_keys = [row[0] for row in result]

        assert foreign_keys == [], (
            "ingestion_events has a foreign key again; a TRUNCATE CASCADE "
            f"on the referenced table will empty the log: {foreign_keys}"
        )

    @pytest.mark.asyncio
    async def test_the_document_id_column_is_still_there(self):
        """
        Dropping the constraint, not the column. The id is still how a row
        is matched to the document it produced -- it is simply recorded
        rather than enforced.
        """
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'ingestion_events'
                      AND column_name = 'document_id'
                    """
                )
            )

            assert result.scalar_one_or_none() == "document_id"
