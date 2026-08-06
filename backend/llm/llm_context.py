








from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig

from backend.llm.llm_runtime import LLMRuntime, ModelRuntime
from backend.llm.llm_tiers import LLMTier


LLM_RUNTIME_CONFIG_KEY = "llm_runtime"


def get_llm_runtime(config: RunnableConfig | None,) -> LLMRuntime:
    """
    Extract and validate the request-scoped LLM runtime
    from LangGraph configuration.
    """

    if config is None:
        raise RuntimeError("LangGraph config was not supplied to the node")

    configurable: dict[str, Any]= config.get(
        "configurable",
        {},
    )

    runtime = configurable.get(LLM_RUNTIME_CONFIG_KEY)

    if runtime is None:
        raise RuntimeError("llm_runtime is missing from LangGraph config")

    if not isinstance(runtime, LLMRuntime):
        raise RuntimeError("Invalid llm_runtime object in LangGraph config")

    return runtime

def get_model_runtime(
        config: RunnableConfig | None,
        tier: LLMTier | str,
) -> ModelRuntime:
    runtime = get_llm_runtime(config)
    return runtime.get_model(tier)

def get_llm_client(
        config: RunnableConfig | None,
        tier: LLMTier | str,
) -> BaseChatModel:
    runtime = get_llm_runtime(config)
    return runtime.get_client(tier)
    
    

    






    













