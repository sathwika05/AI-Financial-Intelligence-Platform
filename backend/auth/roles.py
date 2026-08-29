"""
The two roles this system grants.

Deliberately two, not three. The mock showed a Viewer as well, but a role
nothing enforces is worse than no role: it reads as a guarantee while
granting whatever the next handler happens to allow. Add it when something
actually distinguishes it from analyst.
"""
from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    # Configures the system: providers, indexing, users.
    ADMIN = "admin"

    # Uses the system: queries, benchmarks, the dashboard.
    ANALYST = "analyst"


# Ascending. Everything an analyst may do, an admin may also do.
_RANK: dict[Role, int] = {
    Role.ANALYST: 1,
    Role.ADMIN: 2,
}


def has_at_least(actual: Role, required: Role) -> bool:
    """Whether `actual` satisfies a handler requiring `required`."""
    return _RANK[actual] >= _RANK[required]
