import os

from backend.config import settings


def setup_langsmith() -> None:
    """Propagates LangSmith config from Settings into the process environment.

    The LangSmith/LangChain SDKs read tracing config directly from
    os.environ at call time, not from our pydantic Settings object, so this
    must run once at startup before any graph/chain invocation.
    """
    os.environ["LANGSMITH_TRACING"] = "true" if settings.LANGSMITH_TRACING else "false"

    if not settings.LANGSMITH_TRACING:
        return

    if not settings.LANGSMITH_API_KEY:
        raise RuntimeError("LANGSMITH_TRACING is enabled but LANGSMITH_API_KEY is not set")

    os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY
    os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT
