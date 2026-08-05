"""Tests for PII/PHI detection and redaction."""

from src.privacy import DataRedactor, PHIDetector, PIIDetector, PrivacyGuard


def test_pii_detects_email():
    findings = PIIDetector.detect_all("Contact john@example.com")
    assert len(findings) >= 1
    assert any(f.data_type.value == "email" for f in findings)


def test_pii_detects_ssn():
    findings = PIIDetector.detect_all("SSN 123-45-6789")
    assert any(f.data_type.value == "ssn" for f in findings)


def test_phi_detects_medical_condition():
    findings = PHIDetector.detect_all("Patient diagnosed with diabetes")
    assert len(findings) >= 1


def test_rag_questions_have_no_false_positives():
    q = "What is retrieval-augmented generation?"
    assert PIIDetector.detect_all(q) == []
    assert PHIDetector.detect_all(q) == []


def test_redact_pii():
    text = "Email: john@example.com"
    redacted = DataRedactor.redact_pii(text)
    assert "john@example.com" not in redacted
    assert "[EMAIL]" in redacted


def test_privacy_blocks_pii_input():
    ok, _ = PrivacyGuard.check_input("My email is test@example.com")
    assert not ok


def test_privacy_allows_informational_phi_questions():
    """Mentioning a medical term is not a privacy violation — output is redacted instead."""
    ok, findings = PrivacyGuard.check_input("What treatments exist for diabetes?")
    assert ok
    assert len(findings) >= 1  # still detected, just not blocking


def test_nine_digit_numbers_are_not_ssn():
    """Bare 9-digit numbers (IDs, counts) must not trigger SSN detection."""
    findings = PIIDetector.detect_all("The dataset has 123456789 rows")
    assert not any(f.data_type.value == "ssn" for f in findings)
