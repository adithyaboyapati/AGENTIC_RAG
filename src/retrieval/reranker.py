"""Rerank retrieval candidates with NVIDIA NIM or local FlashRank.

Pipeline position:
  hybrid/mmr/similarity over-fetch → rerank → top_k → optional parent expand

Providers (``RERANK_PROVIDER``):
  - ``nvidia``   — NVIDIA NeMo Retriever rerank API (needs ``NVIDIA_API_KEY``)
  - ``flashrank`` — local ONNX cross-encoder (no API cost)

Disable entirely with ``RERANK_ENABLED=false``.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import httpx
from langchain_core.documents import Document

from src.config import PROJECT_ROOT, settings

logger = logging.getLogger(__name__)

_ranker_lock = threading.Lock()
_flashrank = None
_flashrank_key: tuple[str, str] | None = None
_flashrank_failed = False


def _provider() -> str:
    return (settings.rerank_provider or "flashrank").strip().lower()


def _cache_dir() -> Path:
    raw = Path(settings.rerank_cache_dir)
    path = raw if raw.is_absolute() else PROJECT_ROOT / raw
    path.mkdir(parents=True, exist_ok=True)
    return path


def _passage_text(doc: Document) -> str:
    # NVIDIA models are typically capped ~512 tokens; char truncate is a safe guard.
    limit = max(256, settings.rerank_max_length * 4)
    return (doc.page_content or "")[:limit]


def _apply_ranking(
    documents: list[Document],
    ranked_indices: list[tuple[int, float]],
    *,
    keep: int,
    model_label: str,
) -> list[Document]:
    reranked: list[Document] = []
    for idx, score in ranked_indices[:keep]:
        if idx < 0 or idx >= len(documents):
            continue
        doc = documents[idx]
        meta = dict(doc.metadata)
        meta["retrieval_score"] = meta.get("score")
        meta["rerank_score"] = score
        meta["score"] = score
        meta["rerank_provider"] = _provider()
        reranked.append(Document(page_content=doc.page_content, metadata=meta))

    if not reranked:
        return documents[:keep]

    logger.info(
        "rerank | provider=%s | model=%s | candidates=%d | kept=%d | top_score=%.4f",
        _provider(),
        model_label,
        len(documents),
        len(reranked),
        float(reranked[0].metadata.get("rerank_score") or 0.0),
    )
    return reranked


# ---------------------------------------------------------------------------
# FlashRank (local)
# ---------------------------------------------------------------------------


def _get_flashrank():
    global _flashrank, _flashrank_key, _flashrank_failed

    if _flashrank_failed:
        return None

    key = (settings.rerank_model, str(_cache_dir()))
    with _ranker_lock:
        if _flashrank is not None and _flashrank_key == key:
            return _flashrank

        try:
            from flashrank import Ranker
        except ImportError:
            logger.warning(
                "RERANK_PROVIDER=flashrank but flashrank is not installed — "
                "skipping rerank (pip install flashrank)"
            )
            _flashrank_failed = True
            return None

        try:
            _flashrank = Ranker(
                model_name=settings.rerank_model,
                cache_dir=str(_cache_dir()),
                max_length=settings.rerank_max_length,
            )
            _flashrank_key = key
            logger.info(
                "Loaded FlashRank reranker model=%s cache=%s",
                settings.rerank_model,
                _cache_dir(),
            )
            return _flashrank
        except Exception:
            logger.warning("Failed to initialize FlashRank reranker", exc_info=True)
            _flashrank_failed = True
            _flashrank = None
            _flashrank_key = None
            return None


def _rerank_flashrank(
    query: str, documents: list[Document], *, keep: int
) -> list[Document] | None:
    ranker = _get_flashrank()
    if ranker is None:
        return None

    passages = [{"id": i, "text": _passage_text(doc)} for i, doc in enumerate(documents)]
    try:
        from flashrank import RerankRequest

        ranked = ranker.rerank(RerankRequest(query=query, passages=passages))
    except Exception:
        logger.warning("FlashRank rerank failed — using unre-ranked order", exc_info=True)
        return None

    pairs: list[tuple[int, float]] = []
    for item in ranked:
        if isinstance(item, dict):
            pairs.append((int(item["id"]), float(item.get("score", 0.0))))
        else:
            pairs.append((int(item.id), float(getattr(item, "score", 0.0))))

    return _apply_ranking(documents, pairs, keep=keep, model_label=settings.rerank_model)


# ---------------------------------------------------------------------------
# NVIDIA NeMo Retriever (API)
# ---------------------------------------------------------------------------


def _nvidia_rerank_url() -> str:
    """Build ranking URL from explicit override or model slug."""
    if settings.nvidia_rerank_url.strip():
        return settings.nvidia_rerank_url.strip()

    model = settings.rerank_model.strip()
    # Accept "nvidia/nv-rerankqa-mistral-4b-v3" or bare "nv-rerankqa-mistral-4b-v3"
    slug = model.removeprefix("nvidia/")
    base = settings.nvidia_api_base.rstrip("/")
    return f"{base}/retrieval/nvidia/{slug}/reranking"


def _rerank_nvidia(
    query: str, documents: list[Document], *, keep: int
) -> list[Document] | None:
    api_key = (settings.nvidia_api_key or "").strip()
    if not api_key:
        logger.warning(
            "RERANK_PROVIDER=nvidia but NVIDIA_API_KEY is empty — skipping rerank"
        )
        return None

    model = settings.rerank_model.strip()
    if not model.startswith("nvidia/"):
        model = f"nvidia/{model.removeprefix('nvidia/')}"

    payload = {
        "model": model,
        "query": {"text": query},
        "passages": [{"text": _passage_text(doc)} for doc in documents],
        "truncate": settings.nvidia_rerank_truncate,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    url = _nvidia_rerank_url()

    from src.resilience.circuit_breaker import CircuitOpenError, get_breaker

    breaker = get_breaker("nvidia_rerank")

    def _call() -> dict:
        with httpx.Client(timeout=settings.nvidia_rerank_timeout_seconds) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

    try:
        data = breaker.call(_call)
    except CircuitOpenError:
        logger.warning("NVIDIA rerank circuit open — skipping NVIDIA, trying fallback")
        return None
    except Exception:
        logger.warning("NVIDIA rerank API failed — using unre-ranked order", exc_info=True)
        return None

    rankings = data.get("rankings") or data.get("results") or []
    pairs: list[tuple[int, float]] = []
    for item in rankings:
        if not isinstance(item, dict):
            continue
        idx = item.get("index", item.get("id"))
        if idx is None:
            continue
        # NVIDIA returns logits; higher = more relevant
        score = item.get("logit", item.get("score", item.get("relevance_score", 0.0)))
        pairs.append((int(idx), float(score)))

    if not pairs:
        logger.warning("NVIDIA rerank returned no rankings — using unre-ranked order")
        return None

    return _apply_ranking(documents, pairs, keep=keep, model_label=model)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def invalidate_reranker() -> None:
    """Reset cached local ranker (tests / model switch)."""
    global _flashrank, _flashrank_key, _flashrank_failed
    with _ranker_lock:
        _flashrank = None
        _flashrank_key = None
        _flashrank_failed = False


def rerank_documents(
    query: str,
    documents: list[Document],
    *,
    top_n: int | None = None,
) -> list[Document]:
    """
    Rerank documents by cross-encoder relevance to ``query``.

    Returns the top ``top_n`` docs (default: ``retrieval_top_k``) with
    ``score`` / ``rerank_score`` metadata updated. On disable or failure,
    returns the original list truncated to ``top_n``.
    """
    keep = top_n if top_n is not None else settings.retrieval_top_k
    if keep <= 0:
        return []
    if not documents:
        return []
    if len(documents) <= 1 or not settings.rerank_enabled:
        return documents[:keep]

    provider = _provider()
    result: list[Document] | None = None

    if provider == "nvidia":
        result = _rerank_nvidia(query, documents, keep=keep)
        # Soft fallback so local/dev still works if the key is missing or the API fails
        if result is None and not (settings.nvidia_api_key or "").strip():
            logger.info("Falling back to FlashRank (NVIDIA_API_KEY not set)")
            result = _rerank_flashrank(query, documents, keep=keep)
    elif provider == "flashrank":
        result = _rerank_flashrank(query, documents, keep=keep)
    else:
        logger.warning("Unknown RERANK_PROVIDER=%r — skipping rerank", provider)

    return result if result is not None else documents[:keep]
