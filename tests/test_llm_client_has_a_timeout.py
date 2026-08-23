"""
A hung provider call must fail the question, not the run.

Run dbba921f stalled for three and a half hours on one question. Every call
returned 200 and there were no rate-limit errors — a handful simply hung,
the longest for 84 minutes, against a median gap of 11 seconds. With no
timeout the run had no way to give up, so 15 questions never ran and the
process had to be killed by hand.

A timeout converts that into a failed question the runner records and moves
past. The benchmark already tolerates a question erroring; it cannot
tolerate one never returning.
"""
import inspect

from backend.llm import llm_factory


class TestTheClientCannotHangForever:
    def test_a_timeout_is_configured(self):
        src = inspect.getsource(llm_factory.create_llm_client)

        assert "timeout" in src

    def test_the_timeout_is_passed_to_the_model(self):
        src = inspect.getsource(llm_factory.create_llm_client)

        assert "timeout=" in src

    def test_it_is_long_enough_for_a_real_analysis_call(self):
        """
        The analysis node legitimately takes 15-36s, and the reviewer's
        judges longer. A timeout under a minute would fail healthy work.
        """
        assert llm_factory.REQUEST_TIMEOUT_SECONDS >= 120

    def test_it_is_short_enough_to_catch_a_hang(self):
        """The shortest hang observed in dbba921f was 16 minutes."""
        assert llm_factory.REQUEST_TIMEOUT_SECONDS <= 600

    def test_retries_are_bounded(self):
        """
        A timeout that is retried without limit is not a timeout. The SDK
        default is 2; this pins it so the ceiling stays predictable.
        """
        src = inspect.getsource(llm_factory.create_llm_client)

        assert "max_retries" in src
