
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from langchain_core.language_models import BaseChatModel

from backend.llm.llm_tiers import LLMTier







@dataclass(frozen=True)
class ModelRuntime:
    tier: str
    model_name: str
    client: BaseChatModel
    input_cost_per_million: Decimal
    output_cost_per_million: Decimal

@dataclass(frozen=True)
class LLMRuntime:
    """
    Request-scoped collection of models for one provider.
    """

    provider_id: UUID
    provider_name: str
    models: dict[str,ModelRuntime]

    def get_model(self, tier: LLMTier | str,) -> ModelRuntime:

        tier_value = (
            tier.value
            if isinstance(tier, LLMTier)
            else tier
        )

        model = self.models.get(tier_value)

        if model is None:
            available = ", ".join(self.model.keys())

            raise RuntimeError(
                f"Model Tier '{tier_value}' is not configured for "
                f"provider '{self.provider_name}'. "
                f"Available tiers: {available}"
            )

        return model

    def get_client(self, tier: LLMTier | str,):
        return self.get_model(tier).client


    def get_model_name(
        self,
        tier: LLMTier | str,
    ) -> str:
        return self.get_model(tier).model_name

    def describe(self) -> dict[str, str]:
        return {
            tier: model.model_name
            for tier, model in self.models.items()
        }


    