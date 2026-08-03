from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.db_models import LLMModel, LLMProvider
from backend.llm.encryption_service import encryption_service
from backend.services.postgres_service import get_db


router = APIRouter(
    prefix="/admin/llm",
    tags=["Admin LLM"],
)


class ProviderCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=50)
    display_name: str = Field(min_length=2, max_length=100)
    api_key: str = Field(min_length=1)
    is_enabled: bool = True
    is_default: bool = False


class ProviderUpdateRequest(BaseModel):
    display_name: str | None = None
    api_key: str | None = None
    is_enabled: bool | None = None


class ModelCreateRequest(BaseModel):
    tier: str
    model_name: str
    display_name: str | None = None
    input_cost_per_million: float = 0
    output_cost_per_million: float = 0
    is_enabled: bool = True


class ModelUpdateRequest(BaseModel):
    model_name: str | None = None
    display_name: str | None = None
    input_cost_per_million: float | None = None
    output_cost_per_million: float | None = None
    is_enabled: bool | None = None


def serialize_provider(provider: LLMProvider) -> dict:
    return {
        "id": provider.id,
        "name": provider.name,
        "display_name": provider.display_name,
        "is_enabled": provider.is_enabled,
        "is_default": provider.is_default,
        "connection_status": provider.connection_status,
        "last_tested_at": provider.last_tested_at,
        "has_api_key": bool(provider.encrypted_api_key),
        "created_at": provider.created_at,
        "updated_at": provider.updated_at,
    }


@router.post("/providers")
async def create_provider(
    payload: ProviderCreateRequest,
    session: AsyncSession = Depends(get_db),
):
    provider_name = payload.name.lower().strip()

    if payload.is_default and not payload.is_enabled:
        raise HTTPException(
            status_code=400,
            detail="A disabled provider cannot be default",
        )

    existing_result = await session.execute(
        select(LLMProvider).where(
            LLMProvider.name == provider_name
        )
    )

    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="Provider already exists",
        )

    try:
        if payload.is_default:
            await session.execute(
                update(LLMProvider).values(
                    is_default=False
                )
            )

        provider = LLMProvider(
            name=provider_name,
            display_name=payload.display_name.strip(),
            encrypted_api_key=encryption_service.encrypt(
                payload.api_key
            ),
            is_enabled=payload.is_enabled,
            is_default=payload.is_default,
        )

        session.add(provider)
        await session.commit()
        await session.refresh(provider)

        return serialize_provider(provider)

    except IntegrityError as exc:
        await session.rollback()

        raise HTTPException(
            status_code=409,
            detail="Provider configuration conflict",
        ) from exc


@router.get("/providers")
async def list_providers(
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(LLMProvider).order_by(
            LLMProvider.display_name
        )
    )

    return [
        serialize_provider(provider)
        for provider in result.scalars().all()
    ]


@router.patch("/providers/{provider_id}")
async def update_provider(
    provider_id: UUID,
    payload: ProviderUpdateRequest,
    session: AsyncSession = Depends(get_db),
):
    provider = await session.get(
        LLMProvider,
        provider_id,
    )

    if not provider:
        raise HTTPException(
            status_code=404,
            detail="Provider not found",
        )

    updates = payload.model_dump(exclude_unset=True)

    if "api_key" in updates:
        provider.encrypted_api_key = (
            encryption_service.encrypt(
                updates.pop("api_key")
            )
        )
        provider.connection_status = "untested"
        provider.last_tested_at = None

    if "display_name" in updates:
        provider.display_name = updates["display_name"]

    if "is_enabled" in updates:
        provider.is_enabled = updates["is_enabled"]

        if not provider.is_enabled:
            provider.is_default = False

    await session.commit()
    await session.refresh(provider)

    return serialize_provider(provider)


@router.post("/providers/{provider_id}/set-default")
async def set_default_provider(
    provider_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    provider = await session.get(
        LLMProvider,
        provider_id,
    )

    if not provider:
        raise HTTPException(
            status_code=404,
            detail="Provider not found",
        )

    if not provider.is_enabled:
        raise HTTPException(
            status_code=400,
            detail="Enable the provider before setting it as default",
        )

    await session.execute(
        update(LLMProvider).values(
            is_default=False
        )
    )

    provider.is_default = True

    await session.commit()
    await session.refresh(provider)

    return serialize_provider(provider)


@router.post("/providers/{provider_id}/toggle")
async def toggle_provider(
    provider_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    provider = await session.get(
        LLMProvider,
        provider_id,
    )

    if not provider:
        raise HTTPException(
            status_code=404,
            detail="Provider not found",
        )

    provider.is_enabled = not provider.is_enabled

    if not provider.is_enabled:
        provider.is_default = False

    await session.commit()
    await session.refresh(provider)

    return serialize_provider(provider)


@router.delete("/providers/{provider_id}")
async def delete_provider(
    provider_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    provider = await session.get(
        LLMProvider,
        provider_id,
    )

    if not provider:
        raise HTTPException(
            status_code=404,
            detail="Provider not found",
        )

    if provider.is_default:
        raise HTTPException(
            status_code=400,
            detail="Set another default provider before deleting this one",
        )

    await session.delete(provider)
    await session.commit()

    return {
        "message": "Provider deleted successfully"
    }


@router.post("/providers/{provider_id}/models")
async def create_model(
    provider_id: UUID,
    payload: ModelCreateRequest,
    session: AsyncSession = Depends(get_db),
):
    provider = await session.get(
        LLMProvider,
        provider_id,
    )

    if not provider:
        raise HTTPException(
            status_code=404,
            detail="Provider not found",
        )

    normalized_tier = payload.tier.lower().strip()

    if normalized_tier not in {
        "small",
        "medium",
        "large",
    }:
        raise HTTPException(
            status_code=400,
            detail="Tier must be small, medium, or large",
        )

    model = LLMModel(
        provider_id=provider.id,
        tier=normalized_tier,
        model_name=payload.model_name.strip(),
        display_name=payload.display_name,
        input_cost_per_million=(
            payload.input_cost_per_million
        ),
        output_cost_per_million=(
            payload.output_cost_per_million
        ),
        is_enabled=payload.is_enabled,
    )

    try:
        session.add(model)
        await session.commit()
        await session.refresh(model)

        return model

    except IntegrityError as exc:
        await session.rollback()

        raise HTTPException(
            status_code=409,
            detail=(
                f"A model is already configured for tier "
                f"'{normalized_tier}'"
            ),
        ) from exc


@router.get("/providers/{provider_id}/models")
async def list_provider_models(
    provider_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(LLMModel)
        .where(LLMModel.provider_id == provider_id)
        .order_by(LLMModel.tier)
    )

    return list(result.scalars().all())


@router.patch("/models/{model_id}")
async def update_model(
    model_id: UUID,
    payload: ModelUpdateRequest,
    session: AsyncSession = Depends(get_db),
):
    model = await session.get(
        LLMModel,
        model_id,
    )

    if not model:
        raise HTTPException(
            status_code=404,
            detail="Model not found",
        )

    for field, value in payload.model_dump(
        exclude_unset=True
    ).items():
        setattr(model, field, value)

    await session.commit()
    await session.refresh(model)

    return model


@router.delete("/models/{model_id}")
async def delete_model(
    model_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    model = await session.get(
        LLMModel,
        model_id,
    )

    if not model:
        raise HTTPException(
            status_code=404,
            detail="Model not found",
        )

    await session.delete(model)
    await session.commit()

    return {
        "message": "Model deleted successfully"
    }