"""
Keyword generation asks Groq's small tier for structured output, and the
schema it sends is what decides whether that works.

    class RankingKeywords(BaseModel):
        keywords: List[str]

No docstring, no field description. The JSON schema Groq receives is an
untitled array of untitled strings, and the model returns the list as
message content instead of calling the tool:

    400 tool_use_failed
    "Tool choice is required, but model did not call a tool"

`generate_ranking_keywords` catches that and returns [], `bm25_rerank`
takes its `if not rows or not keywords` branch, and the demo serves the
pgvector order untouched. Nothing errors. The only trace is a warning:

    [BM25] No rows or keywords -- skipping rerank

Four candidate fixes were measured against gpt-oss-20b at temperature
zero, five serial attempts each, on the real prompt:

    bare schema                 0/5
    described schema            0/5   (later 2/5 -- it is flaky, not fixed)
    described + MEDIUM tier     0/5
    described + examples that
      show no bare array        0/5

None of them work, and the reason is visible in the rejection: the model
produces the right keywords every time and emits them as content. So the
fix is not to make the tool call succeed, it is to keep the answer that
was already generated.

    structured output alone          2/5
    structured output + recovery     5/5

Recovery costs no extra call. A second plain invocation parsed as JSON
also measured 5/5 and is the fallback if the provider stops including
failed_generation.

Separately: the call was synchronous inside an async function, so it held
the event loop for the length of an LLM round trip. On a single-CPU
instance that is every concurrent query waiting on this one.
"""
from __future__ import annotations

import inspect

from backend.retrieval import query_filters
from backend.retrieval.query_filters import RankingKeywords


class TestTheSchemaGroqReceives:
    """
    These assert on the schema rather than on a live call, because the
    live call costs money and the thing that broke is static.
    """

    def test_the_model_is_described(self):
        assert RankingKeywords.__doc__, (
            "an undescribed schema is what Groq refused to call a tool for"
        )

    def test_the_field_is_described(self):
        description = RankingKeywords.model_fields["keywords"].description

        assert description, "keywords: List[str] carries no description"

    def test_the_description_reaches_the_json_schema(self):
        """
        The docstring and Field(description=...) are only useful if they
        survive into what is actually sent.
        """
        schema = RankingKeywords.model_json_schema()

        assert schema.get("description"), "model docstring did not survive"
        assert schema["properties"]["keywords"].get("description"), (
            "field description did not survive"
        )


class TestItDoesNotBlockTheEventLoop:
    def test_generation_is_awaitable(self):
        assert inspect.iscoroutinefunction(
            query_filters.generate_ranking_keywords
        ), "a synchronous LLM call inside an async node holds the loop"

    def test_it_awaits_the_provider(self):
        source = inspect.getsource(query_filters.generate_ranking_keywords)

        assert "await" in source and "ainvoke" in source, (
            "async in name only; .invoke() still blocks"
        )


class TestEveryCallerAwaitsIt:
    """
    Changing the signature without changing the callers would assign a
    coroutine to `keywords` -- truthy, never a list, and silently wrong
    rather than loudly broken.
    """

    def test_vector_search_awaits_it(self):
        """
        retrieve_similar is a @tool object, not a function, so the module
        source is what there is to read.
        """
        from backend.retrieval import vector_search

        source = inspect.getsource(vector_search)

        assert "await generate_ranking_keywords" in source

    def test_hybrid_retrieval_awaits_it(self):
        from backend.retrieval import hybrid_retrieval

        source = inspect.getsource(hybrid_retrieval)

        assert "await generate_ranking_keywords" in source


class TestTheGeneratedAnswerIsNotThrownAway:
    """
    Groq puts the model's actual output in the rejection body. Reading it
    turns a hard failure into a successful call.
    """

    @staticmethod
    def _rejection(payload: str) -> Exception:
        exc = Exception("400 tool_use_failed")
        exc.body = {"error": {"failed_generation": payload}}
        return exc

    def test_it_recovers_the_keywords_from_the_payload(self):
        recovered = query_filters._recover_keywords_from_tool_failure(
            self._rejection(
                '["revenue growth", "year over year", "guidance"]'
            )
        )

        assert recovered == ["revenue growth", "year over year", "guidance"]

    def test_it_finds_the_array_inside_surrounding_prose(self):
        recovered = query_filters._recover_keywords_from_tool_failure(
            self._rejection('Here you go: ["gross margin", "guidance"]')
        )

        assert recovered == ["gross margin", "guidance"]

    def test_an_unrelated_exception_recovers_nothing(self):
        recovered = query_filters._recover_keywords_from_tool_failure(
            TimeoutError("read timed out")
        )

        assert recovered == []

    def test_malformed_json_recovers_nothing(self):
        """
        Recovery must not become a second way to fail loudly.
        """
        recovered = query_filters._recover_keywords_from_tool_failure(
            self._rejection('["unterminated, "list"')
        )

        assert recovered == []

    def test_a_non_list_generation_recovers_nothing(self):
        recovered = query_filters._recover_keywords_from_tool_failure(
            self._rejection('{"keywords": "not a list"}')
        )

        assert recovered == []


class TestTheFailureStaysOpen:
    """
    Deliberately unchanged. A keyword failure degrades retrieval; it must
    not fail the query. The except stays broad and stays logged -- the fix
    is that it no longer fires, not that it now raises.
    """

    def test_it_still_returns_a_list_on_failure(self):
        source = inspect.getsource(query_filters.generate_ranking_keywords)

        assert "return []" in source
        assert "logger.error" in source
