"""Injection detection and sanitising for analyst queries.

Tuned for finance questions rather than general chat. "act as" appears in
"how does Amex act as both issuer and network"; "system" appears in
"payment system upgrades"; "ignore the previous quarter" is a real thing to
ask. Patterns therefore require the imperative form — an instruction aimed
at the model — instead of the bare phrase.

The tradeoff is deliberate. A missed injection reaches a pipeline that
still has to ground every claim in retrieved evidence and pass a reviewer
that validates citations; a false positive returns nothing at all.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Verdict:
    """The outcome of inspecting one input."""

    blocked: bool
    reason: str | None = None
    pattern: str | None = None


# Each requires the model to be addressed, not just the words to appear.
INJECTION_PATTERNS: tuple[str, ...] = (
    # "ignore/disregard/forget ... previous/prior/above ... instructions"
    r"\b(ignore|disregard|forget)\b[^.?!]{0,40}\b(previous|prior|earlier|above|all)\b"
    r"[^.?!]{0,20}\b(instruction|instructions|prompt|rule|rules|context)\b",

    # An injected instruction block.
    r"\bnew\s+instructions?\s*:",
    r"[-=]{3,}\s*end\s+(of\s+)?(the\s+)?(prompt|instructions)",

    # Role override aimed at the assistant.
    r"\bpretend\s+(you|to\s+be)\b",
    r"\bact\s+as\s+(if\s+)?(you|though)\b",
    r"\byou\s+are\s+now\b[^.?!]{0,30}\b(unrestricted|jailbroken|dan)\b",

    # Asking for the instructions themselves.
    r"\b(reveal|show|print|repeat|output)\b[^.?!]{0,25}\b(system\s*prompt|your\s+instructions)\b",

    # Explicit restriction bypass.
    r"\bbypass\b[^.?!]{0,20}\b(restriction|restrictions|filter|filters|guardrail|guardrails)\b",
    r"\b(disable|turn\s+off)\b[^.?!]{0,20}\b(safety|filter|filters|guardrail|guardrails)\b",
)


class InputGuard:
    """Inspect and clean an analyst query before it reaches the graph."""

    def __init__(self, patterns: tuple[str, ...] = INJECTION_PATTERNS):
        self._patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in patterns
        ]

    def inspect(self, text: str) -> Verdict:
        """Whether this input is an instruction aimed at the model."""
        for pattern in self._patterns:
            match = pattern.search(text or "")

            if match:
                return Verdict(
                    blocked=True,
                    reason=(
                        "The request contains an instruction aimed at the "
                        "assistant rather than a question about the data."
                    ),
                    pattern=pattern.pattern,
                )

        return Verdict(blocked=False)

    def sanitize(self, text: str) -> str:
        """Remove markers that could be read as prompt structure.

        Braces are defused rather than dropped: the prompt layer formats
        strings, and a stray {{ }} arriving from a user would be read as a
        template placeholder.
        """
        cleaned = re.sub(r"[-]{3,}", " ", text or "")
        cleaned = re.sub(r"[=]{3,}", " ", cleaned)
        cleaned = cleaned.replace("{{", "{ {").replace("}}", "} }")

        return re.sub(r"\s{2,}", " ", cleaned).strip()
