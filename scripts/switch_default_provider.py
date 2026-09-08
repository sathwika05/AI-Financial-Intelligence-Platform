"""
Move the default LLM provider, after proving the new one works.

There is no UI for this on the public demo: admin_llm_routes lives behind
`if mode == "full"`, and preprod runs portfolio mode. So this is the
supported way to do it, and it is a script rather than a psql one-liner
because two things must not be got wrong.

    Exactly one default. _load_default_provider selects on
    is_default AND is_enabled with scalar_one_or_none(), so two defaults
    raise MultipleResultsFound on every query rather than picking one.
    The unset and the set are one transaction.

    A key that decrypts is not a key that works. The column holds
    Fernet ciphertext under LLM_KEY_ENCRYPTION_SECRET; decrypting proves
    the secret matches, not that the provider will accept what came out.
    This calls the small model before it writes anything, because the
    failure it is guarding against -- switching preprod to a provider
    that 401s -- takes the demo down completely and silently.

Usage, against whichever database DATABASE_URL points at:

    python scripts/switch_default_provider.py --to openai
    python scripts/switch_default_provider.py --to openai --dry-run
    python scripts/switch_default_provider.py --show

Point it at preprod by exporting that DATABASE_URL first. It prints which
host it is about to change, and asks, because "which database am I on" is
the mistake worth making expensive.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from urllib.parse import urlparse

# Same shim as create_user.py: run as a file, Python puts *this*
# directory on sys.path rather than the working directory, so
# `import backend` fails however carefully you cd first.
_ROOT = Path(__file__).resolve().parents[1]

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.llm.encryption_service import EncryptionService
from backend.llm.llm_factory import create_llm_client
from backend.models.db_models import LLMModel, LLMProvider

REQUIRED_TIERS = ("small", "medium", "large")


def _where(url: str) -> str:
    """Host and database only. The password must not reach a terminal."""
    parsed = urlparse(url)
    return f"{parsed.hostname or '?'}/{(parsed.path or '').lstrip('/') or '?'}"


async def _providers(session: AsyncSession) -> list[LLMProvider]:
    result = await session.execute(select(LLMProvider))
    return list(result.scalars())


async def _models(session: AsyncSession, provider_id) -> dict[str, str]:
    result = await session.execute(
        select(LLMModel).where(
            LLMModel.provider_id == provider_id,
            LLMModel.is_enabled.is_(True),
        )
    )
    return {m.tier: m.model_name for m in result.scalars()}


async def show(session: AsyncSession) -> None:
    for provider in await _providers(session):
        tiers = await _models(session, provider.id)
        marks = "".join(
            [
                "D" if provider.is_default else "-",
                "E" if provider.is_enabled else "-",
            ]
        )
        print(f"  [{marks}] {provider.name:<10} {tiers}")
    print("\n  D = default, E = enabled")


async def verify(session: AsyncSession, name: str) -> LLMProvider:
    """Every reason this switch could break the demo, checked first."""
    result = await session.execute(
        select(LLMProvider).where(LLMProvider.name == name)
    )
    provider = result.scalar_one_or_none()

    if provider is None:
        sys.exit(f"No provider named {name!r} in this database.")

    if not provider.is_enabled:
        sys.exit(
            f"{name} is disabled. A disabled default is selected by "
            "nothing, so every query would fail with 'No enabled default "
            "LLM provider is configured'."
        )

    tiers = await _models(session, provider.id)
    missing = [tier for tier in REQUIRED_TIERS if tier not in tiers]

    if missing:
        sys.exit(
            f"{name} has no enabled model for: {', '.join(missing)}. "
            "Every tier is reached on an ordinary query."
        )

    print(f"  models    {tiers}")

    try:
        api_key = EncryptionService().decrypt(provider.encrypted_api_key)
    except Exception as exc:
        sys.exit(
            f"Could not decrypt {name}'s key: {exc}\n"
            "The ciphertext was written under a different "
            "LLM_KEY_ENCRYPTION_SECRET than this environment has."
        )

    print("  decrypt   ok")

    # The check that matters. A key can decrypt cleanly and still be
    # revoked, out of credit, or for the wrong organisation.
    client = create_llm_client(name, tiers["small"], api_key)

    try:
        await client.ainvoke("Reply with the single word: ready")
    except Exception as exc:
        sys.exit(
            f"{name} decrypted but would not answer: "
            f"{type(exc).__name__}: {exc}\n"
            "Nothing was changed."
        )

    print(f"  live call ok ({tiers['small']})")

    return provider


async def switch(session: AsyncSession, provider: LLMProvider) -> None:
    """Unset and set together, so no moment has two defaults or none."""
    await session.execute(
        update(LLMProvider)
        .where(LLMProvider.is_default.is_(True))
        .values(is_default=False)
    )
    await session.execute(
        update(LLMProvider)
        .where(LLMProvider.id == provider.id)
        .values(is_default=True)
    )
    await session.commit()

    result = await session.execute(
        select(LLMProvider).where(
            LLMProvider.is_default.is_(True),
            LLMProvider.is_enabled.is_(True),
        )
    )
    # Same call the application makes. If this raises here, it would have
    # raised on every query instead.
    confirmed = result.scalar_one_or_none()

    if confirmed is None or confirmed.id != provider.id:
        sys.exit("The switch did not take. Check the database by hand.")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", help="provider name, e.g. openai")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--yes", action="store_true", help="skip the confirmation"
    )
    args = parser.parse_args()

    url = settings.DATABASE_URL
    engine = create_async_engine(url, echo=False)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        print(f"\ndatabase  {_where(url)}\n")
        await show(session)

        if args.show or not args.to:
            await engine.dispose()
            return

        print(f"\nchecking {args.to}")
        provider = await verify(session, args.to)

        if args.dry_run:
            print(f"\ndry run: {args.to} is ready. Nothing changed.")
            await engine.dispose()
            return

        if not args.yes:
            print(f"\nMake {args.to} the default on {_where(url)}?")

            if input("type the database name to confirm: ").strip() != (
                urlparse(url).path or ""
            ).lstrip("/"):
                sys.exit("Not confirmed. Nothing changed.")

        await switch(session, provider)
        print(f"\n{args.to} is now the default.\n")
        await show(session)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
