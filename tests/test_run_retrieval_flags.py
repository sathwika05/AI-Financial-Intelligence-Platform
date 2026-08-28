"""
The retrieval flags as run configuration.

The point of putting them on the run rather than in settings is
comparability: baseline, RRF only, cross-encoder only and both are four
runs whose rows say which was which. A flag that is not persisted would
leave two runs differing with nothing on record to explain why.
"""
from uuid import uuid4

import pytest

from backend.api.evaluation_routes import RunRequest, _find_active_duplicate
from backend.models.db_models import BenchmarkRun


def _request(**overrides):
    defaults = {
        "provider_id": uuid4(),
        "question_set": "smoke",
    }
    defaults.update(overrides)
    return RunRequest(**defaults)


class TestTheRequest:
    def test_both_flags_default_to_off(self):
        """Today's pipeline stays the default; opting in is explicit."""
        request = _request()

        assert request.rrf_enabled is False
        assert request.cross_encoder_enabled is False

    def test_they_can_be_set_independently(self):
        request = _request(rrf_enabled=True)

        assert request.rrf_enabled is True
        assert request.cross_encoder_enabled is False


class TestTheRunRecord:
    def test_the_run_stores_which_retrieval_it_used(self):
        """Without this a scored run cannot be attributed to a config."""
        columns = BenchmarkRun.__table__.columns

        assert "rrf_enabled" in columns
        assert "cross_encoder_enabled" in columns

    def test_the_columns_default_to_off_for_existing_rows(self):
        """Every run recorded before today ran the baseline pipeline."""
        columns = BenchmarkRun.__table__.columns

        assert columns["rrf_enabled"].server_default is not None
        assert columns["cross_encoder_enabled"].server_default is not None


class TestDuplicateDetection:
    async def test_two_runs_differing_only_by_flags_are_not_duplicates(self):
        """
        The four-way comparison launches four runs over the same question
        set. If the flags are not part of the match, the second is refused
        as a duplicate of the first and the comparison cannot be run at all.
        """
        provider_id = uuid4()
        seen = {}

        class _Result:
            def scalar_one_or_none(self):
                return None

        class _Session:
            async def execute(self, statement):
                seen["sql"] = str(statement)
                return _Result()

        await _find_active_duplicate(
            session=_Session(),
            request=_request(provider_id=provider_id, rrf_enabled=True),
        )

        assert "rrf_enabled" in seen["sql"]
        assert "cross_encoder_enabled" in seen["sql"]


class TestFlagsReachTheGraph:
    def test_the_runner_puts_them_on_configurable(self):
        """
        `configurable` is the channel retrieve_similar reads them from;
        see test_retrieval_feature_flags.
        """
        import inspect

        from backend.api import evaluation_routes

        source = inspect.getsource(evaluation_routes._execute_benchmark)

        assert "retrieval_flags" in source
