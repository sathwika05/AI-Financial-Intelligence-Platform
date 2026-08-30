"""
Where to go to explain a run, once this is deployed.

CloudWatch holds what the containers printed; LangSmith holds the graph's
trace hierarchy. Both are external products with better interfaces than
anything worth rebuilding here, so the admin UI links out to them rather
than proxying them -- no log reading, no extra IAM grant, no trace viewer
that is worse than the real one.

The URLs are configuration rather than constants: a different AWS account,
region and log group, a different LangSmith project. Empty means this
deployment has nowhere to point, which is the ordinary state on a laptop
and is reported as such rather than as a failure.
"""
from __future__ import annotations

import logging
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends

from backend.auth.dependencies import require_role
from backend.auth.roles import Role
from backend.config import settings


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_role(Role.ADMIN))],
)


def _describe(url: str, *, setting: str, label: str) -> dict:
    """
    One link, and whether it can be followed.

    HTTPS only, and validated here rather than trusted from configuration.
    These values are rendered as anchors in an admin page, so a
    `javascript:` URL would execute on click -- configuration is not
    usually hostile, but it is edited by hand and pasted from consoles,
    and the check costs one line.
    """
    cleaned = (url or "").strip()

    if not cleaned:
        return {
            "configured": False,
            "url": None,
            "detail": (
                f"{setting} is not set on this deployment, so there is no "
                f"{label} to open."
            ),
        }

    if urlsplit(cleaned).scheme != "https":
        logger.warning("[ADMIN] %s is not an https URL; refusing to link it", setting)

        return {
            "configured": False,
            "url": None,
            "detail": f"{setting} must be an https URL.",
        }

    return {"configured": True, "url": cleaned, "detail": None}


def _links(*, cloudwatch: str, langsmith: str) -> dict:
    return {
        "cloudwatch": _describe(
            cloudwatch,
            setting="CLOUDWATCH_LOGS_URL",
            label="log group",
        ),
        "langsmith": _describe(
            langsmith,
            setting="LANGSMITH_PROJECT_URL",
            label="LangSmith project",
        ),
    }


@router.get("/external-links")
async def external_links() -> dict:
    """The observability tools this deployment can link out to."""
    return _links(
        cloudwatch=settings.CLOUDWATCH_LOGS_URL,
        langsmith=settings.LANGSMITH_PROJECT_URL,
    )
