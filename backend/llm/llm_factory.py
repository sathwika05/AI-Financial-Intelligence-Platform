# llm_service.py

from langchain_openai import ChatOpenAI
from langchain.chat_models import init_chat_model


from langchain.chat_models import init_chat_model


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
    )

    except Exception as exc:
        raise RuntimeError(
            f"Failed to initialize model '{model_name}' "
            f"for provider '{provider_name}'"
        ) from exc
