"""
PII masking on the way in, validation on the way out.

Masking matters here because the query leaves the process twice: to the LLM
provider, and into LangSmith traces, which are the copy that persists. An
analyst pasting a client email into a question should not have it retained
by either.

The finance-specific trap is the ticker-shaped false positive. A US phone
pattern matches plenty of things that are not phone numbers, and a bare
4-digit run appears in "revenue grew from 2024 to 2026". Each pattern is
therefore anchored tightly enough to leave financial text alone.
"""
from backend.security.output_validator import OutputValidator
from backend.security.pii import PIIDetector


class TestItFindsRealPII:
    def test_email(self):
        assert "email" in PIIDetector().detect("write to jane.doe@bank.com")

    def test_ssn(self):
        assert "ssn" in PIIDetector().detect("SSN 123-45-6789")

    def test_credit_card(self):
        assert "credit_card" in PIIDetector().detect("card 4111-1111-1111-1111")

    def test_masking_removes_the_value(self):
        masked = PIIDetector().mask("contact jane.doe@bank.com today")

        assert "jane.doe@bank.com" not in masked
        assert "REDACTED" in masked

    def test_masking_keeps_the_rest_of_the_sentence(self):
        masked = PIIDetector().mask("contact jane.doe@bank.com today")

        assert masked.startswith("contact ")
        assert masked.endswith(" today")


class TestItLeavesFinancialTextAlone:
    def test_a_year_range_is_not_a_phone_number(self):
        assert PIIDetector().detect("revenue grew from 2024 to 2026") == {}

    def test_a_price_target_is_not_pii(self):
        assert PIIDetector().detect("Morgan Stanley raised its target to $179") == {}

    def test_a_large_market_cap_is_not_a_card_number(self):
        assert PIIDetector().detect("market cap of 5252323999744") == {}

    def test_a_pe_ratio_is_not_pii(self):
        assert PIIDetector().detect("Intel trades at 33.20827 times earnings") == {}


class TestOutputValidation:
    def test_it_masks_pii_in_a_report(self):
        result = OutputValidator().validate("Reach the CFO at cfo@corp.com.")

        assert "cfo@corp.com" not in result.output
        assert result.findings

    def test_it_blocks_a_leaked_secret(self):
        result = OutputValidator().validate("The api_key is sk-abc123def456.")

        assert result.blocked

    def test_a_normal_report_passes_untouched(self):
        text = (
            "NVIDIA has the strongest coverage: CoreWeave signed a "
            "multibillion-dollar agreement for access to NVIDIA systems."
        )
        result = OutputValidator().validate(text)

        assert not result.blocked
        assert result.output == text
        assert not result.findings

    def test_it_does_not_trip_on_the_word_key(self):
        """"Key metrics" and "key takeaway" are everywhere in this domain."""
        result = OutputValidator().validate(
            "The key metrics are revenue growth and margin."
        )

        assert not result.blocked
