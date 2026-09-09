# llm_service.py

from langchain_openai import ChatOpenAI
from langchain.chat_models import init_chat_model


from langchain.chat_models import init_chat_model


# How long a single provider call may take before it is abandoned.
#
# Run dbba921f stalled three and a half hours on one question: every call
# returned 200, none were rate-limited, but a handful hung — the longest for
# 84 minutes against a median gap of 11 seconds. Without a timeout the run
# had no way to give up, 15 questions never ran, and it had to be killed by
# hand.
#
# Five minutes is well clear of honest work — the analysis node takes 15-36s
# and the reviewer's judges longer — while catching a hang far short of the
# 16-minute minimum observed.
REQUEST_TIMEOUT_SECONDS = 300

# A timeout retried without limit is not a timeout. This is the SDK default,
# pinned so the worst case stays predictable: three attempts, so a hung call
# costs at most REQUEST_TIMEOUT_SECONDS * 3 before the question fails.
MAX_REQUEST_RETRIES = 2


PROVIDER_ALIASES: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google_genai",
    "gemini": "google_genai",

    # Serves the public preprod demo. That deployment is unauthenticated,
    # so the ceiling on an endpoint that costs money per call has to be
    # something other than a login; Groq's free tier makes the limit
    # requests per minute instead of dollars.
    #
    # The tiers map to real, different models on that tier: gpt-oss-20b
    # for small, gpt-oss-120b for medium and large. Two tiers sharing a
    # name is a sizing choice, so nothing may assume the three are
    # distinct -- see tests/test_groq_provider.py.
    "groq": "groq",
}


def create_llm_client(
    provider_name: str,
    model_name: str,
    api_key: str,
    temperature: float = 0,
):
    """
    Create a LangChain chat model from database configuration.
    """

    normalized_name = provider_name.strip().lower()

    provider = PROVIDER_ALIASES.get(normalized_name)

    if provider is None:
        supported = ", ".join(
            sorted(PROVIDER_ALIASES.keys())
        )

        raise RuntimeError(
            f"Unsupported LLM provider '{provider_name}'. "
            f"Supported provider names: {supported}"
        )

    try:
        return init_chat_model(
            model=model_name,
            # The resolved alias, not the name that was typed. LangChain
            # identifies Google's integration as "google_genai" and nobody
            # configures a provider under that name -- which is what
            # PROVIDER_ALIASES is for. Passing provider_name here consulted
            # the table, used the answer only to decide whether the
            # provider was supported, and then sent the raw name anyway.
            # Three of the five aliases are identity mappings, so the only
            # two that translate were the only two that broke.
            model_provider=provider,
            api_key=api_key,
            temperature=0,
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=MAX_REQUEST_RETRIES,
        )

    except Exception as exc:
        raise RuntimeError(
            f"Failed to initialize model '{model_name}' "
            f"for provider '{provider_name}'"
        ) from exc
