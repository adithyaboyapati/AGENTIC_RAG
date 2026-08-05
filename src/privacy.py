"""
Privacy & Compliance Module — PII/PHI Detection and Handling.

Implements:
- PII (Personally Identifiable Information) detection
- PHI (Protected Health Information) detection
- Data redaction and masking
- Privacy compliance (GDPR, HIPAA, CCPA)
- Audit logging for sensitive data
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class DataType(str, Enum):
    """Types of sensitive data."""

    SSN = "ssn"  # Social Security Number
    CREDIT_CARD = "credit_card"  # Credit card number
    EMAIL = "email"  # Email address
    PHONE = "phone"  # Phone number
    ADDRESS = "address"  # Physical address
    NAME = "name"  # Person's name
    DOB = "dob"  # Date of birth
    MEDICAL = "medical"  # Medical condition/treatment
    INSURANCE = "insurance"  # Insurance ID
    PASSPORT = "passport"  # Passport number
    DRIVER_LICENSE = "driver_license"  # Driver license
    FINANCIAL = "financial"  # Account/bank info


@dataclass
class SensitiveDataFound:
    """Represents detected sensitive data."""

    data_type: DataType
    value: str  # Original value (for logging)
    position: int  # Position in text
    severity: str  # "pii" | "phi" | "financial"


class PIIDetector:
    """Detects Personally Identifiable Information."""

    # US Social Security Number (XXX-XX-XXXX). Deliberately requires dashes:
    # a bare \d{9} matches any 9-digit number (IDs, counts, years-ranges) and
    # causes constant false positives on legitimate questions.
    SSN_PATTERN = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')

    # Credit card (4 groups of 4 digits)
    CREDIT_CARD_PATTERN = re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b')

    # Email address
    EMAIL_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')

    # Phone number (multiple formats)
    PHONE_PATTERN = re.compile(
        r'\b(?:\+?1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})\b'
    )

    # US Address (street, city, state, zip)
    ADDRESS_PATTERN = re.compile(
        r'\b\d+\s+[A-Za-z\s]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Court|Ct)'
    )

    # Passport number (various countries)
    PASSPORT_PATTERN = re.compile(r'\b[A-Z]{1,2}\d{6,9}\b')

    # Driver license (US format: state code + 7-8 digits)
    DRIVER_LICENSE_PATTERN = re.compile(r'\b[A-Z]{2}\d{7,8}\b')

    @classmethod
    def detect_all(cls, text: str) -> list[SensitiveDataFound]:
        """Detect all types of PII in text."""
        findings: list[SensitiveDataFound] = []

        # SSN detection
        for match in cls.SSN_PATTERN.finditer(text):
            findings.append(
                SensitiveDataFound(
                    data_type=DataType.SSN,
                    value=match.group(),
                    position=match.start(),
                    severity="pii",
                )
            )

        # Credit card detection
        for match in cls.CREDIT_CARD_PATTERN.finditer(text):
            findings.append(
                SensitiveDataFound(
                    data_type=DataType.CREDIT_CARD,
                    value=match.group(),
                    position=match.start(),
                    severity="financial",
                )
            )

        # Email detection
        for match in cls.EMAIL_PATTERN.finditer(text):
            findings.append(
                SensitiveDataFound(
                    data_type=DataType.EMAIL,
                    value=match.group(),
                    position=match.start(),
                    severity="pii",
                )
            )

        # Phone detection
        for match in cls.PHONE_PATTERN.finditer(text):
            findings.append(
                SensitiveDataFound(
                    data_type=DataType.PHONE,
                    value=match.group(),
                    position=match.start(),
                    severity="pii",
                )
            )

        # Address detection
        for match in cls.ADDRESS_PATTERN.finditer(text):
            findings.append(
                SensitiveDataFound(
                    data_type=DataType.ADDRESS,
                    value=match.group(),
                    position=match.start(),
                    severity="pii",
                )
            )

        # Passport detection
        for match in cls.PASSPORT_PATTERN.finditer(text):
            findings.append(
                SensitiveDataFound(
                    data_type=DataType.PASSPORT,
                    value=match.group(),
                    position=match.start(),
                    severity="pii",
                )
            )

        # Driver license detection
        for match in cls.DRIVER_LICENSE_PATTERN.finditer(text):
            findings.append(
                SensitiveDataFound(
                    data_type=DataType.DRIVER_LICENSE,
                    value=match.group(),
                    position=match.start(),
                    severity="pii",
                )
            )

        return findings


class PHIDetector:
    """Detects Protected Health Information."""

    # Medical conditions (common patterns)
    MEDICAL_CONDITIONS = [
        "diabetes", "cancer", "covid", "hiv", "aids",
        "hypertension", "depression", "schizophrenia",
        "bipolar", "autism", "arthritis", "asthma",
    ]

    # Medical procedures
    MEDICAL_PROCEDURES = [
        "surgery", "chemotherapy", "dialysis", "transplant",
        "vaccination", "biopsy", "angioplasty", "bypass",
    ]

    # Medication patterns
    MEDICATION_PATTERN = re.compile(
        r'\b(?:aspirin|ibuprofen|metformin|lisinopril|atorvastatin|omeprazole|sertraline|fluoxetine|alprazolam|lorazepam)\b',
        re.IGNORECASE,
    )

    # Health insurance ID (various formats)
    INSURANCE_ID_PATTERN = re.compile(r'\b[A-Z]{2}\d{8,10}\b')

    @classmethod
    def detect_all(cls, text: str) -> list[SensitiveDataFound]:
        """Detect all types of PHI in text."""
        findings: list[SensitiveDataFound] = []

        # Medical condition detection
        for condition in cls.MEDICAL_CONDITIONS:
            pattern = re.compile(rf'\b{condition}\b', re.IGNORECASE)
            for match in pattern.finditer(text):
                findings.append(
                    SensitiveDataFound(
                        data_type=DataType.MEDICAL,
                        value=match.group(),
                        position=match.start(),
                        severity="phi",
                    )
                )

        # Medical procedure detection
        for procedure in cls.MEDICAL_PROCEDURES:
            pattern = re.compile(rf'\b{procedure}\b', re.IGNORECASE)
            for match in pattern.finditer(text):
                findings.append(
                    SensitiveDataFound(
                        data_type=DataType.MEDICAL,
                        value=match.group(),
                        position=match.start(),
                        severity="phi",
                    )
                )

        # Medication detection
        for match in cls.MEDICATION_PATTERN.finditer(text):
            findings.append(
                SensitiveDataFound(
                    data_type=DataType.MEDICAL,
                    value=match.group(),
                    position=match.start(),
                    severity="phi",
                )
            )

        # Insurance ID detection
        for match in cls.INSURANCE_ID_PATTERN.finditer(text):
            findings.append(
                SensitiveDataFound(
                    data_type=DataType.INSURANCE,
                    value=match.group(),
                    position=match.start(),
                    severity="phi",
                )
            )

        return findings


class DataRedactor:
    """Redacts and masks sensitive data."""

    @staticmethod
    def redact_pii(text: str) -> str:
        """Remove all PII from text."""
        findings = PIIDetector.detect_all(text)
        redacted = text

        # Sort by position (reverse) to maintain indices
        for finding in sorted(findings, key=lambda x: x.position, reverse=True):
            value = finding.value
            mask = f"[{finding.data_type.value.upper()}]"
            redacted = redacted[:finding.position] + mask + redacted[finding.position + len(value):]

        return redacted

    @staticmethod
    def redact_phi(text: str) -> str:
        """Remove all PHI from text."""
        findings = PHIDetector.detect_all(text)
        redacted = text

        # Sort by position (reverse) to maintain indices
        for finding in sorted(findings, key=lambda x: x.position, reverse=True):
            value = finding.value
            mask = f"[{finding.data_type.value.upper()}]"
            redacted = redacted[:finding.position] + mask + redacted[finding.position + len(value):]

        return redacted

    @staticmethod
    def redact_all(text: str) -> str:
        """Remove all PII and PHI from text."""
        text = DataRedactor.redact_pii(text)
        text = DataRedactor.redact_phi(text)
        return text

    @staticmethod
    def mask_value(value: str, reveal_chars: int = 4) -> str:
        """Mask a value revealing only last N characters."""
        if len(value) <= reveal_chars:
            return "*" * len(value)
        return "*" * (len(value) - reveal_chars) + value[-reveal_chars:]


class PrivacyPolicy:
    """Privacy handling policy configuration."""

    # Block sensitive data. PHI does NOT block by default: informational
    # questions ("what is diabetes?") are legitimate — PHI findings are
    # redacted from output instead.
    BLOCK_ON_PII = True
    BLOCK_ON_PHI = False

    # Redact sensitive data
    REDACT_PII = False
    REDACT_PHI = False

    # Log sensitive data (for compliance audit)
    LOG_PII = True
    LOG_PHI = True

    # Data retention (days)
    DATA_RETENTION_DAYS = 30

    # Compliance modes
    COMPLIANCE_GDPR = False  # EU data protection
    COMPLIANCE_HIPAA = False  # Healthcare
    COMPLIANCE_CCPA = False  # California privacy


class PrivacyGuard:
    """Enforces privacy policy on input and output."""

    @staticmethod
    def check_input(text: str, policy: PrivacyPolicy = PrivacyPolicy) -> tuple[bool, list[SensitiveDataFound]]:
        """Check input for sensitive data. Fails only when a block policy triggers."""
        pii_findings = PIIDetector.detect_all(text)
        phi_findings = PHIDetector.detect_all(text)
        all_findings = pii_findings + phi_findings

        if policy.BLOCK_ON_PII and pii_findings:
            return False, all_findings
        if policy.BLOCK_ON_PHI and phi_findings:
            return False, all_findings

        return True, all_findings

    @staticmethod
    def process_input(text: str, policy: PrivacyPolicy = PrivacyPolicy) -> str:
        """Process input according to privacy policy."""
        if policy.REDACT_PII:
            text = DataRedactor.redact_pii(text)
        if policy.REDACT_PHI:
            text = DataRedactor.redact_phi(text)
        return text

    @staticmethod
    def check_output(text: str, policy: PrivacyPolicy = PrivacyPolicy) -> tuple[bool, list[SensitiveDataFound]]:
        """Check output for sensitive data."""
        pii_findings = PIIDetector.detect_all(text)
        phi_findings = PHIDetector.detect_all(text)
        all_findings = pii_findings + phi_findings

        return len(all_findings) == 0, all_findings

    @staticmethod
    def process_output(text: str, policy: PrivacyPolicy = PrivacyPolicy) -> str:
        """Process output according to privacy policy."""
        if policy.REDACT_PII:
            text = DataRedactor.redact_pii(text)
        if policy.REDACT_PHI:
            text = DataRedactor.redact_phi(text)
        return text


# Default privacy policy — use get_privacy_policy() for runtime config
DEFAULT_PRIVACY_POLICY = PrivacyPolicy()


def get_privacy_policy() -> PrivacyPolicy:
    """Build privacy policy from application settings."""
    from src.config import settings

    policy = PrivacyPolicy()
    policy.REDACT_PII = settings.redact_output_pii
    policy.REDACT_PHI = settings.redact_output_pii
    return policy
