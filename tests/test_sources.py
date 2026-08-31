"""Tests for extra knowledge sources: SQLite, sample API, MCP, federation."""

from __future__ import annotations

from langchain_core.documents import Document

from src.resilience.node_gate import PREFIX_TOOL_EMPTY
from src.sources.database import catalog_counts, reset_database_cache, search_database
from src.sources.federation import (
    RETRIEVAL_TOOL_NAMES,
    documents_for_tool,
    merge_with_pdf,
    parse_extra_sources,
    search_extra_sources,
)
from src.sources.mcp_server import handle_rpc, search_mcp
from src.sources.sample_api import search_api, search_catalog
from src.sources.text import lexical_score, tokenize
from src.tools.all_tools import TOOLS, query_api, query_database, query_mcp


def test_tokenize_stems_and_drops_stopwords():
    tokens = tokenize("How many citations does the CRAG paper have?")
    assert "citation" in tokens
    assert "crag" in tokens
    assert "paper" in tokens
    assert "how" not in tokens
    assert "the" not in tokens


def test_lexical_score_rewards_overlap():
    text = "Paper CRAG citation count 1842 venue ICLR"
    assert lexical_score("CRAG paper citations", text) >= 0.9
    assert lexical_score("hello there", text) == 0.0


def test_database_finds_crag_citation_count(tmp_path, monkeypatch):
    db_path = tmp_path / "knowledge.db"
    monkeypatch.setattr("src.config.settings.knowledge_db_path", str(db_path))
    reset_database_cache()
    docs = search_database("How many citations does the CRAG paper have?")
    assert docs
    blob = docs[0].page_content
    assert "1842" in blob
    assert docs[0].metadata["source_type"] == "database"
    assert docs[0].metadata["source"].startswith("db://papers/")
    counts = catalog_counts()
    assert counts["papers"] == 3
    assert counts["benchmarks"] == 3


def test_database_finds_ndcg_benchmark(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.settings.knowledge_db_path", str(tmp_path / "kb.db"))
    reset_database_cache()
    docs = search_database("What is Hybrid-RAG nDCG@10 on MS MARCO?")
    assert docs
    assert "0.71" in docs[0].page_content


def test_database_ignores_unrelated_chitchat(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.settings.knowledge_db_path", str(tmp_path / "kb.db"))
    reset_database_cache()
    assert search_database("Hello how are you today?") == []


def test_api_finds_retriever_owner():
    docs = search_api("Who owns retriever-prod?")
    assert docs
    assert "platform-search" in docs[0].page_content
    assert docs[0].metadata["source_type"] == "api"


def test_api_finds_incident():
    hits = search_catalog("INC-1042 rerank p95")
    assert hits
    assert any("2100ms" in h["body"] or "2100" in h["body"] for h in hits)


def test_mcp_finds_experiment_42():
    docs = search_mcp("What did experiment 42 conclude about parent-child chunking?")
    assert docs
    assert "12%" in docs[0].page_content
    assert docs[0].metadata["source"].startswith("lab://experiments/")


def test_mcp_finds_bm25_runbook():
    docs = search_mcp("How do I rebuild a stale BM25 index?")
    assert docs
    assert "invalidate_bm25_cache" in docs[0].page_content


def test_mcp_initialize_and_tools_call():
    init = handle_rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    )
    assert init["result"]["serverInfo"]["name"] == "agentic-rag-lab"
    listed = handle_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in listed["result"]["tools"]}
    assert "search_lab_knowledge" in names
    called = handle_rpc(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_experiment", "arguments": {"id": "exp-42"}},
        }
    )
    text = called["result"]["content"][0]["text"]
    assert "exp-42" in text
    assert "12%" in text


def test_mcp_resources_read():
    listed = handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "resources/list"})
    uris = [r["uri"] for r in listed["result"]["resources"]]
    assert "lab://experiments/exp-42" in uris
    read = handle_rpc(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "resources/read",
            "params": {"uri": "lab://experiments/exp-42"},
        }
    )
    assert "Parent-child" in read["result"]["contents"][0]["text"]


def test_mcp_unknown_method():
    err = handle_rpc({"jsonrpc": "2.0", "id": 9, "method": "nope/nope"})
    assert err["error"]["code"] == -32601


