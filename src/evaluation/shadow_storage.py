"""Persist shadow evaluation records without coupling to production state."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT, settings
from src.evaluation.shadow_models import ShadowResult

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_SCHEMA = """
create table if not exists shadow_results (
    id integer primary key autoincrement,
    request_id text not null,
    tenant_id text not null,
    input_fingerprint text not null,
    execution_mode text not null,
    legacy_mode text not null,
    canonical_strategy text,
    comparison_status text,
    disagreement_class text,
    winner text,
    latency_delta_ms real,
    cost_delta_usd real,
    token_delta integer,
    legacy_metrics_json text not null,
    canonical_metrics_json text not null,
    legacy_summary_json text not null,
    canonical_summary_json text not null,
    quality_deltas_json text,
    sampling_json text,
    eval_config_hash text,
    errors_json text,
    fallback_reason text,
    created_at real not null
);
create index if not exists idx_shadow_created on shadow_results (created_at);
create index if not exists idx_shadow_fingerprint on shadow_results (input_fingerprint);
create index if not exists idx_shadow_tenant on shadow_results (tenant_id);
"""


def _db_path() -> Path:
    raw = getattr(settings, "shadow_db_path", "") or str(PROJECT_ROOT / "data" / "shadow_eval.db")
    return Path(raw)


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def save_shadow_result(result: ShadowResult) -> bool:
    try:
        with _lock:
            conn = _connect()
            _ensure_schema(conn)
            conn.execute(
                """
                insert into shadow_results (
                    request_id, tenant_id, input_fingerprint, execution_mode,
                    legacy_mode, canonical_strategy, comparison_status,
                    disagreement_class, winner, latency_delta_ms, cost_delta_usd,
                    token_delta, legacy_metrics_json, canonical_metrics_json,
                    legacy_summary_json, canonical_summary_json, quality_deltas_json,
                    sampling_json, eval_config_hash, errors_json, fallback_reason,
                    created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.request_id,
                    result.tenant_id,
                    result.input_fingerprint,
                    result.execution_mode.value,
                    result.legacy_mode,
                    result.canonical_strategy,
                    result.comparison_status.value,
                    result.disagreement_class.value,
                    result.winner,
                    result.latency_delta_ms,
                    result.cost_delta_usd,
                    result.token_delta,
                    result.legacy_metrics.model_dump_json(),
                    result.canonical_metrics.model_dump_json(),
                    json.dumps(result.legacy_response_summary, ensure_ascii=False),
                    json.dumps(result.canonical_response_summary, ensure_ascii=False),
                    json.dumps(result.quality_deltas, ensure_ascii=False),
                    json.dumps(result.sampling, ensure_ascii=False),
                    result.eval_config_hash,
                    json.dumps(list(result.errors), ensure_ascii=False),
                    result.fallback_reason,
                    time.time(),
                ),
            )
            conn.commit()
            _apply_retention(conn)
            conn.close()
        return True
    except Exception:
        logger.warning("Failed to persist shadow result", exc_info=True)
        return False


def _apply_retention(conn: sqlite3.Connection) -> None:
    days = max(1, int(getattr(settings, "shadow_retention_days", 30)))
    cutoff = time.time() - (days * 86400)
    conn.execute("delete from shadow_results where created_at < ?", (cutoff,))
    conn.commit()


def list_shadow_results(
    *,
    limit: int = 500,
    tenant_id: str | None = None,
    since_ts: float | None = None,
) -> list[dict[str, Any]]:
    with _lock:
        conn = _connect()
        _ensure_schema(conn)
        clauses = ["1=1"]
        params: list[Any] = []
        if tenant_id:
            clauses.append("tenant_id = ?")
            params.append(tenant_id.strip().lower())
        if since_ts is not None:
            clauses.append("created_at >= ?")
            params.append(since_ts)
        params.append(max(1, limit))
        rows = conn.execute(
            f"""
            select * from shadow_results
            where {' and '.join(clauses)}
            order by created_at desc
            limit ?
            """,
            params,
        ).fetchall()
        conn.close()
    return [_row_to_dict(row) for row in rows]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "request_id": row["request_id"],
        "tenant_id": row["tenant_id"],
        "input_fingerprint": row["input_fingerprint"],
        "execution_mode": row["execution_mode"],
        "legacy_mode": row["legacy_mode"],
        "canonical_strategy": row["canonical_strategy"],
        "comparison_status": row["comparison_status"],
        "disagreement_class": row["disagreement_class"],
        "winner": row["winner"],
        "latency_delta_ms": row["latency_delta_ms"],
        "cost_delta_usd": row["cost_delta_usd"],
        "token_delta": row["token_delta"],
        "legacy_metrics": json.loads(row["legacy_metrics_json"]),
        "canonical_metrics": json.loads(row["canonical_metrics_json"]),
        "legacy_summary": json.loads(row["legacy_summary_json"]),
        "canonical_summary": json.loads(row["canonical_summary_json"]),
        "quality_deltas": json.loads(row["quality_deltas_json"] or "{}"),
        "sampling": json.loads(row["sampling_json"] or "{}"),
        "eval_config_hash": row["eval_config_hash"],
        "errors": json.loads(row["errors_json"] or "[]"),
        "fallback_reason": row["fallback_reason"],
        "created_at": row["created_at"],
    }


def reset_shadow_store_for_tests() -> None:
    with _lock:
        path = _db_path()
        if path.exists():
            path.unlink()
