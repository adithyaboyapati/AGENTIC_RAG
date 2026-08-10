"""Offline golden-set gate (no Chroma / OpenAI)."""

from src.evaluation.retrieval_metrics import (
    score_keyword_hits,
    validate_golden_set_offline,
)


def test_score_keyword_hits_basic():
    hit, recall, mrr, matched = score_keyword_hits(
        ["Corrective RAG grades documents and may rewrite the query"],
        ["corrective rag", "rewrite"],
    )
    assert hit is True
    assert recall == 1.0
    assert mrr == 1.0
    assert len(matched) == 2


def test_validate_golden_set_offline():
    report = validate_golden_set_offline()
    assert report["ok"] is True
    assert report["count"] >= 1
    assert report["errors"] == []


# ---------------------------------------------------------------------------
# Regression gate thresholds (used by the nightly eval workflow)
# ---------------------------------------------------------------------------


def test_thresholds_pass_on_healthy_report():
    from src.evaluation.retrieval_metrics import check_thresholds

    report = {"recall_at_k": 0.9, "mrr": 0.8, "hit_rate": 1.0}
    assert check_thresholds(
        report, min_recall=0.7, min_mrr=0.5, min_hit_rate=0.8
    ) == []


def test_thresholds_flag_each_regression():
    from src.evaluation.retrieval_metrics import check_thresholds

    report = {"recall_at_k": 0.4, "mrr": 0.2, "hit_rate": 0.5}
    failures = check_thresholds(
        report, min_recall=0.7, min_mrr=0.5, min_hit_rate=0.8
    )
    assert len(failures) == 3
    assert any("recall@k" in f for f in failures)
    assert any("MRR" in f for f in failures)
    assert any("hit_rate" in f for f in failures)


def test_threshold_boundary_is_inclusive():
    """Exactly meeting the floor must pass, not flake the nightly job."""
    from src.evaluation.retrieval_metrics import check_thresholds

    report = {"recall_at_k": 0.7, "mrr": 0.5, "hit_rate": 0.8}
    assert check_thresholds(
        report, min_recall=0.7, min_mrr=0.5, min_hit_rate=0.8
    ) == []
