from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.llm.llm_tiers import LLMTier
from backend.models.db_models import LLMModel, LLMProvider
from backend.llm.encryption_service import EncryptionService, encryption_service
from backend.llm.llm_runtime import LLMRuntime, ModelRuntime
from backend.llm.llm_factory import create_llm_client

from backend.config import settings 


REQUIRED_TIERS = {
    LLMTier.SMALL.value,
    LLMTier.MEDIUM.value,
    LLMTier.LARGE.value,
}


class LLMConfigService:

    """
    Loads LLM provider/model configuration from the database
    and builds a request-scoped LLMRuntime.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

        self.encryption_service = EncryptionService(
            settings.LLM_ENCRYPTION_KEY
        )

    async def load_default_runtime(
        self,
    ) -> LLMRuntime:
        provider = await self._load_default_provider()

        model_records = await self._load_enabled_models(
            provider.id
        )

        return self._build_runtime(
            provider=provider,
            model_records=model_records,
        )

    async def _load_default_provider(
        self,
    ) -> LLMProvider:
        result = await self.session.execute(
            select(LLMProvider).where(
                LLMProvider.is_default.is_(True),
                LLMProvider.is_enabled.is_(True),
            )
        )

        provider = result.scalar_one_or_none()

        if provider is None:
            raise RuntimeError(
                "No enabled default LLM provider "
                "is configured"
            )

        return provider

    async def _load_enabled_models(
        self,
        provider_id: UUID,
    ) -> list[LLMModel]:
        result = await self.session.execute(
            select(LLMModel).where(
                LLMModel.provider_id == provider_id,
                LLMModel.is_enabled.is_(True),
            )
        )

        model_records = list(
            result.scalars().all()
        )

        if not model_records:
            raise RuntimeError(
                "No enabled models are configured for "
                "the default LLM provider"
            )

        return model_records


    def _build_runtime(
        self,
        provider: LLMProvider,
        model_records: list[LLMModel],
    ) -> LLMRuntime:
        api_key = self.encryption_service.decrypt(
            provider.encrypted_api_key
        )

        runtime_models: dict[str, ModelRuntime] = {}

        for model_record in model_records:
            tier = model_record.tier.strip().lower()

            if tier in runtime_models:
                raise RuntimeError(
                    f"Multiple enabled models are configured "
                    f"for tier '{tier}'"
                )

            client = create_llm_client(
                provider_name=provider.name,
                model_name=model_record.model_name,
                api_key=api_key,
                temperature=0,
            )

            runtime_models[tier] = ModelRuntime(
                tier=tier,
                model_name=model_record.model_name,
                client=client,
                input_cost_per_million=(
                    model_record.input_cost_per_million
                ),
                output_cost_per_million=(
                    model_record.output_cost_per_million
                ),
            )

        self._validate_required_tiers(
            runtime_models
        )

        return LLMRuntime(
            provider_id=provider.id,
            provider_name=provider.name,
            models=runtime_models,
        )

    @staticmethod
    def _validate_required_tiers(
        runtime_models: dict[str, ModelRuntime],
    ) -> None:
        missing_tiers = (
            REQUIRED_TIERS - runtime_models.keys()
        )

        if missing_tiers:
            raise RuntimeError(
                "Missing required LLM model tiers: "
                + ", ".join(sorted(missing_tiers))
            )