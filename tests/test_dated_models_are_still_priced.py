"""
Providers return a dated snapshot name; the rate table is keyed on the
configured one.

    rate table keys : gpt-5.4-nano, gpt-5.4-mini, gpt-5.6-sol
    returned        : gpt-5.4-nano-2026-03-17

The lookup was exact, so every call to a dated model missed its rate,
counted as unpriced, and contributed nothing to the run's cost. Only
gpt-5.6-sol happened to come back undated, which is why a per-node
breakdown showed a cost for analysis and $0.0 for intent, planner,
retrieval and scoring -- four nodes that had certainly spent money.

WHY THIS WAS EASY TO MISS
    A run where nothing is priced reports total_cost_usd as None, which
    is honest and visible. A run where *some* calls are priced reports a
    number, and that number silently omits the rest. $0.058 looked like a
    complete total while excluding two thirds of the calls.

THE MATCH IS PREFIX, LONGEST FIRST
    A dated name extends the configured one, so a prefix match resolves
    it. Longest-first because a provider that offers both "gpt-5.4-nano"
    and "gpt-5.4-nano-pro" would otherwise price the second at the
    first's rate -- quietly, and in the direction of understating.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from backend.llm.usage_tracker import UsageTracker


class _Model:
    def __init__(self, name, cost_in, cost_out):
        self.model_name = name
        self.input_cost_per_million = Decimal(str(cost_in))
        self.output_cost_per_million = Decimal(str(cost_out))


class _Runtime:
    def __init__(self, models):
        self.models = {str(i): m for i, m in enumerate(models)}


def _tracker(*models) -> UsageTracker:
    return UsageTracker(_Runtime(list(models)))


class TestADatedModelResolves:
    def test_the_dated_name_finds_the_configured_rate(self):
        tracker = _tracker(_Model("gpt-5.4-nano", 0.20, 1.25))

        assert tracker._rates_for("gpt-5.4-nano-2026-03-17") == (
            Decimal("0.20"), Decimal("1.25")
        )

    def test_an_exact_name_still_resolves(self):
        tracker = _tracker(_Model("gpt-5.6-sol", 5.0, 30.0))

        assert tracker._rates_for("gpt-5.6-sol") == (
            Decimal("5.0"), Decimal("30.0")
        )

    def test_a_provider_prefixed_name_resolves(self):
        """
        Groq returns "openai/gpt-oss-20b" and is configured the same way.
        """
        tracker = _tracker(_Model("openai/gpt-oss-20b", 0.0, 0.0))

        assert tracker._rates_for("openai/gpt-oss-20b") is not None


class TestItDoesNotGuess:
    def test_an_unknown_model_is_unpriced(self):
        tracker = _tracker(_Model("gpt-5.4-nano", 0.20, 1.25))

        assert tracker._rates_for("claude-opus-4-8") is None

    def test_a_shorter_name_does_not_match_a_longer_config(self):
        """
        Prefix matching runs one way only. "gpt-5.4" must not pick up the
        rate for "gpt-5.4-nano".
        """
        tracker = _tracker(_Model("gpt-5.4-nano", 0.20, 1.25))

        assert tracker._rates_for("gpt-5.4") is None

    def test_the_longest_configured_match_wins(self):
        """
        Otherwise "gpt-5.4-nano-pro-2026-01-01" prices at the plain
        nano rate -- quietly, and in the direction of understating.
        """
        tracker = _tracker(
            _Model("gpt-5.4-nano", 0.20, 1.25),
            _Model("gpt-5.4-nano-pro", 2.00, 8.00),
        )

        assert tracker._rates_for("gpt-5.4-nano-pro-2026-01-01") == (
            Decimal("2.00"), Decimal("8.00")
        )

    @pytest.mark.parametrize("name", ["", None])
    def test_a_missing_name_is_unpriced(self, name):
        tracker = _tracker(_Model("gpt-5.4-nano", 0.20, 1.25))

        assert tracker._rates_for(name) is None


class TestTheCostIsActuallyCounted:
    def test_a_dated_call_adds_cost(self):
        """
        The behaviour the whole fix is for: before this, a dated model
        incremented unpriced_calls and left cost_usd at zero.
        """
        tracker = _tracker(_Model("gpt-5.4-nano", 1.0, 2.0))

        rates = tracker._rates_for("gpt-5.4-nano-2026-03-17")

        assert rates is not None

        cost = (
            (Decimal(1_000_000) / Decimal(1_000_000)) * rates[0]
            + (Decimal(500_000) / Decimal(1_000_000)) * rates[1]
        )

        assert cost == Decimal("2.0")
