from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from backend.llm.llm_runtime import LLMRuntime


logger = logging.getLogger(__name__)


class UsageTracker(BaseCallbackHandler):
    """
    Accumulates token usage and cost across every LLM call in one graph run.

    Attached to the invocation config rather than to individual call sites:
    LangChain propagates callbacks down through nested runnables, so a single
    handler sees every model call the pipeline makes without any node having
    to know about it.

    Cost is computed from the per-model rates already loaded on the request's
    LLMRuntime, so it is the provider's configured price for the exact model
    that ran — not an estimate and not a hard-coded table. A call whose model
    is not in the runtime still contributes its tokens; only its cost is
    skipped, and that is reported rather than silently absorbed.
    """

    def __init__(self, runtime: LLMRuntime | None) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.call_count = 0
        self.cost_usd = Decimal("0")

        # Calls whose model could not be priced, so the caller can tell an
        # honest zero from an incomplete total.
        self.unpriced_calls = 0

        self._rates: dict[str, tuple[Decimal, Decimal]] = {}

        for model in (runtime.models if runtime else {}).values():
            self._rates[model.model_name] = (
                Decimal(model.input_cost_per_million),
                Decimal(model.output_cost_per_million),
            )

    # ── Extraction ──────────────────────────────────────────────

    @staticmethod
    def _token_counts(response: LLMResult) -> tuple[int, int]:
        """
        Read prompt/completion tokens from whichever shape arrived.

        Providers report usage in two places: `llm_output.token_usage` on the
        result, and `usage_metadata` on the generated message. Both are
        checked because which one is populated varies by integration and by
        whether structured output was used.
        """
        output = response.llm_output or {}
        usage = output.get("token_usage") or output.get("usage") or {}

        prompt = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        completion = (
            usage.get("completion_tokens") or usage.get("output_tokens") or 0
        )

        if prompt or completion:
            return int(prompt), int(completion)

        for generations in response.generations:
            for generation in generations:
                message = getattr(generation, "message", None)
                metadata = getattr(message, "usage_metadata", None) or {}

                if metadata:
                    return (
                        int(metadata.get("input_tokens", 0)),
                        int(metadata.get("output_tokens", 0)),
                    )

        return 0, 0

    @staticmethod
    def _model_name(response: LLMResult, kwargs: dict[str, Any]) -> str:
        output = response.llm_output or {}

        name = output.get("model_name") or output.get("model")

        if name:
            return str(name)

        # Falls back to the invocation params LangChain attaches to the run.
        params = kwargs.get("invocation_params") or {}

        return str(params.get("model") or params.get("model_name") or "")

    # ── Callback ────────────────────────────────────────────────

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        try:
            prompt_tokens, completion_tokens = self._token_counts(response)

            self.call_count += 1
            self.input_tokens += prompt_tokens
            self.output_tokens += completion_tokens

            rates = self._rates.get(
                self._model_name(response, kwargs)
            )

            if rates is None:
                self.unpriced_calls += 1
                return

            input_rate, output_rate = rates

            self.cost_usd += (
                Decimal(prompt_tokens) / Decimal(1_000_000) * input_rate
                + Decimal(completion_tokens) / Decimal(1_000_000) * output_rate
            )
        except Exception:
            # Accounting must never take down a query that already succeeded.
            logger.exception(
                "Failed to record LLM usage; continuing without it",
            )

    # ── Results ─────────────────────────────────────────────────

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def totals(self) -> dict[str, Any]:
        """
        Usage for this run.

        `total_cost_usd` is None when nothing could be priced, so an
        unconfigured provider reads as "unknown" rather than as free.
        """
        priced = self.call_count - self.unpriced_calls

        return {
            "llm_calls": self.call_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "total_cost_usd": (
                float(round(self.cost_usd, 6)) if priced > 0 else None
            ),
            "unpriced_llm_calls": self.unpriced_calls,
        }


def build_usage_config(
    runtime: LLMRuntime | None,
    *,
    provider_id: UUID | None = None,
) -> tuple[dict[str, Any], UsageTracker]:
    """
    Build the invocation config carrying the runtime and a fresh tracker.

    One tracker per graph run — sharing one across runs would pool their
    tokens together.
    """
    tracker = UsageTracker(runtime)

    config: dict[str, Any] = {
        "configurable": {"llm_runtime": runtime},
        "callbacks": [tracker],
    }

    if provider_id is not None:
        config["configurable"]["provider_id"] = provider_id

    return config, tracker
