"""Lightweight experiment framework on canary/shadow infrastructure (Phase 8)."""

from __future__ import annotations

import hashlib
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


class ExperimentStatus(str, Enum):
    DRAFT = "draft"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class Experiment:
    name: str
    control_pipeline: str = "canonical-v1"
    treatment_pipeline: str = "canonical-v2"
    traffic_percent: float = 0.0
    status: str = ExperimentStatus.DRAFT.value
    experiment_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    config: dict[str, Any] = field(default_factory=dict)


_lock = threading.Lock()


def _db_path() -> Path:
    path = Path(getattr(settings, "experiments_db_path", PROJECT_ROOT / "data" / "eval" / "experiments.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=5.0)
    conn.execute(
        """
        create table if not exists experiments (
            experiment_id text primary key,
            name text not null,
            control_pipeline text not null,
            treatment_pipeline text not null,
            traffic_percent real default 0,
            status text not null,
            config_json text default '{}',
            created_at real not null,
            ended_at real
        )
        """
    )
    return conn


def save_experiment(exp: Experiment) -> str:
    row = {
        "experiment_id": exp.experiment_id,
        "name": exp.name,
        "control_pipeline": exp.control_pipeline,
        "treatment_pipeline": exp.treatment_pipeline,
        "traffic_percent": exp.traffic_percent,
        "status": exp.status,
        "config_json": json.dumps(exp.config),
        "created_at": exp.created_at,
        "ended_at": exp.ended_at,
    }
    cols = ", ".join(row.keys())
    marks = ", ".join("?" for _ in row)
    with _lock, _conn() as conn:
        conn.execute(f"insert or replace into experiments ({cols}) values ({marks})", list(row.values()))
    return exp.experiment_id


def list_experiments(*, status: str | None = None) -> list[dict[str, Any]]:
    clause = "where status = ?" if status else ""
    params: list[Any] = [status] if status else []
    with _lock, _conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"select * from experiments {clause} order by created_at desc",
            params,
        ).fetchall()
    out = []
    for row in rows:
        d = dict(row)
        try:
            d["config"] = json.loads(d.pop("config_json") or "{}")
        except Exception:
            d["config"] = {}
        out.append(d)
    return out


def assign_experiment_bucket(
    *,
    experiment_id: str,
    request_id: str,
    traffic_percent: float,
) -> str:
    """Deterministically assign control vs treatment."""
    if traffic_percent <= 0:
        return "control"
    digest = hashlib.sha256(f"{experiment_id}:{request_id}".encode()).hexdigest()
    bucket = int(digest[:8], 16) % 100
    return "treatment" if bucket < int(traffic_percent) else "control"


def compare_experiment_metrics(
    control_metrics: dict[str, float],
    treatment_metrics: dict[str, float],
) -> dict[str, Any]:
    """Compare quality, latency, cost, reliability across arms."""
    keys = sorted(set(control_metrics) | set(treatment_metrics))
    deltas = {k: round(treatment_metrics.get(k, 0.0) - control_metrics.get(k, 0.0), 4) for k in keys}
    return {
        "control": control_metrics,
        "treatment": treatment_metrics,
        "deltas": deltas,
        "winner": "treatment"
        if treatment_metrics.get("quality_proxy", 0) > control_metrics.get("quality_proxy", 0)
        and treatment_metrics.get("cost_usd", 1e9) <= control_metrics.get("cost_usd", 1e9) * 1.1
        else "control",
    }