def test_parse_extra_sources_stable_order():
    assert parse_extra_sources("mcp, database,api,pdf") == ["database", "api", "mcp"]


def test_federation_merges_extra_ahead_of_pdf():
    extra = [
        Document(page_content="db hit", metadata={"chunk_id": "db-1", "source": "db://x"})
    ]
    pdf = [
        Document(page_content="pdf hit", metadata={"chunk_id": "pdf-1", "source": "rag.pdf"})
    ]
    merged = merge_with_pdf(pdf, extra)
    assert [d.metadata["chunk_id"] for d in merged] == ["db-1", "pdf-1"]


def test_search_extra_sources_routes_to_right_backends(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.settings.knowledge_db_path", str(tmp_path / "kb.db"))
    monkeypatch.setattr("src.config.settings.multi_source_enabled", True)
    monkeypatch.setattr("src.config.settings.extra_sources", "database,api,mcp")
    reset_database_cache()

    db_hits = search_extra_sources("CRAG citation count", sources=["database"])
    assert any(d.metadata.get("source_type") == "database" for d in db_hits)

    api_hits = search_extra_sources("Who owns retriever-prod", sources=["api"])
    assert any(d.metadata.get("source_type") == "api" for d in api_hits)

    mcp_hits = search_extra_sources("exp-42 parent-child", sources=["mcp"])
    assert any(d.metadata.get("source_type") == "mcp" for d in mcp_hits)


def test_tools_registered_include_new_sources():
    names = {t.name for t in TOOLS}
    assert RETRIEVAL_TOOL_NAMES <= names
    assert {"query_database", "query_api", "query_mcp"} <= names


def test_query_database_tool_formats_hits(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.settings.knowledge_db_path", str(tmp_path / "kb.db"))
    reset_database_cache()
    out = query_database.invoke({"query": "Self-RAG citation count"})
    assert "2104" in out
    assert "[DATABASE]" in out


def test_query_api_and_mcp_tools():
    api_out = query_api.invoke({"query": "retriever-prod owner"})
    assert "platform-search" in api_out
    assert "[API]" in api_out
    mcp_out = query_mcp.invoke({"query": "exp-42"})
    assert "12%" in mcp_out
    assert "[MCP]" in mcp_out


def test_query_tools_empty_sentinels():
    empty_db = query_database.invoke({"query": "zzzz-not-a-real-record"})
    assert str(empty_db).startswith(PREFIX_TOOL_EMPTY)
    empty_api = query_api.invoke({"query": "zzzz-not-a-real-record"})
    assert str(empty_api).startswith(PREFIX_TOOL_EMPTY)
    empty_mcp = query_mcp.invoke({"query": "zzzz-not-a-real-record"})
    assert str(empty_mcp).startswith(PREFIX_TOOL_EMPTY)


def test_documents_for_tool_database(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.settings.knowledge_db_path", str(tmp_path / "kb.db"))
    reset_database_cache()
    docs = documents_for_tool("query_database", "CRAG citation count")
    assert docs
    assert docs[0].metadata["source_type"] == "database"


def test_retrieve_prepends_extra_source_hits(monkeypatch):
    from src.retrieval.retriever import retrieve

    pdf = [
        Document(
            page_content="pdf chunk",
            metadata={"chunk_id": "p1", "source": "rag.pdf"},
        )
    ]
    extra = [
        Document(
            page_content="db chunk",
            metadata={
                "chunk_id": "db-1",
                "source": "db://papers/crag",
                "source_type": "database",
                "score": 1.0,
            },
        )
    ]
    monkeypatch.setattr("src.retrieval.retriever.settings.multi_source_enabled", True)
    monkeypatch.setattr("src.retrieval.retriever.settings.expand_to_parent", False)
    monkeypatch.setattr("src.retrieval.retriever.settings.rerank_enabled", False)
    monkeypatch.setattr("src.retrieval.retriever.settings.retrieval_search_type", "similarity")
    monkeypatch.setattr("src.retrieval.retriever._dense_retrieve", lambda *a, **k: pdf)
    monkeypatch.setattr("src.sources.federation.search_extra_sources", lambda *a, **k: extra)

    docs = retrieve("CRAG citations", top_k=4)
    assert [d.metadata["chunk_id"] for d in docs] == ["db-1", "p1"]
