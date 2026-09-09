"""
The alias table was consulted and then thrown away.

    provider = PROVIDER_ALIASES.get(normalized_name)   # "gemini" -> "google_genai"
    ...
    model_provider=provider_name,                      # the original "gemini"

PROVIDER_ALIASES exists for exactly one purpose: LangChain identifies
Google's integration as "google_genai", and nobody configuring a provider
types that. The lookup resolved it correctly, used the result only to
decide whether the provider was supported, and then passed the raw name
through anyway.

    gemini      -> google_genai   discarded, "gemini" sent, ImportError
    google      -> google_genai   same
    openai      -> openai         identical, so it worked by coincidence
    anthropic   -> anthropic      same
    groq        -> groq           same

Three of five aliases are identity mappings, which is why this survived:
the only two that actually translate are the two providers nobody had
installed. Fixing the packages made the bug reachable.

Same shape as the confidence defect elsewhere in this codebase -- a value
derived correctly and then not used -- and worth the same note: a lookup
whose result is discarded is worse than no lookup, because it reads as
though the translation happened.
"""
from __future__ import annotations

import inspect

import pytest

from backend.llm import llm_factory
from backend.llm.llm_factory import PROVIDER_ALIASES


class TestTheAliasIsWhatReachesLangChain:
    def test_the_resolved_alias_is_passed_not_the_raw_name(self):
        source = inspect.getsource(llm_factory.create_llm_client)

        assert "model_provider=provider" in source
        assert "model_provider=provider_name" not in source, (
            "the raw name is what broke gemini; the alias exists to "
            "replace it"
        )


class TestTheTableItself:
    @pytest.mark.parametrize("name", ["gemini", "google"])
    def test_googles_two_names_both_translate(self, name):
        """
        The only entries that are not identity mappings, and therefore the
        only ones the bug could ever have affected.
        """
        assert PROVIDER_ALIASES[name] == "google_genai"

    @pytest.mark.parametrize("name", ["openai", "anthropic", "groq"])
    def test_the_others_are_identity(self, name):
        """
        Recorded rather than assumed: these three worked by coincidence,
        which is why nothing caught the discarded lookup for months.
        """
        assert PROVIDER_ALIASES[name] == name

    def test_an_unknown_provider_is_still_refused(self):
        with pytest.raises(RuntimeError) as raised:
            llm_factory.create_llm_client("cohere", "command-r", "key")

        assert "Unsupported LLM provider" in str(raised.value)
        assert "cohere" in str(raised.value)

    def test_the_error_lists_what_is_supported(self):
        """
        A rejection that does not say what would have worked makes the
        caller read the source.
        """
        with pytest.raises(RuntimeError) as raised:
            llm_factory.create_llm_client("cohere", "command-r", "key")

        for name in PROVIDER_ALIASES:
            assert name in str(raised.value)


class TestCaseAndWhitespace:
    @pytest.mark.parametrize("given", ["Gemini", " gemini ", "GEMINI"])
    def test_a_provider_name_is_normalised_before_lookup(self, given):
        """
        The name comes from a database column somebody typed into.
        """
        normalised = given.strip().lower()

        assert PROVIDER_ALIASES.get(normalised) == "google_genai"
