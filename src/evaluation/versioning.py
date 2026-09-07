"""Version identifiers for reproducible evaluation (Phase 8)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from src.config import settings
from src.evaluation.legacy_retirement import CANONICAL_PIPELINE_VERSION


@dataclass(frozen=True)
class EvalVersionManifest:
    """Identifies the exact configuration used for an evaluation run."""

    dataset_version: str
    pipeline_version: str
    model_version: str
    prompt_version: str
    retrieval_config_version: str
    evaluation_timestamp: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _hash_payload(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def current_prompt_version() -> str:
    """Hash of canonical prompt templates used in production."""
    from src.prompts import (
        DIRECT_PROMPT,
        RAG_PROMPT,
        ROUTER_PROMPT,
        WEB_SEARCH_PROMPT,
    )

    payload = {
        "router": str(ROUTER_PROMPT.messages),
        "rag": str(RAG_PROMPT.messages),
        "direct": str(DIRECT_PROMPT.messages),
        "web": str(WEB_SEARCH_PROMPT.messages),
    }
    return f"prompt-{_hash_payload(payload)}"


def current_retrieval_config_version() -> str:
    payload = {
        "retrieval_top_k": settings.retrieval_top_k,
        "retrieval_candidate_k": settings.retrieval_candidate_k,
        "retrieval_search_type": settings.retrieval_search_type,
        "rerank_enabled": settings.rerank_enabled,
        "rerank_provider": settings.rerank_provider,
        "rerank_model": settings.rerank_model,
        "multi_source_enabled": settings.multi_source_enabled,
        "extra_sources": settings.extra_sources,
        "expand_to_parent": settings.expand_to_parent,
        "context_compression_enabled": settings.context_compression_enabled,
    }
    return f"retrieval-{_hash_payload(payload)}"


def current_model_version() -> str:
    payload = {
        "openai_model": settings.openai_model,
        "groq_model": settings.groq_model,
        "embedding_model": settings.openai_embedding_model,
        "llm_fallback_enabled": settings.llm_fallback_enabled,
    }
    return f"model-{_hash_payload(payload)}"


def current_eval_manifest(*, dataset_version: str = "golden-v1") -> EvalVersionManifest:
    return EvalVersionManifest(
        dataset_version=dataset_version,
        pipeline_version=f"canonical-{CANONICAL_PIPELINE_VERSION}",
        model_version=current_model_version(),
        prompt_version=current_prompt_version(),
        retrieval_config_version=current_retrieval_config_version(),
        evaluation_timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
