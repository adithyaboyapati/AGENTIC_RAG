"""Persist user feedback on answers.

Primary store is Supabase (``answer_feedback`` table). When Supabase is not
configured the same rows are written to a local SQLite file so development
and CI still capture feedback and the export/eval tooling keeps working.

Every free-text field is passed through the privacy redactor before storage:
a complaint like "it got my SSN 123-45-6789 wrong" must not become a PII
leak in the feedback table.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.config import settings

logger = logging.getLogger(__name__)

RATINGS = ("up", "down")
CATEGORIES = (
    "hallucination",
    "wrong_source",
    "incomplete",
    "off_topic",
    "too_slow",
    "formatting",
    "other",
)

_sqlite_lock = threading.Lock()


@dataclass
class FeedbackRecord:
    rating: str
    question: str
    answer: str
    mode: str = ""
    comment: str = ""
    categories: list[str] = field(default_factory=list)
    session_id: str | None = None
    message_id: str | None = None
    request_id: str | None = None
    tenant_id: str = "default"
    route: str | None = None
    sources: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: float | None = None
    consensus_score: float | None = None
    client: str = "web"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["categories"] = list(self.categories)
        row["sources"] = list(self.sources)
        row["citations"] = list(self.citations)
        return row


def _redact(text: str | None) -> str:
    if not text:
        return ""
    try:
        from src.privacy import (
            DataRedactor,
            PHIDetector,
            PIIDetector,
            PrivacyMode,
            get_privacy_policy,
        )

        policy = get_privacy_policy()
        if policy.output_mode is PrivacyMode.OFF:
            return text
        # Always redact for storage — even under a "block" policy we still want
        # the comment, just not the identifiers inside it.
        findings = PIIDetector.detect_all(text)
        if policy.detect_phi:
            findings += PHIDetector.detect_all(text)
        return DataRedactor._apply(text, findings) if findings else text
    except Exception:
        logger.debug("Feedback redaction skipped", exc_info=True)
        return text


def sanitize_record(record: FeedbackRecord) -> FeedbackRecord:
    """Normalize and redact before persistence."""
    rating = (record.rating or "").strip().lower()
    if rating not in RATINGS:
        raise ValueError(f"rating must be one of {RATINGS}")
    record.rating = rating
    record.comment = _redact(record.comment)[:2000]
    record.question = _redact(record.question)[:4000]
    record.answer = _redact(record.answer)[:12000]
    record.categories = [c for c in record.categories if c in CATEGORIES][:5]
    record.tenant_id = (record.tenant_id or "default").strip().lower()
    return record


# ---------------------------------------------------------------------------
# Supabase backend
# ---------------------------------------------------------------------------


def _supabase():
    try:
        from src.memory.supabase_store import get_supabase_client

        return get_supabase_client()
    except Exception:
        return None


def _supabase_insert(row: dict[str, Any]) -> bool:
    client = _supabase()
    if client is None:
        return False
    payload = dict(row)
    payload["created_at"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(payload.pop("created_at")))
    )
    try:
        client.table(settings.supabase_feedback_table).insert(payload).execute()
        return True
    except Exception as exc:
        logger.warning("Failed to save feedback to Supabase: %s", exc)
        return False


def _supabase_list(limit: int, rating: str | None, mode: str | None) -> list[dict[str, Any]] | None:
    client = _supabase()
    if client is None:
        return None
    try:
        query = client.table(settings.supabase_feedback_table).select("*")
        if rating:
            query = query.eq("rating", rating)
        if mode:
            query = query.eq("mode", mode)
        response = query.order("created_at", desc=True).limit(limit).execute()
        return list(response.data or [])
    except Exception as exc:
        logger.warning("Failed to list feedback from Supabase: %s", exc)
        return None


# ---------------------------------------------------------------------------
# SQLite fallback
# ---------------------------------------------------------------------------


def _sqlite_path() -> Path:
    path = Path(settings.feedback_db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_sqlite_path()), timeout=5.0)
    conn.execute(
        """
        create table if not exists answer_feedback (
            id text primary key,
            rating text not null,
            question text not null,
            answer text not null,
            mode text default '',
            comment text default '',
            categories text default '[]',
            session_id text,
            message_id text,
            request_id text,
            tenant_id text default 'default',
            route text,
            sources text default '[]',
            citations text default '[]',
            latency_ms real,
            consensus_score real,
            client text default 'web',
            created_at real not null
        )
        """
    )
    conn.execute(
        "create index if not exists idx_feedback_created on answer_feedback (created_at)"
    )
    return conn


def _sqlite_insert(row: dict[str, Any]) -> bool:
    payload = dict(row)
    for key in ("categories", "sources", "citations"):
        payload[key] = json.dumps(payload.get(key) or [], ensure_ascii=False)
    cols = ", ".join(payload.keys())
    marks = ", ".join("?" for _ in payload)
    try:
        with _sqlite_lock, _sqlite_conn() as conn:
            conn.execute(
                f"insert or replace into answer_feedback ({cols}) values ({marks})",
                list(payload.values()),
            )
        return True
    except Exception as exc:
        logger.warning("Failed to save feedback to SQLite: %s", exc)
        return False


def _sqlite_list(limit: int, rating: str | None, mode: str | None) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if rating:
        clauses.append("rating = ?")
        params.append(rating)
    if mode:
        clauses.append("mode = ?")
        params.append(mode)
    where = f"where {' and '.join(clauses)}" if clauses else ""
    try:
        with _sqlite_lock, _sqlite_conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"select * from answer_feedback {where} order by created_at desc limit ?",
                [*params, limit],
            ).fetchall()
    except Exception as exc:
        logger.warning("Failed to list feedback from SQLite: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        for key in ("categories", "sources", "citations"):
            try:
                d[key] = json.loads(d.get(key) or "[]")
            except Exception:
                d[key] = []
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save_feedback(record: FeedbackRecord) -> tuple[bool, str]:
    """Persist feedback. Returns (ok, backend)."""
    if not settings.feedback_enabled:
        return False, "disabled"
    record = sanitize_record(record)
    row = record.to_row()

    if _supabase_insert(row):
        backend = "supabase"
    elif _sqlite_insert(row):
        backend = "sqlite"
    else:
        return False, "none"

    logger.info(
        "Feedback saved | rating=%s | mode=%s | categories=%s | backend=%s | id=%s",
        record.rating,
        record.mode,
        ",".join(record.categories) or "-",
        backend,
        record.id,
    )
    try:
        from src.api.metrics import record_feedback

        record_feedback(record.mode, record.rating, record.categories)
    except Exception:
        logger.debug("Feedback metric export skipped", exc_info=True)

    if record.rating == "down" and getattr(settings, "feedback_auto_regression", True):
        try:
            from src.evaluation.regression_pipeline import create_regression_candidate_from_feedback
            from src.api.metrics import record_regression_candidate

            case = create_regression_candidate_from_feedback(record.to_row())
            if case is not None:
                record_regression_candidate("user_feedback", case.failure_category)
        except Exception:
            logger.debug("Feedback regression candidate skipped", exc_info=True)

    return True, backend


def list_feedback(
    limit: int = 100,
    rating: str | None = None,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    limit = max(1, min(1000, int(limit)))
    rows = _supabase_list(limit, rating, mode)
    if rows is None:
        rows = _sqlite_list(limit, rating, mode)
    return rows


def summarize_feedback(limit: int = 1000) -> dict[str, Any]:
    """Aggregate feedback so operators can see where the system is failing."""
    rows = list_feedback(limit=limit)
    by_mode: dict[str, dict[str, int]] = {}
    categories: dict[str, int] = {}
    up = down = 0
    for r in rows:
        mode = str(r.get("mode") or "unknown")
        rating = str(r.get("rating") or "")
        bucket = by_mode.setdefault(mode, {"up": 0, "down": 0})
        if rating == "up":
            up += 1
            bucket["up"] += 1
        elif rating == "down":
            down += 1
            bucket["down"] += 1
            for c in r.get("categories") or []:
                categories[str(c)] = categories.get(str(c), 0) + 1
    total = up + down
    mode_rows = []
    for mode, counts in sorted(by_mode.items()):
        n = counts["up"] + counts["down"]
        mode_rows.append(
            {
                "mode": mode,
                "up": counts["up"],
                "down": counts["down"],
                "negative_rate": round(counts["down"] / n, 3) if n else 0.0,
            }
        )
    recent_negative = [
        {
            "id": r.get("id"),
            "mode": r.get("mode"),
            "question": r.get("question"),
            "comment": r.get("comment"),
            "categories": r.get("categories") or [],
            "created_at": r.get("created_at"),
        }
        for r in rows
        if r.get("rating") == "down"
    ][:20]
    return {
        "total": total,
        "up": up,
        "down": down,
        "negative_rate": round(down / total, 3) if total else 0.0,
        "by_mode": mode_rows,
        "top_categories": sorted(
            ({"category": k, "count": v} for k, v in categories.items()),
            key=lambda x: x["count"],
            reverse=True,
        ),
        "recent_negative": recent_negative,
    }
