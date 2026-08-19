"""
Production Guardrails — Safety, Cost Control, and Quality Assurance.

Implements:
- Input validation (length, content safety)
- Output filtering (quality, safety)
- Rate limiting (queries per minute)
- Cost tracking (token usage)
- Confidence thresholds (quality gates)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from src.config import settings


class RateLimitError(Exception):
    """Raised when a request exceeds rate or budget limits (maps to HTTP 429)."""


@dataclass
class GuardrailViolation:
    """Represents a guardrail violation."""

    rule: str
    message: str
    severity: str  # "warning" | "error"
    value: float | str
    limit: float | str


class InputGuardrails:
    """Validates user input before processing."""

    # Maximum question length (words)
    MAX_QUESTION_LENGTH = 500

    # Maximum question length (characters)
    MAX_QUESTION_CHARS = 3000

    # Minimum question length (characters)
    MIN_QUESTION_CHARS = 3

    # Credential-shaped strings. Intentionally NOT a plain-word blocklist:
    # blocking words like "token" or "secret" rejects legitimate questions
    # ("what is a token limit?"). These match actual secret material instead.
    CREDENTIAL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
        ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
        ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
        ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
        ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
        ("password_assignment", re.compile(r"\bpassword\s*[:=]\s*\S+", re.IGNORECASE)),
        ("api_key_assignment", re.compile(r"\bapi[_-]?key\s*[:=]\s*\S+", re.IGNORECASE)),
        ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}", re.IGNORECASE)),
    ]

    @classmethod
    def validate(cls, question: str) -> tuple[bool, list[GuardrailViolation]]:
        """
        Validate user input.

        Returns:
            (is_valid, violations)
        """
        violations: list[GuardrailViolation] = []

        # Check length
        if len(question) < cls.MIN_QUESTION_CHARS:
            violations.append(
                GuardrailViolation(
                    rule="min_length",
                    message=f"Question too short (minimum {cls.MIN_QUESTION_CHARS} characters)",
                    severity="error",
                    value=len(question),
                    limit=cls.MIN_QUESTION_CHARS,
                )
            )

        if len(question) > cls.MAX_QUESTION_CHARS:
            violations.append(
                GuardrailViolation(
                    rule="max_length",
                    message=f"Question too long (maximum {cls.MAX_QUESTION_CHARS} characters)",
                    severity="error",
                    value=len(question),
                    limit=cls.MAX_QUESTION_CHARS,
                )
            )

        # Check word count
        word_count = len(question.split())
        if word_count > cls.MAX_QUESTION_LENGTH:
            violations.append(
                GuardrailViolation(
                    rule="max_words",
                    message=f"Question too many words (maximum {cls.MAX_QUESTION_LENGTH})",
                    severity="error",
                    value=word_count,
                    limit=cls.MAX_QUESTION_LENGTH,
                )
            )

        # Reject inputs containing credential-shaped strings
        for name, pattern in cls.CREDENTIAL_PATTERNS:
            if pattern.search(question):
                violations.append(
                    GuardrailViolation(
                        rule="blocked_keyword",
                        message=f"Question appears to contain a credential ({name}) — remove it",
                        severity="error",
                        value=name,
                        limit="N/A",
                    )
                )

        # Check prompt injection and jailbreak attacks
        if settings.injection_guardrails_enabled and settings.injection_guardrails_mode != "off":
            from src.security.injection import InjectionDetector
            from src.api.metrics import record_injection_attempt

            scan_result = InjectionDetector.scan_input(question)
            if not scan_result.is_safe:
                severity_level = (
                    "error" if settings.injection_guardrails_mode == "block" else "warning"
                )
                for finding in scan_result.findings:
                    try:
                        record_injection_attempt("input", finding.injection_type.value)
                    except Exception:
                        pass
                    violations.append(
                        GuardrailViolation(
                            rule=finding.injection_type.value,
                            message=finding.message,
                            severity=severity_level,
                            value=finding.matched_pattern,
                            limit="N/A",
                        )
                    )

        return len([v for v in violations if v.severity == "error"]) == 0, violations


class OutputGuardrails:
    """Validates generated output before returning."""

    # Minimum answer length (characters)
    MIN_ANSWER_CHARS = 10

    # Maximum answer length (characters)
    MAX_ANSWER_CHARS = 10000

    # Minimum confidence score (0.0-1.0)
    MIN_CONFIDENCE = 0.5

    @classmethod
    def validate(
        cls,
        answer: str,
        confidence: float = 1.0,
        sources: list[str] | None = None,
    ) -> tuple[bool, list[GuardrailViolation]]:
        """
        Validate generated output.

        Returns:
            (is_valid, violations)
        """
        violations: list[GuardrailViolation] = []
        sources = sources or []

        # Check answer length
        if len(answer) < cls.MIN_ANSWER_CHARS:
            violations.append(
                GuardrailViolation(
                    rule="min_answer_length",
                    message=f"Answer too short (minimum {cls.MIN_ANSWER_CHARS} characters)",
                    severity="warning",
                    value=len(answer),
                    limit=cls.MIN_ANSWER_CHARS,
                )
            )

        if len(answer) > cls.MAX_ANSWER_CHARS:
            violations.append(
                GuardrailViolation(
                    rule="max_answer_length",
                    message=f"Answer too long (maximum {cls.MAX_ANSWER_CHARS} characters)",
                    severity="warning",
                    value=len(answer),
                    limit=cls.MAX_ANSWER_CHARS,
                )
            )

        # Check confidence
        if confidence < cls.MIN_CONFIDENCE:
            violations.append(
                GuardrailViolation(
                    rule="low_confidence",
                    message=f"Confidence score too low (minimum {cls.MIN_CONFIDENCE})",
                    severity="warning",
                    value=confidence,
                    limit=cls.MIN_CONFIDENCE,
                )
            )

        # Check sources
        if not sources:
            violations.append(
                GuardrailViolation(
                    rule="no_sources",
                    message="Answer has no retrieved sources",
                    severity="warning",
                    value=0,
                    limit=1,
                )
            )

        # Check for system prompt leakage and markdown image data exfiltration in output
        if settings.injection_guardrails_enabled and settings.prompt_leakage_detection_enabled:
            from src.security.injection import InjectionDetector
            from src.api.metrics import record_injection_attempt

            out_scan = InjectionDetector.scan_output(answer)
            if not out_scan.is_safe:
                for finding in out_scan.findings:
                    try:
                        record_injection_attempt("output", finding.injection_type.value)
                    except Exception:
                        pass
                    # Exfiltration or severe leaks are errors; others are warnings
                    is_error = finding.matched_pattern in (
                        "markdown_image_exfil",
                        "generic_suspicious_image_exfil",
                    )
                    violations.append(
                        GuardrailViolation(
                            rule=finding.injection_type.value,
                            message=finding.message,
                            severity="error" if is_error else "warning",
                            value=finding.matched_pattern,
                            limit="N/A",
                        )
                    )

        return len([v for v in violations if v.severity == "error"]) == 0, violations


class CostGuardrails:
    """Tracks and limits token usage and costs (thread-safe).

    Uses Redis counters when available so budgets are shared across workers;
    falls back to in-process lists otherwise.

    Usage: call check_query_rate() + check_token_budget() before dispatch,
    record_query() when accepted, record_usage() with actual token counts after.
    """

    _REDIS_QPM = "cost:v1:queries_minute"
    _REDIS_TOK_MIN = "cost:v1:tokens_minute"
    _REDIS_TOK_HOUR = "cost:v1:tokens_hour"

    def __init__(self):
        """Initialize cost tracker."""
        import threading

        self._lock = threading.Lock()
        self.query_history: list[tuple[datetime, int, int]] = []  # (timestamp, input_tokens, output_tokens)
        self.query_timestamps: list[datetime] = []

    def _redis(self):
        backend = (settings.rate_limit_backend or "auto").strip().lower()
        if backend == "memory":
            return None
        try:
            from src.cache.redis_cache import get_redis_client

            return get_redis_client()
        except Exception:
            return None

    def check_query_rate(self) -> tuple[bool, list[GuardrailViolation]]:
        """Enforce max queries per minute."""
        limit = settings.max_queries_per_minute
        client = self._redis()
        if client is not None:
            try:
                recent = int(client.get(self._REDIS_QPM) or 0)
                if recent >= limit:
                    return False, [
                        GuardrailViolation(
                            rule="queries_per_minute",
                            message=f"Rate limit exceeded ({recent} >= {limit} queries/minute)",
                            severity="error",
                            value=recent,
                            limit=limit,
                        )
                    ]
                return True, []
            except Exception:
                pass

        now = datetime.now()
        one_minute_ago = now - timedelta(minutes=1)
        with self._lock:
            recent = sum(1 for t in self.query_timestamps if t > one_minute_ago)
        if recent >= limit:
            return False, [
                GuardrailViolation(
                    rule="queries_per_minute",
                    message=f"Rate limit exceeded ({recent} >= {limit} queries/minute)",
                    severity="error",
                    value=recent,
                    limit=limit,
                )
            ]
        return True, []

    def record_query(self) -> None:
        """Record a query for rate limiting."""
        client = self._redis()
        if client is not None:
            try:
                pipe = client.pipeline()
                pipe.incr(self._REDIS_QPM)
                pipe.expire(self._REDIS_QPM, 60)
                pipe.execute()
            except Exception:
                pass

        now = datetime.now()
        cutoff = now - timedelta(hours=1)
        with self._lock:
            self.query_timestamps.append(now)
            self.query_timestamps = [t for t in self.query_timestamps if t > cutoff]

    def check_token_budget(self) -> tuple[bool, list[GuardrailViolation]]:
        """Reject new work when the minute/hour token budget is already spent."""
        violations: list[GuardrailViolation] = []
        client = self._redis()
        if client is not None:
            try:
                minute_tokens = int(client.get(self._REDIS_TOK_MIN) or 0)
                hourly_tokens = int(client.get(self._REDIS_TOK_HOUR) or 0)
                if minute_tokens >= settings.max_tokens_per_minute:
                    violations.append(
                        GuardrailViolation(
                            rule="tokens_per_minute",
                            message=(
                                f"Minute token budget exhausted "
                                f"({minute_tokens} >= {settings.max_tokens_per_minute})"
                            ),
                            severity="error",
                            value=minute_tokens,
                            limit=settings.max_tokens_per_minute,
                        )
                    )
                if hourly_tokens >= settings.max_tokens_per_hour:
                    violations.append(
                        GuardrailViolation(
                            rule="tokens_per_hour",
                            message=(
                                f"Hour token budget exhausted "
                                f"({hourly_tokens} >= {settings.max_tokens_per_hour})"
                            ),
                            severity="error",
                            value=hourly_tokens,
                            limit=settings.max_tokens_per_hour,
                        )
                    )
                return len(violations) == 0, violations
            except Exception:
                pass

        now = datetime.now()
        one_minute_ago = now - timedelta(minutes=1)
        one_hour_ago = now - timedelta(hours=1)

        with self._lock:
            minute_tokens = sum(i + o for t, i, o in self.query_history if t > one_minute_ago)
            hourly_tokens = sum(i + o for t, i, o in self.query_history if t > one_hour_ago)

        if minute_tokens >= settings.max_tokens_per_minute:
            violations.append(
                GuardrailViolation(
                    rule="tokens_per_minute",
                    message=f"Minute token budget exhausted ({minute_tokens} >= {settings.max_tokens_per_minute})",
                    severity="error",
                    value=minute_tokens,
                    limit=settings.max_tokens_per_minute,
                )
            )
        if hourly_tokens >= settings.max_tokens_per_hour:
            violations.append(
                GuardrailViolation(
                    rule="tokens_per_hour",
                    message=f"Hour token budget exhausted ({hourly_tokens} >= {settings.max_tokens_per_hour})",
                    severity="error",
                    value=hourly_tokens,
                    limit=settings.max_tokens_per_hour,
                )
            )
        return len(violations) == 0, violations

    def record_usage(self, input_tokens: int, output_tokens: int) -> None:
        """Record actual token usage after a query completes."""
        total = max(0, int(input_tokens)) + max(0, int(output_tokens))
        client = self._redis()
        if client is not None and total:
            try:
                pipe = client.pipeline()
                pipe.incrby(self._REDIS_TOK_MIN, total)
                pipe.expire(self._REDIS_TOK_MIN, 60)
                pipe.incrby(self._REDIS_TOK_HOUR, total)
                pipe.expire(self._REDIS_TOK_HOUR, 3600)
                pipe.execute()
            except Exception:
                pass

        now = datetime.now()
        cutoff = now - timedelta(hours=1)
        with self._lock:
            self.query_history.append((now, input_tokens, output_tokens))
            self.query_history = [(t, i, o) for t, i, o in self.query_history if t > cutoff]

    def calculate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        *,
        provider: str = "openai",
    ) -> float:
        """Calculate cost in USD for token usage."""
        if provider == "groq":
            in_rate = settings.groq_cost_per_1k_input_usd
            out_rate = settings.groq_cost_per_1k_output_usd
        else:
            in_rate = settings.cost_per_1k_input_usd
            out_rate = settings.cost_per_1k_output_usd
        input_cost = (input_tokens / 1000) * in_rate
        output_cost = (output_tokens / 1000) * out_rate
        return input_cost + output_cost

    def get_usage_stats(self) -> dict:
        """Get current usage statistics."""
        client = self._redis()
        if client is not None:
            try:
                return {
                    "queries_per_minute": int(client.get(self._REDIS_QPM) or 0),
                    "tokens_per_minute": int(client.get(self._REDIS_TOK_MIN) or 0),
                    "tokens_per_hour": int(client.get(self._REDIS_TOK_HOUR) or 0),
                    "total_queries": int(client.get(self._REDIS_QPM) or 0),
                    "backend": "redis",
                }
            except Exception:
                pass

        now = datetime.now()
        one_minute_ago = now - timedelta(minutes=1)
        one_hour_ago = now - timedelta(hours=1)

        with self._lock:
            minute_tokens = sum(i + o for t, i, o in self.query_history if t > one_minute_ago)
            hour_tokens = sum(i + o for t, i, o in self.query_history if t > one_hour_ago)
            minute_queries = sum(1 for t, _, _ in self.query_history if t > one_minute_ago)
            total = len(self.query_history)

        return {
            "queries_per_minute": minute_queries,
            "tokens_per_minute": minute_tokens,
            "tokens_per_hour": hour_tokens,
            "total_queries": total,
            "backend": "memory",
        }


class QualityGuardrails:
    """Ensures output quality standards."""

    # Minimum answer relevance score (0.0-1.0)
    MIN_RELEVANCE = 0.6

    # Minimum context precision (fraction of relevant docs)
    MIN_CONTEXT_PRECISION = 0.5

    # Minimum faithfulness score (0.0-1.0)
    MIN_FAITHFULNESS = 0.7

    @classmethod
    def validate(
        cls,
        faithfulness: float = 1.0,
        relevance: float = 1.0,
        context_precision: float = 1.0,
    ) -> tuple[bool, list[GuardrailViolation]]:
        """Validate quality metrics."""
        violations: list[GuardrailViolation] = []

        if faithfulness < cls.MIN_FAITHFULNESS:
            violations.append(
                GuardrailViolation(
                    rule="low_faithfulness",
                    message=f"Answer not grounded in context (faithfulness {faithfulness:.2f} < {cls.MIN_FAITHFULNESS})",
                    severity="warning",
                    value=faithfulness,
                    limit=cls.MIN_FAITHFULNESS,
                )
            )

        if relevance < cls.MIN_RELEVANCE:
            violations.append(
                GuardrailViolation(
                    rule="low_relevance",
                    message=f"Answer not sufficiently relevant (relevance {relevance:.2f} < {cls.MIN_RELEVANCE})",
                    severity="warning",
                    value=relevance,
                    limit=cls.MIN_RELEVANCE,
                )
            )

        if context_precision < cls.MIN_CONTEXT_PRECISION:
            violations.append(
                GuardrailViolation(
                    rule="low_context_precision",
                    message=f"Retrieved documents not precise (precision {context_precision:.2f} < {cls.MIN_CONTEXT_PRECISION})",
                    severity="warning",
                    value=context_precision,
                    limit=cls.MIN_CONTEXT_PRECISION,
                )
            )

        return len(violations) == 0, violations


# Global cost tracker
_cost_tracker: CostGuardrails | None = None


def get_cost_tracker() -> CostGuardrails:
    """Get or create global cost tracker."""
    global _cost_tracker
    if _cost_tracker is None:
        _cost_tracker = CostGuardrails()
    return _cost_tracker
