"""Versioned evaluation dataset lifecycle store (Phase 8).

Lifecycle:
  raw → candidate → reviewed → golden | regression → historical result
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT, settings

_lock = threading.Lock()

CASE_STATUSES = (
    "raw",
    "candidate",
    "reviewed",
    "golden",
    "regression",
    "archived",
)


class CaseStatus(str, Enum):
    RAW = "raw"
    CANDIDATE = "candidate"
    REVIEWED = "reviewed"
    GOLDEN = "golden"
    REGRESSION = "regression"
    ARCHIVED = "archived"


@dataclass
class EvalCase:
    question: str
    status: str = CaseStatus.CANDIDATE.value
    expected_keywords: list[str] = field(default_factory=list)
    expected_chunk_ids: list[str] = field(default_factory=list)
    rejected_answer: str = ""
    failure_category: str = ""
    source_event: str = ""
    feedback_id: str | None = None
    request_id: str | None = None
    tenant_id: str = "default"
    notes: str = ""
    dataset_version: str = "eval-v1"
    case_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_row(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "question": self.question,
            "status": self.status,
            "expected_keywords": json.dumps(self.expected_keywords),
            "expected_chunk_ids": json.dumps(self.expected_chunk_ids),
            "rejected_answer": self.rejected_answer,
            "failure_category": self.failure_category,
            "source_event": self.source_event,
            "feedback_id": self.feedback_id,
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
            "notes": self.notes,
            "dataset_version": self.dataset_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _db_path() -> Path:
    path = Path(getattr(settings, "eval_dataset_db_path", PROJECT_ROOT / "data" / "eval" / "dataset.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=5.0)
    conn.execute(
        """
        create table if not exists eval_cases (
            case_id text primary key,
            question text not null,
            status text not null,
            expected_keywords text default '[]',
            expected_chunk_ids text default '[]',
            rejected_answer text default '',
            failure_category text default '',
            source_event text default '',
            feedback_id text,
            request_id text,
            tenant_id text default 'default',
            notes text default '',
            dataset_version text default 'eval-v1',
            created_at real not null,
            updated_at real not null
        )
        """
    )
    conn.execute(
        """
        create table if not exists eval_runs (
            run_id text primary key,
            trigger text not null,
            dataset_version text not null,
            pipeline_version text not null,
            model_version text not null,
            prompt_version text not null,
            retrieval_config_version text not null,
            evaluation_timestamp text not null,
            summary_json text not null,
            gate_status text default 'informational',
            created_at real not null
        )
        """
    )
    conn.execute("create index if not exists idx_eval_cases_status on eval_cases (status)")
    conn.execute("create index if not exists idx_eval_runs_ts on eval_runs (evaluation_timestamp)")
    return conn


def save_case(case: EvalCase) -> str:
    case.updated_at = time.time()
    row = case.to_row()
    cols = ", ".join(row.keys())
    marks = ", ".join("?" for _ in row)
    with _lock, _conn() as conn:
        conn.execute(
            f"insert or replace into eval_cases ({cols}) values ({marks})",
            list(row.values()),
        )
    return case.case_id


def list_cases(
    *,
    status: str | None = None,
    dataset_version: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if dataset_version:
        clauses.append("dataset_version = ?")
        params.append(dataset_version)
    where = f"where {' and '.join(clauses)}" if clauses else ""
    with _lock, _conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"select * from eval_cases {where} order by updated_at desc limit ?",
            [*params, max(1, limit)],
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        for key in ("expected_keywords", "expected_chunk_ids"):
            try:
                d[key] = json.loads(d.get(key) or "[]")
            except Exception:
                d[key] = []
        out.append(d)
    return out


def promote_case(case_id: str, *, to_status: str, notes: str = "") -> bool:
    if to_status not in CASE_STATUSES:
        raise ValueError(f"invalid status: {to_status}")
    with _lock, _conn() as conn:
        cur = conn.execute(
            "update eval_cases set status = ?, notes = ?, updated_at = ? where case_id = ?",
            (to_status, notes, time.time(), case_id),
        )
        return cur.rowcount > 0


def append_eval_run(
    *,
    trigger: str,
    manifest: dict[str, str],
    summary: dict[str, Any],
    gate_status: str = "informational",
) -> str:
    run_id = uuid.uuid4().hex
    row = {
        "run_id": run_id,
        "trigger": trigger,
        "dataset_version": manifest.get("dataset_version", ""),
        "pipeline_version": manifest.get("pipeline_version", ""),
        "model_version": manifest.get("model_version", ""),
        "prompt_version": manifest.get("prompt_version", ""),
        "retrieval_config_version": manifest.get("retrieval_config_version", ""),
        "evaluation_timestamp": manifest.get("evaluation_timestamp", ""),
        "summary_json": json.dumps(summary, ensure_ascii=False),
        "gate_status": gate_status,
        "created_at": time.time(),
    }
    cols = ", ".join(row.keys())
    marks = ", ".join("?" for _ in row)
    with _lock, _conn() as conn:
        conn.execute(f"insert into eval_runs ({cols}) values ({marks})", list(row.values()))
    return run_id


def list_eval_runs(limit: int = 50) -> list[dict[str, Any]]:
    with _lock, _conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "select * from eval_runs order by created_at desc limit ?",
            (max(1, limit),),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        try:
            d["summary"] = json.loads(d.pop("summary_json") or "{}")
        except Exception:
            d["summary"] = {}
        out.append(d)
    return out
