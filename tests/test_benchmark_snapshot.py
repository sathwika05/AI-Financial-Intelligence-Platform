"""
The frozen benchmark snapshot.

A benchmark run against live data cannot be interpreted: a score that moves
might mean the code changed or that Yahoo repriced a stock overnight. These
tests cover the round trip that makes the data constant, with particular
attention to the two things that silently corrupt a restore — embeddings,
which do not survive JSON on their own, and identity sequences, which are
left pointing at 1 when ids are inserted explicitly.

The round-trip tests do truncate and reload the four benchmark tables. They
take their own snapshot of the current database first and restore exactly
that, so the net effect is nil, and `restore` runs inside a single
transaction so a failure rolls back rather than leaving the tables empty.
"""
import json

import pytest
from sqlalchemy import text

from backend.services.postgres_service import engine
from seeds.snapshot import (
    TABLES,
    VECTOR_COLUMNS,
    _insert_statement,
    _select_clause,
    create,
    restore,
    verify,
)


@pytest.fixture
async def live_snapshot(tmp_path):
    """
    A snapshot of whatever is currently in the database.

    Restoring this is a no-op in effect, which is what makes it safe to
    exercise the destructive path against a real database.
    """
    path = tmp_path / "live.json"
    await create(path)
    return path


async def fingerprint() -> str:
    """A checksum over ids, foreign keys and embeddings."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT md5(string_agg(x, '|' ORDER BY x)) FROM (
                  SELECT id||ticker||coalesce(market_cap::text,'') AS x
                    FROM companies
                  UNION ALL
                  SELECT id||coalesce(company_id::text,'')||coalesce(content_hash,'')
                    FROM documents
                  UNION ALL
                  SELECT id||coalesce(document_id::text,'')||coalesce(embedding::text,'')
                    FROM document_chunks
                ) s
                """
            )
        )
        return result.scalar_one()


# ---------------------------------------------------------------------------
# Statement construction — no database needed
# ---------------------------------------------------------------------------


class TestStatementConstruction:
    def test_vectors_are_read_as_text(self):
        """
        pgvector will not serialise to JSON on its own. Reading it as text
        gives the same literal form the CAST on write accepts.
        """
        clause = _select_clause("document_chunks")
        assert "embedding::text AS embedding" in clause

    def test_ordinary_columns_are_not_cast(self):
        clause = _select_clause("companies")
        assert "::text" not in clause

    def test_vectors_are_cast_back_on_insert(self):
        statement = _insert_statement("document_chunks")
        assert "CAST(:embedding AS vector)" in statement

    def test_insert_covers_every_captured_column(self):
        for table, columns in TABLES.items():
            statement = _insert_statement(table)
            for column in columns:
                assert column in statement, f"{table}.{column} missing"

    def test_primary_keys_are_captured(self):
        """
        documents.company_id and document_chunks.document_id are foreign
        keys, so ids must survive the round trip or the references break.
        """
        for table, columns in TABLES.items():
            assert "id" in columns, f"{table} would lose its primary key"

    def test_tables_are_ordered_parent_first(self):
        """Restore inserts in this order and must not violate a foreign key."""
        order = list(TABLES)
        assert order.index("companies") < order.index("financial_metrics")
        assert order.index("companies") < order.index("documents")
        assert order.index("documents") < order.index("document_chunks")

    def test_embedding_is_the_only_vector_column(self):
        assert VECTOR_COLUMNS == {"embedding"}


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


