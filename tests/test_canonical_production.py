"""Production hardening tests for Phase 4 canonical graph."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.cache.semantic_cache import SemanticCache
from src.contracts.models import VerificationResult
from src.graph.citation_mapper import map_citations, scan_citation_markers
from src.graph.verification_engine import VerificationInput, derive_response_status, verify_response
from src.ingestion.job_store import IngestionJobStore, _deserialize_job
from src.ingestion.queue import IngestionJob, IngestionJobStatus, IngestionQueue
from src.retrieval.canonical_adapter import retrieve_candidates
from src.schemas import RBACContext
from src.security.ssrf import OutboundUrlPolicy, UnsafeOutboundUrl, validate_outbound_url
from src.tools.safe_web import filter_safe_urls


@pytest.fixture(autouse=True)
def disable_llm_verification(monkeypatch):
    monkeypatch.setattr(
        "src.config.settings.canonical_verification_llm_enabled",
        False,
    )


class TestOutboundSecurity:
    def test_blocks_private_ips(self):
        blocked = [
            "http://127.0.0.1",
            "http://localhost",
            "http://169.254.169.254",
            "http://10.0.0.1",
            "http://172.16.0.1",
            "http://192.168.1.1",
            "file:///etc/passwd",
            "ftp://example.com",
        ]
        for url in blocked:
            with pytest.raises(UnsafeOutboundUrl):
                validate_outbound_url(url)

    def test_allows_public_https_without_resolution(self):
        policy = OutboundUrlPolicy(resolve_dns=False)
        assert (
            validate_outbound_url("https://example.com", policy=policy)
            == "https://example.com"
        )

    def test_filter_safe_urls_blocks_internal(self):
        allowed, blocked = filter_safe_urls(
            ["http://127.0.0.1/x", "https://example.com"],
            policy=OutboundUrlPolicy(resolve_dns=False),
        )
        assert blocked
        assert allowed == ["https://example.com"]


class TestCitationSecurity:
    def test_malformed_citation_markers(self):
        valid, malformed, zero = scan_citation_markers("Bad [abc] [0] [-1] ok [1]")
        assert 1 in valid
        assert "[abc]" in malformed
        assert 0 in zero

    def test_map_rejects_unknown_and_duplicate(self):
        ev = _evidence_for_test()
        citations, unknown, dup, malformed, zero = map_citations("See [1][1] and [99]", [ev])
        assert unknown == [99]
        assert dup == [1]
        assert malformed == []
        assert zero == []


def _evidence_for_test():
    from langchain_core.documents import Document

    from src.contracts.conversions import document_to_retrieval_result, retrieval_result_to_evidence

    result = document_to_retrieval_result(
        Document(page_content="Tenant A secret policy text.", metadata={"chunk_id": "c1"}),
        query_id="q",
    )
    return retrieval_result_to_evidence(
        result,
        index=1,
        shown_to_generation=True,
    ).model_copy(update={"included_in_context": True, "context_position": 1})


class TestVerificationOutcomes:
    def test_pass_warn_fail_abstain(self):
        shown = _evidence_for_test()
        passed = verify_response(
            VerificationInput(
                question="What is the policy?",
                answer="The policy covers retention and access [1].",
                context_evidence=[shown],
                citations=[],
                unknown_citation_indexes=[],
            )
        )
        assert passed.outcome in {"PASS", "WARN"}
        assert passed.verified_evidence_ids == (shown.evidence_id,)

        failed = verify_response(
            VerificationInput(
                question="What is the policy?",
                answer="",
                context_evidence=[shown],
                citations=[],
                unknown_citation_indexes=[],
            )
        )
        assert failed.outcome == "FAIL"
        assert failed.abstained is True
        assert derive_response_status(failed) == "abstained"

    def test_verified_evidence_invariant(self):
        shown = _evidence_for_test()
        result = verify_response(
            VerificationInput(
                question="Q",
                answer="Grounded answer with enough detail for gate.",
                context_evidence=[shown],
                citations=[],
                unknown_citation_indexes=[],
            )
        )
        assert result.verified_evidence_ids == (shown.evidence_id,)


class TestTenantIsolation:
    def test_tenant_b_cannot_see_tenant_a_pdf_metadata(self):
        doc = MagicMock()
        doc.metadata = {
            "chunk_id": "secret",
            "tenant_id": "tenant_a",
            "access_groups": "tenant_a",
            "classification": "confidential",
        }
        with patch("src.retrieval.canonical_adapter.retrieve", return_value=[doc]):
            results = retrieve_candidates(
                "policy",
                query_id="q",
                rbac_context=RBACContext(tenant_id="tenant_b", user_roles=["tenant_b"]),
            )
        assert results == []


class TestDistributedState:
    def test_semantic_cache_survives_redis_failure(self, monkeypatch):
        class BrokenBackend:
            def lookup(self, **kwargs):
                raise RuntimeError("redis down")

        monkeypatch.setattr(
            "src.cache.semantic_cache_redis.get_redis_semantic_backend",
            lambda: BrokenBackend(),
        )
        cache = SemanticCache(max_entries=10)
        with patch.object(cache, "_get_embedding", return_value=[1.0, 0.0]):
            assert cache.lookup("q", "canonical") is None

    def test_ingestion_job_restart_like_restore(self):
        store = IngestionJobStore()
        job = IngestionJob(
            job_id="job-restart1",
            status=IngestionJobStatus.QUEUED,
            source_paths=["/tmp/x.pdf"],
            tenant_id="tenant_a",
        )
        if not store.available():
            restored = _deserialize_job(job.to_dict())
            assert restored.tenant_id == "tenant_a"
            return
        store.save(job)
        queue = IngestionQueue(max_workers=1)
        queue._jobs.clear()
        loaded = queue.get_job(job.job_id)
        assert loaded is not None
        assert loaded.tenant_id == "tenant_a"


class TestReliabilityInjection:
    def test_verification_judge_timeout_degrades(self, monkeypatch):
        shown = _evidence_for_test()

        def _boom(*args, **kwargs):
            raise TimeoutError("judge timeout")

        monkeypatch.setattr(
            "src.graph.verification_engine._llm_faithfulness",
            lambda *args, **kwargs: (None, "faithfulness_judge_failed"),
        )
        monkeypatch.setattr(
            "src.graph.verification_engine._llm_answer_relevance",
            lambda *args, **kwargs: (None, "relevance_judge_failed"),
        )
        monkeypatch.setattr(
            "src.config.settings.canonical_verification_llm_enabled",
            True,
        )
        result = verify_response(
            VerificationInput(
                question="Q",
                answer="Grounded answer with enough detail for gate.",
                context_evidence=[shown],
                citations=[],
                unknown_citation_indexes=[],
            )
        )
        assert result.outcome in {"PASS", "WARN", "FAIL"}
        assert "faithfulness_judge_failed" in (result.flagged_reason or "")

    def test_bounded_retries_no_infinite_loop(self):
        from src.graph.canonical_graph import route_after_grade, route_after_reflect
        from src.graph.canonical_state import init_canonical_state, merge_state

        for max_retries in (0, 1, 2):
            state = merge_state(
                init_canonical_state("Q"),
                retry_count=max_retries,
                evidence=(),
            )
            assert route_after_grade({"canonical": state.model_dump(mode="json")}) in {
                "rewrite",
                "web_fallback",
                "abort",
            }

        for hops in (1, 2, 3):
            state = merge_state(
                init_canonical_state("Q"),
                current_hop=hops,
                strategy="multi_hop",
                metadata={"reflection_done": True},
            )
            nxt = route_after_reflect({"canonical": state.model_dump(mode="json")})
            assert nxt in {"context", "abort", "plan_retrieval"}


class TestObservability:
    def test_verify_emits_timing_metadata(self):
        from src.graph.canonical_graph import verify_node
        from src.graph.canonical_state import init_canonical_state, merge_state

        shown = _evidence_for_test()
        state = merge_state(
            init_canonical_state("Q"),
            answer="Grounded answer with enough detail for gate.",
            evidence=(shown,),
            citations=(),
            generation_evidence_ids=(shown.evidence_id,),
        )
        update = verify_node({"canonical": state.model_dump(mode="json"), "trace_delta": []})
        parsed = json.loads(json.dumps(update["canonical"]))
        trace = parsed.get("trace", [])
        timing_events = [t for t in trace if t.get("event_type") == "verification_completed"]
        assert timing_events
