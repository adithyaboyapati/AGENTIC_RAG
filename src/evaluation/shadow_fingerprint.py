"""Deterministic request fingerprinting for paired shadow evaluation."""

from __future__ import annotations

import hashlib
import json
import re

from pydantic import BaseModel, ConfigDict, Field

from src.cache.redis_cache import normalize_question
from src.schemas import RBACContext

_WS_RE = re.compile(r"\s+")


class ShadowRequestContext(BaseModel):
    """Inputs that materially affect legacy and canonical execution."""

    model_config = ConfigDict(frozen=True)

    sanitized_question: str = Field(min_length=1)
    legacy_mode: str = Field(min_length=1)
    tenant_id: str = "default"
    roles_key: str = "public"
    classification: str = "public"
    use_memory: bool = False
    canonical_strategy: str | None = None
    config_snapshot: dict[str, str | int | float | bool] = Field(default_factory=dict)


def sanitize_question_for_fingerprint(question: str) -> str:
    return _WS_RE.sub(" ", (question or "").strip())


def build_shadow_request_context(
    *,
    question: str,
    legacy_mode: str,
    rbac_context: RBACContext,
    use_memory: bool = False,
    canonical_strategy: str | None = None,
    config_snapshot: dict[str, str | int | float | bool] | None = None,
) -> ShadowRequestContext:
    return ShadowRequestContext(
        sanitized_question=sanitize_question_for_fingerprint(question),
        legacy_mode=legacy_mode.strip().lower(),
        tenant_id=(rbac_context.tenant_id or "default").strip().lower(),
        roles_key=rbac_context.roles_key(),
        classification=(rbac_context.classification or "public").strip().lower(),
        use_memory=use_memory,
        canonical_strategy=(canonical_strategy or "auto").strip().lower(),
        config_snapshot=config_snapshot or {},
    )


def compute_input_fingerprint(context: ShadowRequestContext) -> str:
    """Stable identity for paired legacy/canonical comparisons."""
    payload = {
        "question": normalize_question(context.sanitized_question),
        "legacy_mode": context.legacy_mode,
        "tenant_id": context.tenant_id,
        "roles_key": context.roles_key,
        "classification": context.classification,
        "use_memory": context.use_memory,
        "canonical_strategy": context.canonical_strategy,
        "config": dict(sorted(context.config_snapshot.items())),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return digest
