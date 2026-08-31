"""Unit tests for retrieval formatting, citations, hybrid helpers, and rerank."""

from __future__ import annotations

from langchain_core.documents import Document

from src.agents.orchestrator import StrategyChoice, normalize_strategy
from src.ingestion.ingest import chunk_content_id
from src.retrieval.citations import build_response, docs_to_citations, docs_to_sources
from src.retrieval.retriever import _rrf_fuse, format_docs
from src.retrieval import reranker as reranker_mod


def test_format_docs_includes_page_and_chunk_id():
    docs = [
        Document(
            page_content="Hello RAG",
            metadata={
                "source": "rag.pdf",
                "page": 3,
                "chunk_id": "abc123",
                "section_title": "Naive RAG",
            },
        )
    ]
    text = format_docs(docs)
    assert "[1] Source: rag.pdf, page 3, section=Naive RAG (abc123)" in text
    assert "Hello RAG" in text


def test_format_docs_tags_extra_source_types():
    docs = [
        Document(
            page_content="Citation count: 1842",
            metadata={"source": "db://papers/crag", "source_type": "database", "chunk_id": "db-1"},
        )
    ]
    text = format_docs(docs)
    assert "[DATABASE]" in text
    assert "db://papers/crag" in text


def test_docs_to_sources_includes_page_label():
    docs = [
        Document(
            page_content="a",
            metadata={"source": "rag.pdf", "page": 1, "chunk_id": "1", "section_title": "A"},
        ),
        Document(
            page_content="b",
            metadata={"source": "rag.pdf", "page": 1, "chunk_id": "2", "section_title": "A"},
        ),
        Document(
            page_content="c",
            metadata={"source": "rag.pdf", "page": 2, "chunk_id": "3", "section_title": "B"},
        ),
    ]
    sources = docs_to_sources(docs)
    assert sources == ["rag.pdf#p1 [A]", "rag.pdf#p2 [B]"]


def test_build_response_populates_context_docs():
    docs = [
        Document(
            page_content="context chunk",
            metadata={
                "source": "x.pdf",
                "page": 0,
                "chunk_id": "c1",
                "section_title": "Intro",
            },
        )
    ]
    response = build_response(answer="ans", mode="baseline", docs=docs)
    assert response.context_docs == ["context chunk"]
    assert response.citations[0].chunk_id == "c1"
    assert response.citations[0].section == "Intro"
    assert response.sources == ["x.pdf#p0 [Intro]"]


def test_chunk_content_id_stable():
    doc = Document(page_content="same", metadata={"source": "a.pdf", "page": 1})
    assert chunk_content_id(doc) == chunk_content_id(doc)


def test_rrf_fuse_prefers_overlap():
    a = Document(page_content="overlap", metadata={"chunk_id": "shared"})
    b = Document(page_content="only-dense", metadata={"chunk_id": "dense"})
    c = Document(page_content="only-bm25", metadata={"chunk_id": "bm25"})
    fused = _rrf_fuse([[a, b], [a, c]], rrf_k=60)
    assert fused[0].metadata["chunk_id"] == "shared"
    assert "score" in fused[0].metadata


def test_normalize_strategy_clamps_invalid():
    assert normalize_strategy("not-a-real-strategy") == "simple"
    assert normalize_strategy("MULTI-HOP") == "multi_hop"
    assert StrategyChoice(strategy="tools", reasoning="ok").strategy == "tools"


def test_docs_to_citations_snippet_truncated():
    docs = [Document(page_content="x" * 500, metadata={"source": "s", "chunk_id": "id"})]
    citations = docs_to_citations(docs)
    assert len(citations[0].snippet) == 300


def test_rerank_flashrank_reorders_and_sets_scores(monkeypatch):
    docs = [
        Document(page_content="weak match", metadata={"chunk_id": "a", "score": 0.9}),
        Document(page_content="strong match about Self-RAG", metadata={"chunk_id": "b", "score": 0.1}),
        Document(page_content="noise", metadata={"chunk_id": "c", "score": 0.5}),
    ]

    class FakeRanker:
        def rerank(self, request):
            return [
                {"id": 1, "score": 0.95, "text": docs[1].page_content},
                {"id": 0, "score": 0.4, "text": docs[0].page_content},
                {"id": 2, "score": 0.1, "text": docs[2].page_content},
            ]

    monkeypatch.setattr(reranker_mod.settings, "rerank_enabled", True)
    monkeypatch.setattr(reranker_mod.settings, "rerank_provider", "flashrank")
    monkeypatch.setattr(reranker_mod.settings, "rerank_model", "ms-marco-MiniLM-L-12-v2")
    monkeypatch.setattr(reranker_mod, "_get_flashrank", lambda: FakeRanker())
    monkeypatch.setattr(reranker_mod, "_flashrank_failed", False)

    ranked = reranker_mod.rerank_documents("What is Self-RAG?", docs, top_n=2)
    assert [d.metadata["chunk_id"] for d in ranked] == ["b", "a"]
    assert ranked[0].metadata["rerank_score"] == 0.95
    assert ranked[0].metadata["score"] == 0.95
    assert ranked[0].metadata["retrieval_score"] == 0.1
    assert ranked[0].metadata["rerank_provider"] == "flashrank"


def test_rerank_nvidia_uses_api_rankings(monkeypatch):
    docs = [
        Document(page_content="weak", metadata={"chunk_id": "a", "score": 0.9}),
        Document(page_content="Self-RAG reflection tokens", metadata={"chunk_id": "b", "score": 0.2}),
    ]

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"rankings": [{"index": 1, "logit": 12.5}, {"index": 0, "logit": -1.0}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            assert "reranking" in url
            assert headers["Authorization"].startswith("Bearer ")
            assert json["model"] == "nvidia/nv-rerankqa-mistral-4b-v3"
            assert json["query"]["text"] == "What is Self-RAG?"
            assert len(json["passages"]) == 2
            return FakeResponse()

    monkeypatch.setattr(reranker_mod.settings, "rerank_enabled", True)
    monkeypatch.setattr(reranker_mod.settings, "rerank_provider", "nvidia")
    monkeypatch.setattr(reranker_mod.settings, "rerank_model", "nvidia/nv-rerankqa-mistral-4b-v3")
    monkeypatch.setattr(reranker_mod.settings, "nvidia_api_key", "nvapi-test-key")
    monkeypatch.setattr(reranker_mod.settings, "nvidia_rerank_url", "")
    monkeypatch.setattr(reranker_mod.httpx, "Client", FakeClient)

    ranked = reranker_mod.rerank_documents("What is Self-RAG?", docs, top_n=2)
    assert [d.metadata["chunk_id"] for d in ranked] == ["b", "a"]
    assert ranked[0].metadata["rerank_score"] == 12.5
    assert ranked[0].metadata["rerank_provider"] == "nvidia"


def test_rerank_disabled_keeps_order(monkeypatch):
    docs = [
        Document(page_content="first", metadata={"chunk_id": "1"}),
        Document(page_content="second", metadata={"chunk_id": "2"}),
    ]
    monkeypatch.setattr(reranker_mod.settings, "rerank_enabled", False)
    ranked = reranker_mod.rerank_documents("q", docs, top_n=1)
    assert ranked[0].metadata["chunk_id"] == "1"
    assert "rerank_score" not in ranked[0].metadata
