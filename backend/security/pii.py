"""Detect and mask personal data in queries and reports.

Anchored tightly because this endpoint is full of numbers that are not
personal data: a market cap is sixteen digits, a P/E ratio has a decimal
point, and "2024 to 2026" is not a phone number. A pattern that fires on
those would mask the answer.
"""
from __future__ import annotations

import re


PATTERNS: dict[str, str] = {
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",

    # Requires separators or a leading +/(, so a bare ten-digit financial
    # figure does not match.
    "phone": r"(?:\+\d{1,2}[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b",

    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",

    # Separated groups only. An unseparated 16-digit run is far more likely
    # to be a market capitalisation in this corpus than a card number.
    "credit_card": r"\b\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}\b",

    # Excludes anything with a decimal point on either side, so a P/E of
    # 33.20827 and a version string are left alone.
    "ip_address": r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])",
}

REDACTIONS: dict[str, str] = {
    "email": "[EMAIL REDACTED]",
    "phone": "[PHONE REDACTED]",
    "ssn": "[SSN REDACTED]",
    "credit_card": "[CARD REDACTED]",
    "ip_address": "[IP REDACTED]",
}


class PIIDetector:
    def __init__(self) -> None:
        self._compiled = {
            name: re.compile(pattern)
            for name, pattern in PATTERNS.items()
        }

    def detect(self, text: str) -> dict[str, list[str]]:
        """Every kind of personal data found, with the matches."""
        found: dict[str, list[str]] = {}

        for name, pattern in self._compiled.items():
            matches = pattern.findall(text or "")

            if matches:
                found[name] = matches

        return found

    def mask(self, text: str) -> str:
        """The same text with personal data replaced by a marker."""
        masked = text or ""

        for name, pattern in self._compiled.items():
            masked = pattern.sub(REDACTIONS[name], masked)

        return masked