class TestCreate:
    async def test_writes_every_table(self, tmp_path):
        path = tmp_path / "snap.json"
        counts = await create(path)

        assert set(counts) == set(TABLES)
        assert path.exists()

    async def test_counts_match_the_database(self, tmp_path):
        path = tmp_path / "snap.json"
        counts = await create(path)

        async with engine.connect() as conn:
            for table, count in counts.items():
                result = await conn.execute(
                    text(f"SELECT count(*) FROM {table}")
                )
                assert result.scalar_one() == count

    async def test_embeddings_are_captured_not_dropped(self, tmp_path):
        """
        Without the embedding a restore would need to call the embedding
        API, which costs money and reintroduces a moving part.
        """
        path = tmp_path / "snap.json"
        await create(path)

        chunks = json.loads(path.read_text())["document_chunks"]

        assert chunks, "no chunks captured"
        assert all(c["embedding"] for c in chunks)
        # Stored as the pgvector literal, e.g. "[0.1,0.2,...]".
        assert chunks[0]["embedding"].startswith("[")

    async def test_snapshot_is_valid_json(self, tmp_path):
        path = tmp_path / "snap.json"
        await create(path)
        json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    async def test_restore_reproduces_the_data_exactly(self, live_snapshot):
        before = await fingerprint()
        await restore(live_snapshot)
        after = await fingerprint()

        assert after == before, "restore did not reproduce the data"

    async def test_embeddings_survive_the_round_trip(self, live_snapshot):
        """
        Covered by the fingerprint too, but asserted alone because a
        corrupted vector would still restore without error and only show up
        later as vector search returning different chunks.
        """
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT embedding::text FROM document_chunks "
                    "ORDER BY id LIMIT 1"
                )
            )
            before = result.scalar_one()

        await restore(live_snapshot)

        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT embedding::text FROM document_chunks "
                    "ORDER BY id LIMIT 1"
                )
            )
            assert result.scalar_one() == before

    async def test_sequences_are_reset_so_new_inserts_do_not_collide(
        self, live_snapshot
    ):
        """
        TRUNCATE ... RESTART IDENTITY leaves the sequence at 1, and the ids
        are then inserted explicitly, so without setval the next insert
        collides with a restored row.
        """
        await restore(live_snapshot)

        async with engine.begin() as conn:
            for table in TABLES:
                result = await conn.execute(
                    text(
                        f"SELECT last_value >= coalesce((SELECT max(id) FROM {table}), 0) "
                        f"FROM {table}_id_seq"
                    )
                )
                assert result.scalar_one(), f"{table} sequence is behind max(id)"

    async def test_foreign_keys_still_resolve(self, live_snapshot):
        await restore(live_snapshot)

        async with engine.connect() as conn:
            orphan_docs = await conn.execute(
                text(
                    "SELECT count(*) FROM documents d "
                    "LEFT JOIN companies c ON c.id = d.company_id "
                    "WHERE d.company_id IS NOT NULL AND c.id IS NULL"
                )
            )
            assert orphan_docs.scalar_one() == 0

            orphan_chunks = await conn.execute(
                text(
                    "SELECT count(*) FROM document_chunks dc "
                    "LEFT JOIN documents d ON d.id = dc.document_id "
                    "WHERE d.id IS NULL"
                )
            )
            assert orphan_chunks.scalar_one() == 0

    async def test_restore_is_idempotent(self, live_snapshot):
        await restore(live_snapshot)
        once = await fingerprint()

        await restore(live_snapshot)
        twice = await fingerprint()

        assert once == twice


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------


class TestVerify:
    async def test_reports_a_match(self, live_snapshot):
        await restore(live_snapshot)
        report = await verify(live_snapshot)

        for table, numbers in report.items():
            assert numbers["database"] == numbers["snapshot"], table

    async def test_detects_drift(self, live_snapshot):
        """
        The check that stops a benchmark being run against data that has
        moved since the snapshot was taken.
        """
        payload = json.loads(live_snapshot.read_text())
        payload["companies"] = payload["companies"][:-1]
        live_snapshot.write_text(json.dumps(payload))

        report = await verify(live_snapshot)

        assert report["companies"]["database"] != report["companies"]["snapshot"]

    async def test_missing_snapshot_is_a_clear_error(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            await verify(tmp_path / "does-not-exist.json")

    async def test_restore_without_a_snapshot_is_a_clear_error(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            await restore(tmp_path / "does-not-exist.json")
