"""
Groq as a provider, for the public preprod demo.

WHY IT EXISTS
    The preprod deployment is public and unauthenticated, so the ceiling on
    an endpoint that costs real money per call has to be something other
    than a login. Groq's free tier turns that ceiling into requests per
    minute rather than dollars.

    The Render blueprint has assumed this since it was written: it sets
    GROQ_API_KEY and its comments say "Groq serves the chat models for the
    public demo". But PROVIDER_ALIASES only ever held openai, anthropic and
    google -- so the deployment would have passed its health check and then
    raised "Unsupported LLM provider 'groq'" on the first question anyone
    asked.

THREE TIERS, TWO MODELS
    Groq's free tier serves several chat models, so the tiers are not
    forced onto one name: small runs gpt-oss-20b, medium and large both
    run gpt-oss-120b. Two tiers sharing a name is a sizing choice, not a
    constraint, so nothing may assume the three names are distinct -- and
    nothing may assume they are identical either. This test pins only that
    sharing is allowed.

    The names here are the ones the deployment actually uses, confirmed
    against the account with a live call. They matter: create_llm_client
    constructs a client without contacting the provider, so a wrong model
    name passes every test in this file and fails on the first question a
    user asks.
"""
import pytest

from backend.llm.llm_factory import PROVIDER_ALIASES, create_llm_client


class TestGroqIsAKnownProvider:
    def test_groq_is_in_the_alias_table(self):
        assert "groq" in PROVIDER_ALIASES

    def test_it_maps_to_langchain_s_own_provider_name(self):
        assert PROVIDER_ALIASES["groq"] == "groq"

    def test_the_existing_providers_are_untouched(self):
        """Adding one must not disturb the three already there."""
        for name in ("openai", "anthropic", "google", "gemini"):
            assert name in PROVIDER_ALIASES

    def test_an_unknown_provider_still_names_groq_in_its_error(self):
        """
        The error lists what is supported. If groq is absent from that
        list, someone configuring the demo has no way to discover it.
        """
        with pytest.raises(RuntimeError) as caught:
            create_llm_client("nonesuch", "some-model", "key")

        assert "groq" in str(caught.value)


class TestTheClientBuilds:
    def test_a_groq_client_can_be_constructed(self):
        """
        The failure this catches is an uninstalled package: init_chat_model
        resolves a provider by importing it at call time, so a missing
        langchain-groq raises here and nowhere earlier.
        """
        client = create_llm_client("groq", "openai/gpt-oss-20b", "gsk-not-real")

        assert client is not None

    def test_tiers_may_share_a_model_name(self):
        """
        Medium and large both run gpt-oss-120b. Building two clients for
        one name has to work, so nothing may assume the tiers resolve to
        distinct models.
        """
        clients = [
            create_llm_client("groq", "openai/gpt-oss-120b", "gsk-not-real")
            for _ in range(2)
        ]

        assert all(c is not None for c in clients)

    def test_tiers_may_also_differ(self):
        """The other half: small runs a different model from the rest."""
        small = create_llm_client("groq", "openai/gpt-oss-20b", "gsk-not-real")
        large = create_llm_client("groq", "openai/gpt-oss-120b", "gsk-not-real")

        assert small is not None and large is not None

    def test_the_timeout_and_retry_ceiling_still_apply(self):
        """
        A public endpoint with no login needs the hang ceiling as much as
        the authenticated one -- more so, since nobody is watching it.
        """
        client = create_llm_client("groq", "openai/gpt-oss-20b", "gsk-not-real")

        assert getattr(client, "request_timeout", None) or getattr(
            client, "timeout", None
        )
