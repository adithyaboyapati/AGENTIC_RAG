"""Tests for PII/PHI detection, redaction, and policy modes.

The false-positive tests matter as much as the detection tests: an
over-eager privacy filter silently corrupts correct answers, which is a worse
failure than missing a redaction on a corpus that contains no PII.
"""

import pytest

from src.privacy import (
    DataRedactor,
    PHIDetector,
    PIIDetector,
    PrivacyGuard,
    PrivacyMode,
    PrivacyPolicy,
)

REDACT = PrivacyPolicy(input_mode=PrivacyMode.REDACT, output_mode=PrivacyMode.REDACT)
BLOCK = PrivacyPolicy(input_mode=PrivacyMode.BLOCK, output_mode=PrivacyMode.BLOCK)
OFF = PrivacyPolicy(input_mode=PrivacyMode.OFF, output_mode=PrivacyMode.OFF)
CLINICAL = PrivacyPolicy(detect_phi=True)


# ---------------------------------------------------------------------------
# True positives
# ---------------------------------------------------------------------------


def test_pii_detects_email():
    findings = PIIDetector.detect_all("Contact john@example.com")
    assert any(f.data_type.value == "email" for f in findings)


def test_pii_detects_ssn():
    findings = PIIDetector.detect_all("SSN 123-45-6789")
    assert any(f.data_type.value == "ssn" for f in findings)


def test_pii_detects_luhn_valid_credit_card():
    findings = PIIDetector.detect_all("Card 4242 4242 4242 4242 on file")
    assert any(f.data_type.value == "credit_card" for f in findings)


def test_pii_detects_labelled_passport():
    findings = PIIDetector.detect_all("Passport No: AB1234567 was verified")
    assert any(f.data_type.value == "passport" for f in findings)


def test_phi_detects_medical_condition_in_clinical_context():
    findings = PHIDetector.detect_all("Patient diagnosed with diabetes")
    assert findings
    assert all(f.severity == "phi" for f in findings)


def test_phi_detects_possessive_condition():
    assert PHIDetector.detect_all("my asthma has been getting worse")


def test_redact_pii():
    redacted = DataRedactor.redact_pii("Email: john@example.com")
    assert "john@example.com" not in redacted
    assert "[EMAIL]" in redacted


# ---------------------------------------------------------------------------
# False positives — these are the regressions that matter
# ---------------------------------------------------------------------------


def test_rag_questions_have_no_false_positives():
    q = "What is retrieval-augmented generation?"
    assert PIIDetector.detect_all(q) == []
    assert PHIDetector.detect_all(q) == []


def test_nine_digit_numbers_are_not_ssn():
    findings = PIIDetector.detect_all("The dataset has 123456789 rows")
    assert not any(f.data_type.value == "ssn" for f in findings)


def test_sixteen_digit_non_card_is_not_a_credit_card():
    """Order numbers and hashes must fail the Luhn check."""
    findings = PIIDetector.detect_all("Order 1234567812345678 shipped")
    assert not any(f.data_type.value == "credit_card" for f in findings)


def test_chunk_ids_are_not_identifiers():
    """Bare ID shapes collide with our own chunk IDs — they need a label."""
    text = "Chunk ID AB12345678 was retrieved from page 4"
    findings = PIIDetector.detect_all(text)
    assert not any(
        f.data_type.value in {"passport", "driver_license"} for f in findings
    )


@pytest.mark.parametrize(
    "text",
    [
        "You can bypass the cache by setting CACHE_ENABLED=false.",
        "The COVID dataset is indexed in Chroma.",
        "Recovery from a failed ingest is automatic.",
        "What treatments exist for diabetes?",
    ],
)
def test_technical_prose_is_not_phi(text):
    """A topic mention is not a disclosure about a person."""
    assert PHIDetector.detect_all(text) == []


def test_output_redaction_leaves_technical_answers_untouched():
    answer = "You can bypass the cache; see the COVID dataset example."
    assert PrivacyGuard.apply_output(answer, REDACT).text == answer


# ---------------------------------------------------------------------------
# Policy modes
# ---------------------------------------------------------------------------


def test_redact_mode_allows_and_masks_input():
    result = PrivacyGuard.apply_input("Email me at test@example.com", REDACT)
    assert result.allowed
    assert "test@example.com" not in result.text
    assert "[EMAIL]" in result.text


def test_block_mode_rejects_input():
    result = PrivacyGuard.apply_input("My SSN is 123-45-6789", BLOCK)
    assert not result.allowed
    assert any(f.data_type.value == "ssn" for f in result.findings)


def test_off_mode_passes_through():
    text = "My SSN is 123-45-6789"
    result = PrivacyGuard.apply_input(text, OFF)
    assert result.allowed
    assert result.text == text
    assert result.findings == []


def test_phi_is_opt_in():
    text = "Patient diagnosed with diabetes"
    assert PrivacyGuard.apply_output(text, REDACT).text == text  # detect_phi=False
    assert "[MEDICAL]" in PrivacyGuard.apply_output(text, CLINICAL).text


def test_block_mode_rejects_output():
    result = PrivacyGuard.apply_output("Reach me at a@b.com", BLOCK)
    assert not result.allowed


def test_overlapping_findings_are_not_double_redacted():
    """A span must never be rewritten twice into nested markers."""
    text = "Write to john@example.com or call 555-123-4567."
    redacted = PrivacyGuard.apply_output(text, REDACT).text
    assert "[[" not in redacted
    assert redacted.count("[EMAIL]") == 1


def test_legacy_policy_aliases_track_modes():
    assert BLOCK.BLOCK_ON_PII is True
    assert REDACT.BLOCK_ON_PII is False
    assert REDACT.REDACT_PII is True
    assert REDACT.REDACT_PHI is False  # PHI opt-in
    assert CLINICAL.REDACT_PHI is True
