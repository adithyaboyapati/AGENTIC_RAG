"""Phase 7 legacy retirement readiness and inventory tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import settings
from src.evaluation.legacy_retirement import (
    CANONICAL_PIPELINE_VERSION,
    LegacyRetirementStatus,
    evaluate_legacy_retirement_readiness,
    inventory_table,
    legacy_dependency_inventory,
)


def test_canonical_pipeline_version_is_v1():
    assert CANONICAL_PIPELINE_VERSION == "v1"


def test_legacy_graph_files_removed():
    graph_dir = Path(__file__).resolve().parents[1] / "src" / "graph"
    removed = [
        "router_graph.py",
        "crag_graph.py",
        "decompose_graph.py",
        "multi_hop_graph.py",
        "tools_graph.py",
        "agent_graph.py",
        "consensus_graph.py",
    ]
    for name in removed:
        assert not (graph_dir / name).exists(), f"legacy graph still present: {name}"


def test_baseline_rag_module_removed():
    assert not (Path(__file__).resolve().parents[1] / "src" / "rag" / "baseline.py").exists()


def test_inventory_table_has_runtime_critical_entries():
    rows = inventory_table()
    assert rows
    critical = [r for r in rows if r["runtime_critical"]]
    components = {r["component"] for r in critical}
    assert any("shared_nodes" in c for c in components)
    assert any("generation" in c for c in components)


def test_evaluate_legacy_retirement_readiness_returns_status():
    evaluation = evaluate_legacy_retirement_readiness()
    assert evaluation.status in LegacyRetirementStatus
    assert evaluation.inventory_count == len(legacy_dependency_inventory())


def test_canonical_primary_enables_deprecation_or_removal():
    assert settings.canonical_primary is True
    evaluation = evaluate_legacy_retirement_readiness()
    assert evaluation.status in {
        LegacyRetirementStatus.READY_FOR_DEPRECATION,
        LegacyRetirementStatus.READY_FOR_REMOVAL,
    }


def test_legacy_runtime_disabled_by_default():
    assert settings.legacy_runtime_enabled is False
    assert settings.legacy_fallback_enabled is False
