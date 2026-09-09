"""
"What does a query cost?" is answerable. "Which stage costs it?" was not.

UsageTracker keeps run totals -- 14 calls, 14,767 in, 3,240 out, $0.079 --
and nothing finer. model_costs has a node_name column and has never had a
writer, so the breakdown the table was designed for did not exist.

Totals hide where the money is. Measured on one query: two LARGE-tier
calls account for 5.5k of the 18k tokens, and the analysis call alone
produces 1,971 output tokens -- 61% of all output. A run total cannot
show that, and it is the number that decides what to optimise.

WHY THE TIMING DECORATOR
    timed_node already wraps every graph node and already merges one
    node_timings entry per execution. The tracker is a callback on the
    same config, so its counters can be read either side of the node and
    the delta is that node's usage. No new plumbing, and no dependence on
    LangChain callback internals -- on_llm_end receives only run_id,
    parent_run_id and tags, with no node name anywhere in it.

WHAT THIS ASSUMES
    That graph nodes run one at a time. They do: the parallel fan-out to
    SQL, vector and market happens inside the retrieval node, not between
    nodes. If nodes were ever run concurrently the deltas would interleave
    and attribute to the wrong stage, so this is written down rather than
    assumed silently.
"""
from __future__ import annotations

import pytest

from backend.observability.tracing import usage_snapshot, usage_delta


class _Tracker:
    """Stands in for UsageTracker; only the counters matter."""

    def __init__(self, tokens_in=0, tokens_out=0, cost=0.0, calls=0):
        self.input_tokens = tokens_in
        self.output_tokens = tokens_out
        self.cost_usd = cost
        self.call_count = calls


class TestFindingTheTracker:
    def test_it_is_found_among_the_callbacks(self):
        tracker = _Tracker(tokens_in=10)

        assert usage_snapshot({"callbacks": [tracker]})["tokens_in"] == 10

    def test_other_callbacks_are_ignored(self):
        tracker = _Tracker(tokens_in=7)

        snapshot = usage_snapshot(
            {"callbacks": [object(), tracker, object()]}
        )

        assert snapshot["tokens_in"] == 7

    def test_a_callback_manager_is_unwrapped(self):
        """
        `callbacks` is a list when the config is built and an
        AsyncCallbackManager by the time LangGraph invokes a node. The
        manager is not iterable, and missing this raised inside every
        node on the first real run.
        """
        tracker = _Tracker(tokens_in=42)

        class _Manager:
            handlers = [tracker]

        assert usage_snapshot(
            {"callbacks": _Manager()}
        )["tokens_in"] == 42

    def test_an_empty_manager_snapshots_nothing(self):
        class _Manager:
            handlers = []

        assert usage_snapshot({"callbacks": _Manager()}) is None

    @pytest.mark.parametrize(
        "config", [None, {}, {"callbacks": []}, {"callbacks": [object()]}],
        ids=["none", "empty", "no callbacks", "no tracker"],
    )
    def test_no_tracker_snapshots_nothing(self, config):
        """
        The benchmark runs with a tracker; a bare unit test may not. A
        missing tracker must not raise inside a node wrapper.
        """
        assert usage_snapshot(config) is None


class TestTheDelta:
    def test_it_is_what_the_node_spent(self):
        before = {"tokens_in": 100, "tokens_out": 20, "cost": 0.001, "calls": 1}
        after = {"tokens_in": 380, "tokens_out": 95, "cost": 0.004, "calls": 3}

        delta = usage_delta(before, after)

        assert delta["tokens_in"] == 280
        assert delta["tokens_out"] == 75
        assert delta["calls"] == 2
        assert delta["cost_usd"] == pytest.approx(0.003)

    def test_a_node_that_called_nothing_reports_zero(self):
        """
        Scoring and output nodes make no provider call. A zero row is
        meaningful -- it says the stage is free -- so it is not dropped.
        """
        same = {"tokens_in": 100, "tokens_out": 20, "cost": 0.001, "calls": 1}

        delta = usage_delta(same, same)

        assert delta == {
            "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "calls": 0
        }

    @pytest.mark.parametrize(
        "before,after",
        [(None, {"tokens_in": 1}), ({"tokens_in": 1}, None), (None, None)],
        ids=["no before", "no after", "neither"],
    )
    def test_a_missing_snapshot_yields_nothing(self, before, after):
        assert usage_delta(before, after) is None

    def test_counters_never_go_backwards(self):
        """
        Defensive: the tracker only accumulates. If a delta ever came out
        negative something is wrong, and a negative cost in a report is
        worse than a zero.
        """
        before = {"tokens_in": 500, "tokens_out": 90, "cost": 0.01, "calls": 4}
        after = {"tokens_in": 100, "tokens_out": 10, "cost": 0.001, "calls": 1}

        delta = usage_delta(before, after)

        assert delta["tokens_in"] == 0
        assert delta["cost_usd"] == 0.0


class TestTheTimingEntryCarriesIt:
    async def test_a_node_records_what_it_spent(self):
        from backend.observability.tracing import timed_node

        tracker = _Tracker(tokens_in=100, tokens_out=20, cost=0.001, calls=1)

        async def node(state, config):
            tracker.input_tokens = 400
            tracker.output_tokens = 90
            tracker.cost_usd = 0.005
            tracker.call_count = 3
            return {"ok": True}

        result = await timed_node("analysis", node)(
            {}, {"callbacks": [tracker]}
        )

        entry = result["node_timings"][0]

        assert entry["node"] == "analysis"
        assert entry["tokens_in"] == 300
        assert entry["tokens_out"] == 70
        assert entry["calls"] == 2

    async def test_latency_is_still_recorded(self):
        """
        The addition must not disturb what the entry already carried.
        """
        from backend.observability.tracing import timed_node

        async def node(state, config):
            return {"ok": True}

        result = await timed_node("intent", node)({}, {})

        entry = result["node_timings"][0]

        assert entry["node"] == "intent"
        assert "latency_ms" in entry

    async def test_a_node_without_a_tracker_still_times(self):
        from backend.observability.tracing import timed_node

        async def node(state, config):
            return {"ok": True}

        result = await timed_node("intent", node)({}, {})

        assert "tokens_in" not in result["node_timings"][0]
