"""
A greeting is not a research question, and the system has to be able to
say so.

Typing "hello" produced a full report: five ranked companies, 52%
confidence, a Reviewed badge. The classifier had actually diagnosed it
correctly and logged the reason —

    [INTENT] Query='hello' intent=SENTIMENT
             reason=User greeted; no financial query provided.

— and then returned SENTIMENT anyway, because the schema offered four
financial intents and no way to decline. The correct answer was produced
and discarded in the same call.

The reviewer now withholds that report rather than presenting it as
reviewed, which is the right terminal but the wrong stage: it costs six
LLM calls and roughly two minutes to decide that "hello" is not a
question. Refusing at the classifier makes it immediate, and lets the
answer say what is actually wrong rather than "the evidence was too thin".

DELIBERATELY NARROW
    A bare company name is in scope — "microsoft" resolved to MSFT and
    produced a reasonable sentiment query. Refusing a real question is a
    worse failure than answering a vague one, so anything naming a
    company, sector, metric or financial topic stays in scope, and an
    unrecognised classification still falls back to MIXED rather than to a
    refusal.
"""
from __future__ import annotations

import inspect

import pytest

from backend.graph import financial_graph
from backend.nodes import intent_node
from backend.nodes.intent_node import (
    OUT_OF_SCOPE,
    build_out_of_scope_report,
)


class TestTheClassifierCanDecline:
    def test_the_schema_offers_the_option(self):
        """
        The model already writes the reason. It needs somewhere to put the
        classification.
        """
        description = intent_node.QueryIntent.model_fields[
            "intent"
        ].description

        assert OUT_OF_SCOPE in description

    def test_the_prompt_names_it(self):
        assert OUT_OF_SCOPE in intent_node.INTENT_SYSTEM_PROMPT

    def test_the_prompt_keeps_a_bare_company_name_in_scope(self):
        """
        "microsoft" is terse, not out of scope. Refusing it would be a
        worse regression than the bug being fixed.
        """
        prompt = intent_node.INTENT_SYSTEM_PROMPT.lower()

        assert "company name" in prompt

    def test_it_is_accepted_by_the_validator(self):
        assert OUT_OF_SCOPE in intent_node._VALID_INTENTS

    def test_an_unrecognised_intent_still_falls_back_to_mixed(self):
        """
        A garbled classification must not become a refusal — that would
        turn a model hiccup into a rejected question.
        """
        source = inspect.getsource(intent_node.classify_intent)

        assert 'intent = "MIXED"' in source


class TestTheGraphStopsThere:
    def test_out_of_scope_routes_to_output(self):
        assert financial_graph.route_after_intent(
            {"intent": OUT_OF_SCOPE}
        ) == "output"

    @pytest.mark.parametrize(
        "intent", ["VALUATION", "GROWTH", "SENTIMENT", "MIXED"]
    )
    def test_every_real_intent_still_reaches_the_planner(self, intent):
        assert financial_graph.route_after_intent(
            {"intent": intent}
        ) == "planner"

    def test_a_missing_intent_reaches_the_planner(self):
        """
        Absent is not the same as refused.
        """
        assert financial_graph.route_after_intent({}) == "planner"

    def test_the_edge_map_has_an_exit(self):
        source = inspect.getsource(financial_graph)

        assert '"output": END' in source


class TestWhatTheReaderIsTold:
    def test_it_carries_no_ranking(self):
        report = build_out_of_scope_report(
            "User greeted; no financial query provided."
        )

        assert report["top_companies"] == []

    def test_it_is_marked_out_of_scope_not_withheld(self):
        """
        Withheld means the pipeline ran and the result was not trusted.
        Nothing ran here, and telling the reader "the evidence was too
        thin" would be the wrong explanation.
        """
        report = build_out_of_scope_report("no financial query provided")

        assert report["out_of_scope"] is True
        assert report.get("withheld") is not True

    def test_the_notice_says_what_to_do_instead(self):
        report = build_out_of_scope_report("no financial query provided")

        notice = report["review"]["notice"].lower()

        assert "research question" in notice
        assert any(
            word in notice for word in ("company", "sector", "metric")
        ), "a refusal that does not say what works is not useful"

    def test_the_classifier_reason_is_carried(self):
        """
        The model's own diagnosis is the most specific thing available and
        was previously thrown away.
        """
        report = build_out_of_scope_report(
            "User greeted; no financial query provided."
        )

        assert "greeted" in report["review"]["reason"]
