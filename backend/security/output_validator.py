"""Check a generated report before it leaves the process.

Two different failures, handled differently. Personal data is masked and
the report still goes out, because the analysis around it is still useful.
A leaked credential is blocked outright, because there is no version of
that report worth returning.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.security.pii import PIIDetector


@dataclass
class ValidationResult:
    output: str
    blocked: bool = False
    findings: list[str] = field(default_factory=list)


# Deliberately narrow. "key metrics" and "key takeaway" are everywhere in
# financial writing, so the pattern requires the credential form.
SECRET_PATTERNS: tuple[str, ...] = (
    r"\bapi[_\-\s]?key\b\s*(is|=|:)",
    r"\b(password|passwd|secret)\b\s*(is|=|:)",
    r"\bsk-[A-Za-z0-9]{16,}\b",
    r"\bBearer\s+[A-Za-z0-9._\-]{20,}",
)


class OutputValidator:
    def __init__(self) -> None:
        self._pii = PIIDetector()
        self._secrets = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in SECRET_PATTERNS
        ]

    def validate(self, output: str) -> ValidationResult:
        text = output or ""

        for pattern in self._secrets:
            if pattern.search(text):
                return ValidationResult(
                    output="[CONTENT BLOCKED]",
                    blocked=True,
                    findings=["credential-like content in the report"],
                )

        found = self._pii.detect(text)

        if found:
            return ValidationResult(
                output=self._pii.mask(text),
                blocked=False,
                findings=[f"masked {name}" for name in sorted(found)],
            )

        return ValidationResult(output=text)
