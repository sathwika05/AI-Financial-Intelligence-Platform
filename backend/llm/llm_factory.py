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
            model_provider=provider_name,
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
