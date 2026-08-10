"""
Privacy & Compliance — PII/PHI detection, redaction, and policy enforcement.

Design notes (why this is not a naive keyword matcher):

- **Shape alone is not identity.** ``AB12345678`` is a chunk ID far more often
  than a driver's licence, so identifier patterns require a *label* ("passport
  no:", "policy #") before they fire. Credit cards must additionally pass a
  Luhn check.
- **A topic mention is not a disclosure.** "What is diabetes?" and "you can
  bypass the cache" must not be treated as protected health information, so
  PHI terms require clinical/possessive context ("patient", "diagnosed with",
  "my", "prescribed") within a short window.
- **PII and PHI are separate risk classes** with separate switches. Redacting
  PHI is opt-in; redacting PII is on by default.

Policy is expressed as two modes (``off`` | ``redact`` | ``block``), one for
input and one for output, so behaviour is a single explicit knob per direction
rather than an implicit combination of booleans.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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


class PrivacyMode(str, Enum):
    """What to do when sensitive data is detected."""

    OFF = "off"  # detect nothing, pass through untouched
    REDACT = "redact"  # mask the sensitive span and continue
    BLOCK = "block"  # reject the request/response outright

    @classmethod
    def parse(cls, value: str | None, default: PrivacyMode) -> PrivacyMode:
        try:
            return cls((value or "").strip().lower())
        except ValueError:
            return default


@dataclass
class SensitiveDataFound:
    """Represents detected sensitive data."""

    data_type: DataType
    value: str  # Original matched value (for logging)
    position: int  # Start offset of the sensitive span in the text
    severity: str  # "pii" | "phi" | "financial"
    end: int = 0  # End offset; defaults to position + len(value)

    def __post_init__(self) -> None:
        if not self.end:
            self.end = self.position + len(self.value)


# ---------------------------------------------------------------------------
# Shared matching helpers
# ---------------------------------------------------------------------------

# Label that must precede a bare identifier before we treat it as sensitive.
_ID_LABEL = (
    r"(?:passport|driver'?s?\s+licen[cs]e|licen[cs]e|\bdl\b|policy|member|"
    r"subscriber|insurance|medicaid|medicare|health\s+plan)"
    r"\s*(?:no\.?|number|num|#|id)?\s*[:#=-]?\s*"
)

# Clinical / possessive cues that turn a medical *term* into a medical *fact
# about a person*. Matched in a window immediately around the term.
_CLINICAL_CONTEXT = re.compile(
    r"\b(?:patient|patients|diagnos(?:ed|is|es)|suffer(?:s|ing)?\s+from|"
    r"treated\s+for|treatment\s+for|undergoing|underwent|scheduled\s+for|"
    r"prescrib(?:ed|ing)|prescription|dosage|dose|mg\b|history\s+of|"
    r"admitted|hospitaliz(?:ed|ation)|medical\s+record|mrn\b|chart\b|"
    r"my|his|her|their|your|our)\b",
    re.IGNORECASE,
)

_CONTEXT_CHARS_BEFORE = 64
_CONTEXT_CHARS_AFTER = 24


def _has_clinical_context(text: str, start: int, end: int) -> bool:
    """True when a medical term sits next to a cue that makes it person-specific."""
    window = text[max(0, start - _CONTEXT_CHARS_BEFORE) : end + _CONTEXT_CHARS_AFTER]
    return bool(_CLINICAL_CONTEXT.search(window))


def _luhn_valid(digits: str) -> bool:
    """Luhn checksum — rejects arbitrary 16-digit runs (IDs, hashes, timestamps)."""
    nums = [int(c) for c in digits if c.isdigit()]
    if len(nums) < 13:
        return False
    total = 0
    for i, digit in enumerate(reversed(nums)):
        if i % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


@dataclass(frozen=True)
class _Rule:
    """One detection rule.

    ``group`` selects which capture group is the sensitive span, so a rule can
    require surrounding context (a label) without redacting that context.
    """

    data_type: DataType
    severity: str
    pattern: re.Pattern[str]
    group: int = 0
    validator: object = None  # Callable[[str], bool] | None


def _scan(text: str, rules: list[_Rule]) -> list[SensitiveDataFound]:
    findings: list[SensitiveDataFound] = []
    for rule in rules:
        for match in rule.pattern.finditer(text):
            value = match.group(rule.group)
            if not value:
                continue
            if rule.validator is not None and not rule.validator(value):  # type: ignore[operator]
                continue
            start, end = match.span(rule.group)
            findings.append(
                SensitiveDataFound(
                    data_type=rule.data_type,
                    value=value,
                    position=start,
                    severity=rule.severity,
                    end=end,
                )
            )
    return findings


class PIIDetector:
    """Detects Personally Identifiable Information."""

    # US Social Security Number (XXX-XX-XXXX). Deliberately requires dashes:
    # a bare \d{9} matches any 9-digit number (IDs, counts, year ranges).
    SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

    # Credit card: 4 groups of 4 digits AND a valid Luhn checksum. Without the
    # checksum this fires on order numbers, hashes, and epoch timestamps.
    CREDIT_CARD_PATTERN = re.compile(r"\b(?:\d{4}[\s-]?){3}\d{4}\b")

    EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

    # Phone number (multiple formats)
    PHONE_PATTERN = re.compile(
        r"\b(?:\+?1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})\b"
    )

    # US Address (street number + name + thoroughfare suffix)
    ADDRESS_PATTERN = re.compile(
        r"\b\d+\s+[A-Za-z\s]+"
        r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Court|Ct)\b"
    )

    # Identifier shapes are ambiguous on their own (chunk IDs, SKUs, model
    # names all match), so they must be introduced by an explicit label.
    PASSPORT_PATTERN = re.compile(
        rf"{_ID_LABEL}([A-Z]{{1,2}}\d{{6,9}})\b", re.IGNORECASE
    )
    DRIVER_LICENSE_PATTERN = re.compile(
        rf"{_ID_LABEL}([A-Z]{{1,2}}\d{{6,9}})\b", re.IGNORECASE
    )

    _RULES: list[_Rule] = [
        _Rule(DataType.SSN, "pii", SSN_PATTERN),
        _Rule(DataType.CREDIT_CARD, "financial", CREDIT_CARD_PATTERN, validator=_luhn_valid),
        _Rule(DataType.EMAIL, "pii", EMAIL_PATTERN),
        _Rule(DataType.PHONE, "pii", PHONE_PATTERN),
        _Rule(DataType.ADDRESS, "pii", ADDRESS_PATTERN),
        _Rule(DataType.PASSPORT, "pii", PASSPORT_PATTERN, group=1),
    ]

    @classmethod
    def detect_all(cls, text: str) -> list[SensitiveDataFound]:
        """Detect all types of PII in text."""
        return _scan(text or "", cls._RULES)


class PHIDetector:
    """Detects Protected Health Information.

    Condition / procedure / medication terms only count when they appear next
    to clinical or possessive context — otherwise every technical document
    that says "bypass", "COVID", or "recovery" is misclassified as PHI.
    """

    MEDICAL_CONDITIONS = [
        "diabetes", "cancer", "covid", "hiv", "aids",
        "hypertension", "depression", "schizophrenia",
        "bipolar", "autism", "arthritis", "asthma",
    ]

    # NOTE: ordinary English words that double as procedures ("bypass",
    # "recovery", "screening") are deliberately excluded — the false-positive
    # rate on technical prose is far worse than the miss rate.
    MEDICAL_PROCEDURES = [
        "chemotherapy", "dialysis", "transplant",
        "biopsy", "angioplasty", "mastectomy", "colonoscopy",
    ]

    # "surgery" and "vaccination" are common in non-clinical prose, so they are
    # matched only in an unambiguous possessive/clinical construction.
    CONTEXT_ONLY_PROCEDURES = ["surgery", "vaccination", "immunization"]

    MEDICATION_PATTERN = re.compile(
        r"\b(?:metformin|lisinopril|atorvastatin|omeprazole|sertraline|"
        r"fluoxetine|alprazolam|lorazepam|insulin|warfarin)\b",
        re.IGNORECASE,
    )

    # Health insurance / member IDs require a label for the same reason as
    # passports: the bare shape collides with internal identifiers.
    INSURANCE_ID_PATTERN = re.compile(
        rf"{_ID_LABEL}([A-Z]{{2}}\d{{6,10}})\b", re.IGNORECASE
    )

    # Medical record number is unambiguous when labelled.
    MRN_PATTERN = re.compile(r"\bMRN\s*[:#=-]?\s*([A-Z0-9-]{5,12})\b", re.IGNORECASE)

    @classmethod
    def _term_pattern(cls, term: str) -> re.Pattern[str]:
        return re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)

    @classmethod
    def detect_all(cls, text: str) -> list[SensitiveDataFound]:
        """Detect PHI that is attributable to a person."""
        text = text or ""
        findings: list[SensitiveDataFound] = []

        context_terms = (
            cls.MEDICAL_CONDITIONS
            + cls.MEDICAL_PROCEDURES
            + cls.CONTEXT_ONLY_PROCEDURES
        )
        for term in context_terms:
            for match in cls._term_pattern(term).finditer(text):
                if not _has_clinical_context(text, match.start(), match.end()):
                    continue
                findings.append(
                    SensitiveDataFound(
                        data_type=DataType.MEDICAL,
                        value=match.group(),
                        position=match.start(),
                        severity="phi",
                        end=match.end(),
                    )
                )

        for match in cls.MEDICATION_PATTERN.finditer(text):
            if not _has_clinical_context(text, match.start(), match.end()):
                continue
            findings.append(
                SensitiveDataFound(
                    data_type=DataType.MEDICAL,
                    value=match.group(),
                    position=match.start(),
                    severity="phi",
                    end=match.end(),
                )
            )

        findings.extend(
            _scan(
                text,
                [
                    _Rule(DataType.INSURANCE, "phi", cls.INSURANCE_ID_PATTERN, group=1),
                    _Rule(DataType.MEDICAL, "phi", cls.MRN_PATTERN, group=1),
                ],
            )
        )

        return findings


class DataRedactor:
    """Redacts and masks sensitive data."""

    @staticmethod
    def _apply(text: str, findings: list[SensitiveDataFound]) -> str:
        """Replace each finding with a type marker, innermost-last.

        Overlapping findings (an email inside an address, say) are collapsed so
        a span is never rewritten twice.
        """
        if not findings:
            return text

        ordered = sorted(findings, key=lambda f: (f.position, -f.end))
        merged: list[SensitiveDataFound] = []
        for finding in ordered:
            if merged and finding.position < merged[-1].end:
                continue  # contained in / overlapping an already-kept span
            merged.append(finding)

        redacted = text
        for finding in reversed(merged):
            mask = f"[{finding.data_type.value.upper()}]"
            redacted = redacted[: finding.position] + mask + redacted[finding.end :]
        return redacted

    @staticmethod
    def redact_pii(text: str) -> str:
        """Remove all PII from text."""
        return DataRedactor._apply(text, PIIDetector.detect_all(text))

    @staticmethod
    def redact_phi(text: str) -> str:
        """Remove all PHI from text."""
        return DataRedactor._apply(text, PHIDetector.detect_all(text))

    @staticmethod
    def redact_all(text: str) -> str:
        """Remove all PII and PHI from text."""
        findings = PIIDetector.detect_all(text) + PHIDetector.detect_all(text)
        return DataRedactor._apply(text, findings)

    @staticmethod
    def mask_value(value: str, reveal_chars: int = 4) -> str:
        """Mask a value revealing only last N characters."""
        if len(value) <= reveal_chars:
            return "*" * len(value)
        return "*" * (len(value) - reveal_chars) + value[-reveal_chars:]


@dataclass
class PrivacyPolicy:
    """Runtime privacy policy.

    ``input_mode`` / ``output_mode`` are the only behavioural switches;
    ``detect_phi`` decides whether PHI participates at all.
    """

    input_mode: PrivacyMode = PrivacyMode.REDACT
    output_mode: PrivacyMode = PrivacyMode.REDACT
    # PHI detection is opt-in: for a general-purpose corpus it produces more
    # noise than signal, and it is only meaningful under HIPAA-style handling.
    detect_phi: bool = False
    # Compliance flags (documentation / audit only — see docs/PRIVACY_COMPLIANCE.md)
    compliance_gdpr: bool = False
    compliance_hipaa: bool = False
    compliance_ccpa: bool = False
    data_retention_days: int = 30
    log_findings: bool = True

    # Legacy attribute names kept so existing call sites / tests keep working.
    @property
    def BLOCK_ON_PII(self) -> bool:  # noqa: N802 — legacy name
        return self.input_mode is PrivacyMode.BLOCK

    @property
    def BLOCK_ON_PHI(self) -> bool:  # noqa: N802 — legacy name
        return self.detect_phi and self.input_mode is PrivacyMode.BLOCK

    @property
    def REDACT_PII(self) -> bool:  # noqa: N802 — legacy name
        return self.output_mode is PrivacyMode.REDACT

    @property
    def REDACT_PHI(self) -> bool:  # noqa: N802 — legacy name
        return self.detect_phi and self.output_mode is PrivacyMode.REDACT


@dataclass
class PrivacyResult:
    """Outcome of applying the policy to one piece of text."""

    allowed: bool
    text: str
    findings: list[SensitiveDataFound] = field(default_factory=list)

    @property
    def redacted(self) -> bool:
        return bool(self.findings) and self.allowed


class PrivacyGuard:
    """Enforces the privacy policy on input and output."""

    @staticmethod
    def _detect(text: str, policy: PrivacyPolicy) -> list[SensitiveDataFound]:
        findings = PIIDetector.detect_all(text)
        if policy.detect_phi:
            findings += PHIDetector.detect_all(text)
        return findings

    @staticmethod
    def apply_input(text: str, policy: PrivacyPolicy | None = None) -> PrivacyResult:
        """Detect → (redact | block | pass) for a user question."""
        policy = policy or get_privacy_policy()
        if policy.input_mode is PrivacyMode.OFF:
            return PrivacyResult(allowed=True, text=text, findings=[])

        findings = PrivacyGuard._detect(text, policy)
        if not findings:
            return PrivacyResult(allowed=True, text=text, findings=[])

        if policy.input_mode is PrivacyMode.BLOCK:
            return PrivacyResult(allowed=False, text=text, findings=findings)

        return PrivacyResult(
            allowed=True,
            text=DataRedactor._apply(text, findings),
            findings=findings,
        )

    @staticmethod
    def apply_output(text: str, policy: PrivacyPolicy | None = None) -> PrivacyResult:
        """Detect → (redact | block | pass) for a generated answer."""
        policy = policy or get_privacy_policy()
        if policy.output_mode is PrivacyMode.OFF:
            return PrivacyResult(allowed=True, text=text, findings=[])

        findings = PrivacyGuard._detect(text, policy)
        if not findings:
            return PrivacyResult(allowed=True, text=text, findings=[])

        if policy.output_mode is PrivacyMode.BLOCK:
            return PrivacyResult(allowed=False, text=text, findings=findings)

        return PrivacyResult(
            allowed=True,
            text=DataRedactor._apply(text, findings),
            findings=findings,
        )

    # ------------------------------------------------------------------
    # Back-compatible surface
    # ------------------------------------------------------------------

    @staticmethod
    def check_input(
        text: str, policy: PrivacyPolicy | None = None
    ) -> tuple[bool, list[SensitiveDataFound]]:
        """Check input. Fails only when the input mode is ``block``."""
        result = PrivacyGuard.apply_input(text, policy)
        return result.allowed, result.findings

    @staticmethod
    def process_input(text: str, policy: PrivacyPolicy | None = None) -> str:
        return PrivacyGuard.apply_input(text, policy).text

    @staticmethod
    def check_output(
        text: str, policy: PrivacyPolicy | None = None
    ) -> tuple[bool, list[SensitiveDataFound]]:
        """Report whether the output is clean. ``False`` means findings exist."""
        policy = policy or get_privacy_policy()
        if policy.output_mode is PrivacyMode.OFF:
            return True, []
        findings = PrivacyGuard._detect(text, policy)
        return len(findings) == 0, findings

    @staticmethod
    def process_output(text: str, policy: PrivacyPolicy | None = None) -> str:
        return PrivacyGuard.apply_output(text, policy).text


def get_privacy_policy() -> PrivacyPolicy:
    """Build the privacy policy from application settings."""
    from src.config import settings

    return PrivacyPolicy(
        input_mode=PrivacyMode.parse(settings.privacy_input_mode, PrivacyMode.REDACT),
        output_mode=PrivacyMode.parse(settings.privacy_output_mode, PrivacyMode.REDACT),
        detect_phi=settings.privacy_detect_phi,
        data_retention_days=settings.privacy_retention_days,
    )


# Default policy for callers that do not thread settings through.
DEFAULT_PRIVACY_POLICY = PrivacyPolicy()
