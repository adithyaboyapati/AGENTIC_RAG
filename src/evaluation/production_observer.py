"""Record production observations for continuous evaluation (Phase 8)."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT, settings

logger = logging.getLogger(__name__)
_lock = threading.Lock()


@dataclass
class ProductionObservation:
    request_id: str
    tenant_id: str
    route: str
    strategy: str
    strategy_decision_source: str
    verification_status: str
    response_status: str
    evidence_count: int
    citation_count: int
    retry_count: int
    llm_call_count: int
    latency_ms: float
    cost_usd: float
    input_tokens: int
    output_tokens: int
    model_id: str
    pipeline_version: str
    zero_evidence: bool = False
    heuristic_strategy: str = ""
    strategy_llm_redundant: bool = False
    ineffective_retry: bool = False
    unnecessary_multihop: bool = False
    error_code: str | None = None
    observation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)


def _db_path() -> Path:
    path = Path(getattr(settings, "production_observations_db_path", PROJECT_ROOT / "data" / "eval" / "observations.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=5.0)
    conn.execute(
        """
        create table if not exists production_observations (
            observation_id text primary key,
            request_id text not null,
            tenant_id text default 'default',
            route text,
            strategy text,
            strategy_decision_source text,
            verification_status text,
            response_status text,
            evidence_count integer,
            citation_count integer,
            retry_count integer,
            llm_call_count integer,
            latency_ms real,
            cost_usd real,
            input_tokens integer,
            output_tokens integer,
            model_id text,
            pipeline_version text,
            zero_evidence integer,
            heuristic_strategy text,
            strategy_llm_redundant integer,
            ineffective_retry integer,
            unnecessary_multihop integer,
            error_code text,
            payload_json text,
            created_at real not null
        )
        """
    )
    conn.execute(
        "create index if not exists idx_obs_created on production_observations (created_at)"
    )
    return conn


def record_observation(obs: ProductionObservation, *, extra: dict[str, Any] | None = None) -> str:
    if not getattr(settings, "continuous_eval_enabled", True):
        return obs.observation_id
    row = {
        "observation_id": obs.observation_id,
        "request_id": obs.request_id,
        "tenant_id": obs.tenant_id,
        "route": obs.route,
        "strategy": obs.strategy,
        "strategy_decision_source": obs.strategy_decision_source,
        "verification_status": obs.verification_status,
        "response_status": obs.response_status,
        "evidence_count": obs.evidence_count,
        "citation_count": obs.citation_count,
        "retry_count": obs.retry_count,
        "llm_call_count": obs.llm_call_count,
        "latency_ms": obs.latency_ms,
        "cost_usd": obs.cost_usd,
        "input_tokens": obs.input_tokens,
        "output_tokens": obs.output_tokens,
        "model_id": obs.model_id,
        "pipeline_version": obs.pipeline_version,
        "zero_evidence": int(obs.zero_evidence),
        "heuristic_strategy": obs.heuristic_strategy,
        "strategy_llm_redundant": int(obs.strategy_llm_redundant),
        "ineffective_retry": int(obs.ineffective_retry),
        "unnecessary_multihop": int(obs.unnecessary_multihop),
        "error_code": obs.error_code,
        "payload_json": json.dumps(extra or {}, ensure_ascii=False),
        "created_at": obs.created_at,
    }
    cols = ", ".join(row.keys())
    marks = ", ".join("?" for _ in row)
    with _lock, _conn() as conn:
        conn.execute(f"insert into production_observations ({cols}) values ({marks})", list(row.values()))
    try:
        from src.api.metrics import record_production_observation

        record_production_observation(obs)
    except Exception:
        pass
    return obs.observation_id


def list_observations(*, since_hours: float = 24.0, limit: int = 5000) -> list[dict[str, Any]]:
    cutoff = time.time() - since_hours * 3600
    with _lock, _conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "select * from production_observations where created_at >= ? order by created_at desc limit ?",
            (cutoff, max(1, limit)),
        ).fetchall()
    return [dict(r) for r in rows]


def observe_from_api_response(
    *,
    request_id: str,
    tenant_id: str,
    result: Any,
    latency_ms: float,
    cost_usd: float = 0.0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    model_id: str = "",
    pipeline_version: str = "canonical-v1",
    metadata: dict[str, Any] | None = None,
) -> str | None:
    """Record a production observation from an AgentResponse-like object."""
    if not getattr(settings, "continuous_eval_enabled", True):
        return None

    meta = metadata or {}
    heuristic = str(meta.get("heuristic_strategy") or "")
    final_strategy = str(getattr(result, "route_reason", None) or meta.get("strategy") or "simple")
    decision_source = str(meta.get("strategy_decision_source") or "unknown")
    retry_count = int(meta.get("retry_count") or 0)
    evidence_count = int(meta.get("evidence_count") or len(getattr(result, "context_docs", []) or []))
    citation_count = len(getattr(result, "citations", []) or [])
    verification_status = str(meta.get("verification_status") or "unknown")
    response_status = "error" if getattr(result, "error_code", None) else "ok"

    obs = ProductionObservation(
        request_id=request_id,
        tenant_id=tenant_id,
        route=str(getattr(result, "route", None) or "unknown"),
        strategy=final_strategy,
        strategy_decision_source=decision_source,
        verification_status=verification_status,
        response_status=response_status,
        evidence_count=evidence_count,
        citation_count=citation_count,
        retry_count=retry_count,
        llm_call_count=int(meta.get("llm_call_count") or 0),
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model_id=model_id or settings.openai_model,
        pipeline_version=pipeline_version,
        zero_evidence=evidence_count == 0 and str(getattr(result, "route", "")) == "retrieve",
        heuristic_strategy=heuristic,
        strategy_llm_redundant=bool(
            decision_source == "llm" and heuristic and heuristic == final_strategy
        ),
        ineffective_retry=bool(retry_count > 0 and evidence_count == 0),
        unnecessary_multihop=bool(
            final_strategy == "multi_hop" and retry_count == 0 and evidence_count <= 2
        ),
        error_code=getattr(result, "error_code", None),
    )
    return record_observation(obs, extra=meta)
