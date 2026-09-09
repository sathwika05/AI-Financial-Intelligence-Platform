"""
Copy an LLM provider and its models from one database into another.

Preprod was seeded with one provider. Adding a second there means either
the admin UI -- which portfolio mode does not mount -- or hand-written
SQL against four columns of pricing and a Fernet blob. This is the third
option.

The encrypted key is copied as ciphertext, not re-encrypted, and that is
only sound when both databases share LLM_KEY_ENCRYPTION_SECRET. The
script proves that first, by decrypting a row that already exists in the
destination. If the secrets differ, the copied key would decrypt to
nothing there and every query would fail with an unhelpful error long
after this script had reported success.

    python scripts/copy_provider.py --provider openai \
        --from "$DATABASE_URL" --to "$PREPROD_DATABASE_URL" --dry-run

Never sets is_default. Copying a provider and switching to it are
separate decisions, and switch_default_provider.py is where the second
one lives -- with its own checks.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from urllib.parse import urlparse

_ROOT = Path(__file__).resolve().parents[1]

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.llm.encryption_service import EncryptionService
from backend.models.db_models import LLMModel, LLMProvider


def _where(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.hostname or '?'}/{(parsed.path or '').lstrip('/') or '?'}"


def _session(url: str):
    engine = create_async_engine(url, echo=False)
    return engine, sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )


async def _load(session: AsyncSession, name: str):
    result = await session.execute(
        select(LLMProvider).where(LLMProvider.name == name)
    )
    provider = result.scalar_one_or_none()

    if provider is None:
        return None, []

    result = await session.execute(
        select(LLMModel).where(LLMModel.provider_id == provider.id)
    )

    return provider, list(result.scalars())


async def _prove_shared_secret(session: AsyncSession) -> None:
    """
    Decrypt something the destination already holds.

    Copying ciphertext between databases is only valid if both were
    written under the same secret. Guessing wrong produces a provider
    that looks correct in every column and fails at the first query.
    """
    result = await session.execute(select(LLMProvider).limit(1))
    existing = result.scalar_one_or_none()

    if existing is None:
        sys.exit(
            "The destination has no providers at all, so there is nothing "
            "to check the encryption secret against. Seed it first."
        )

    try:
        EncryptionService().decrypt(existing.encrypted_api_key)
    except Exception:
        sys.exit(
            f"The destination's {existing.name!r} key does not decrypt with "
            "this environment's LLM_KEY_ENCRYPTION_SECRET.\n"
            "The secrets differ, so a copied key would arrive unreadable. "
            "Nothing was changed."
        )

    print(f"  secret    shared (verified against {existing.name!r})")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--from", dest="src", required=True)
    parser.add_argument("--to", dest="dst", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    src_engine, src_factory = _session(args.src)
    dst_engine, dst_factory = _session(args.dst)

    print(f"\nfrom  {_where(args.src)}")
    print(f"to    {_where(args.dst)}\n")

    async with src_factory() as src, dst_factory() as dst:
        provider, models = await _load(src, args.provider)

        if provider is None:
            sys.exit(f"No provider named {args.provider!r} in the source.")

        if not models:
            sys.exit(
                f"{args.provider} has no models in the source. A provider "
                "without tiers fails on the first query, not at startup."
            )

        print(f"  provider  {provider.name} ({provider.display_name})")

        for model in sorted(models, key=lambda m: m.tier):
            print(f"  model     {model.tier:<7} {model.model_name}")

        await _prove_shared_secret(dst)

        existing, _ = await _load(dst, args.provider)

        if existing is not None:
            sys.exit(
                f"{args.provider} already exists in the destination. This "
                "script creates; it does not merge or overwrite."
            )

        if args.dry_run:
            print("\ndry run: nothing written.")
            await src_engine.dispose()
            await dst_engine.dispose()
            return

        copied = LLMProvider(
            name=provider.name,
            display_name=provider.display_name,
            encrypted_api_key=provider.encrypted_api_key,
            is_enabled=provider.is_enabled,
            # Never inherited. Copying a provider and making it the
            # default are separate decisions, and two default rows make
            # _load_default_provider raise on every query.
            is_default=False,
            connection_status=provider.connection_status,
        )

        dst.add(copied)
        await dst.flush()

        for model in models:
            dst.add(
                LLMModel(
                    provider_id=copied.id,
                    tier=model.tier,
                    model_name=model.model_name,
                    display_name=model.display_name,
                    input_cost_per_million=model.input_cost_per_million,
                    output_cost_per_million=model.output_cost_per_million,
                    is_enabled=model.is_enabled,
                )
            )

        await dst.commit()

        written, written_models = await _load(dst, args.provider)

        print(
            f"\ncopied {written.name} with {len(written_models)} models, "
            "not default."
        )
        print(
            f"Make it default with:\n"
            f"  DATABASE_URL=<destination> python "
            f"scripts/switch_default_provider.py --to {args.provider}\n"
        )

    await src_engine.dispose()
    await dst_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
