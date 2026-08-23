"""
A scratch set for iterating on specific questions.

A full sentiment or mixed run is hours. When a run surfaces a handful of
broken questions, the fix needs a loop measured in minutes, against exactly
those questions — the same reason "smoke" exists, but chosen per
investigation rather than fixed.
"""
import importlib

import pytest


@pytest.fixture
def question_sets(monkeypatch):
    """Reimport the package so FOCUS_QUESTIONS is read fresh."""

    def _load(value):
        if value is None:
            monkeypatch.delenv("FOCUS_QUESTIONS", raising=False)
        else:
            monkeypatch.setenv("FOCUS_QUESTIONS", value)

        import backend.evaluation.datasets.question_sets as module

        return importlib.reload(module)

    yield _load

    monkeypatch.delenv("FOCUS_QUESTIONS", raising=False)
    import backend.evaluation.datasets.question_sets as module

    importlib.reload(module)


class TestFocusSet:
    def test_names_the_questions_it_is_given(self, question_sets):
        module = question_sets("sentiment_003,mixed_002")

        assert [q.question_id for q in module.QUESTION_SETS["focus"]] == [
            "sentiment_003",
            "mixed_002",
        ]

    def test_is_empty_when_unset(self, question_sets):
        module = question_sets(None)

        assert module.QUESTION_SETS["focus"] == []

    def test_ignores_whitespace_and_blanks(self, question_sets):
        module = question_sets(" sentiment_003 , , mixed_002 ")

        assert len(module.QUESTION_SETS["focus"]) == 2

    def test_an_unknown_id_is_skipped_rather_than_guessed(self, question_sets):
        module = question_sets("sentiment_003,not_a_question")

        assert [q.question_id for q in module.QUESTION_SETS["focus"]] == [
            "sentiment_003"
        ]

    def test_the_hundred_is_unaffected(self, question_sets):
        module = question_sets("sentiment_003")

        assert len(module.QUESTION_SETS["all"]) == 100
        assert len(module.QUESTION_SETS["smoke"]) == 4

    def test_the_endpoint_accepts_it(self):
        import typing

        from backend.api.evaluation_routes import RunRequest

        allowed = typing.get_args(
            RunRequest.model_fields["question_set"].annotation
        )

        assert "focus" in allowed
