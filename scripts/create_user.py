"""
Create or update a sign-in account.

There is no registration endpoint: this deployment has a handful of users,
and a public signup on a system that spends provider credit per query is a
cost hole rather than a feature.

    uv run python -m scripts.create_user analyst@example.com analyst
    uv run python scripts/create_user.py boss@example.com admin

Both forms work; run either from the repository root.

The password is prompted for, never passed as an argument -- an argument
lands in shell history and in `ps` output.
"""
from __future__ import annotations

import asyncio
import getpass
import sys
import uuid
from pathlib import Path

# Run as a file, Python puts *this* directory on sys.path -- not the
# working directory -- so `import backend` fails however carefully you
# cd first. Running it as `-m scripts.create_user` works, but the form
# people try first is the path, and it should not greet them with a
# ModuleNotFoundError.
_ROOT = Path(__file__).resolve().parents[1]

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import select

from backend.auth.passwords import hash_password
from backend.auth.roles import Role
from backend.models.db_models import User
from backend.services.postgres_service import AsyncSessionLocal


async def upsert(email: str, role: str, password: str) -> str:
    normalised = email.strip().lower()

    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(
                select(User).where(User.email == normalised)
            )
        ).scalar_one_or_none()

        if existing is not None:
            existing.password_hash = hash_password(password)
            existing.role = role
            existing.is_active = True

            await session.commit()

            return f"updated {normalised} ({role})"

        session.add(
            User(
                id=uuid.uuid4(),
                email=normalised,
                password_hash=hash_password(password),
                role=role,
                is_active=True,
            )
        )

        await session.commit()

        return f"created {normalised} ({role})"


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2

    email, role = sys.argv[1], sys.argv[2]

    try:
        role = Role(role).value
    except ValueError:
        valid = ", ".join(r.value for r in Role)
        print(f"Unknown role {role!r}. Valid roles: {valid}")
        return 2

    password = getpass.getpass("Password: ")

    if len(password) < 12:
        # Nothing rate-limits the login, so a short password is the whole
        # of the defence.
        print("Use at least 12 characters.")
        return 2

    if password != getpass.getpass("Confirm: "):
        print("Passwords did not match.")
        return 2

    print(asyncio.run(upsert(email, role, password)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
