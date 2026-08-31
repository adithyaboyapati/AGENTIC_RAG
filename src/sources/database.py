"""SQLite research catalog — papers, benchmarks, and deployments."""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from langchain_core.documents import Document

from src.config import settings
from src.sources.documents import hit_to_document
from src.sources.seed import BENCHMARKS, DEPLOYMENTS, PAPERS
from src.sources.text import lexical_score, tokenize

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_seeded_path: str | None = None


def _db_path() -> Path:
    return Path(settings.knowledge_db_path)


def reset_database_cache() -> None:
    """Test helper: force the next search to re-seed."""
    global _seeded_path
    with _lock:
        _seeded_path = None


def _paper_body(row: dict) -> str:
    return (
        f"Internal research catalog (demo data). Paper {row['title']}. "
        f"Authors: {row['authors']}. Year: {row['year']}. Venue: {row['venue']}. "
        f"DOI: {row['doi']}. Citation count: {row['citation_count']}. "
        f"Topic: {row['topic']}. {row['summary']}"
    )


def _benchmark_body(row: dict) -> str:
    return (
        f"Internal research catalog (demo data). Benchmark for {row['system_name']} "
        f"on {row['dataset']} ({row['split']}). Metric {row['metric']} = {row['score']} "
        f"measured on {row['measured_on']}. {row['notes']}"
    )


def _deployment_body(row: dict) -> str:
    return (
        f"Internal research catalog (demo data). Deployment at {row['organization']} "
        f"uses {row['rag_pattern']}. Latency p95: {row['latency_p95_ms']} ms. "
        f"Monthly cost: ${row['monthly_cost_usd']}. Corpus size: "
        f"{row['corpus_size_docs']} documents. {row['notes']}"
    )


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS papers (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            authors TEXT NOT NULL,
            year INTEGER,
            venue TEXT,
            doi TEXT,
            citation_count INTEGER,
            topic TEXT,
            summary TEXT
        );
        CREATE TABLE IF NOT EXISTS benchmarks (
            id TEXT PRIMARY KEY,
            system_name TEXT NOT NULL,
            dataset TEXT NOT NULL,
            metric TEXT NOT NULL,
            score REAL NOT NULL,
            split TEXT,
            measured_on TEXT,
            notes TEXT
        );
        CREATE TABLE IF NOT EXISTS deployments (
            id TEXT PRIMARY KEY,
            organization TEXT NOT NULL,
            rag_pattern TEXT NOT NULL,
            latency_p95_ms INTEGER,
            monthly_cost_usd INTEGER,
            corpus_size_docs INTEGER,
            notes TEXT
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
            source_table,
            record_id,
            title,
            body
        );
        """
    )


def _seed_connection(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS knowledge_fts")
    _create_schema(conn)
    for row in PAPERS:
        conn.execute(
            """
            INSERT OR REPLACE INTO papers
            (id, title, authors, year, venue, doi, citation_count, topic, summary)
            VALUES (:id, :title, :authors, :year, :venue, :doi, :citation_count, :topic, :summary)
            """,
            row,
        )
        conn.execute(
            "INSERT INTO knowledge_fts (source_table, record_id, title, body) VALUES (?,?,?,?)",
            ("papers", row["id"], row["title"], _paper_body(row)),
        )
    for row in BENCHMARKS:
        conn.execute(
            """
            INSERT OR REPLACE INTO benchmarks
            (id, system_name, dataset, metric, score, split, measured_on, notes)
            VALUES (:id, :system_name, :dataset, :metric, :score, :split, :measured_on, :notes)
            """,
            row,
        )
        conn.execute(
            "INSERT INTO knowledge_fts (source_table, record_id, title, body) VALUES (?,?,?,?)",
            ("benchmarks", row["id"], row["system_name"], _benchmark_body(row)),
        )
    for row in DEPLOYMENTS:
        conn.execute(
            """
            INSERT OR REPLACE INTO deployments
            (id, organization, rag_pattern, latency_p95_ms, monthly_cost_usd,
             corpus_size_docs, notes)
            VALUES (:id, :organization, :rag_pattern, :latency_p95_ms, :monthly_cost_usd,
                    :corpus_size_docs, :notes)
            """,
            row,
        )
        conn.execute(
            "INSERT INTO knowledge_fts (source_table, record_id, title, body) VALUES (?,?,?,?)",
            ("deployments", row["id"], row["organization"], _deployment_body(row)),
        )
    conn.commit()


def ensure_seeded(path: Path | None = None) -> Path:
    """Create the catalog DB and seed demo rows (idempotent)."""
    global _seeded_path
    db_path = Path(path) if path is not None else _db_path()
    with _lock:
        if _seeded_path == str(db_path) and db_path.exists():
            return db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        try:
            _seed_connection(conn)
        finally:
            conn.close()
        _seeded_path = str(db_path)
        logger.info("Seeded knowledge catalog at %s", db_path)
        return db_path


def _connect() -> sqlite3.Connection:
    db_path = ensure_seeded()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _fts_match(query: str) -> str:
    tokens = sorted(tokenize(query))
    if not tokens:
        return ""
    return " OR ".join(f"{token}*" for token in tokens)


def search_database(query: str, top_k: int = 4) -> list[Document]:
    """Full-text search over the catalog; returns scored Documents."""
    if not (query or "").strip():
        return []
    min_score = settings.multi_source_min_score
    conn = _connect()
    try:
        match = _fts_match(query)
        rows: list[sqlite3.Row] = []
        if match:
            try:
                rows = list(
                    conn.execute(
                        """
                        SELECT source_table, record_id, title, body
                        FROM knowledge_fts
                        WHERE knowledge_fts MATCH ?
                        LIMIT 20
                        """,
                        (match,),
                    )
                )
            except sqlite3.OperationalError:
                rows = []
        if not rows:
            like = f"%{(query or '').strip()[:80]}%"
            rows = list(
                conn.execute(
                    """
                    SELECT source_table, record_id, title, body
                    FROM knowledge_fts
                    WHERE title LIKE ? OR body LIKE ?
                    LIMIT 20
                    """,
                    (like, like),
                )
            )
    finally:
        conn.close()

    scored: list[tuple[float, sqlite3.Row]] = []
    for row in rows:
        blob = f"{row['title']} {row['body']}"
        score = lexical_score(query, blob)
        if score >= min_score:
            scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)

    docs: list[Document] = []
    for score, row in scored[:top_k]:
        table = row["source_table"]
        record_id = row["record_id"]
        docs.append(
            hit_to_document(
                source_type="database",
                source=f"db://{table}/{record_id}",
                chunk_id=f"db-{table}-{record_id}",
                title=row["title"],
                body=row["body"],
                score=score,
                section=table,
            )
        )
    return docs


def catalog_counts() -> dict[str, int]:
    """Row counts for health checks."""
    conn = _connect()
    try:
        papers = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        benches = conn.execute("SELECT COUNT(*) FROM benchmarks").fetchone()[0]
        deploys = conn.execute("SELECT COUNT(*) FROM deployments").fetchone()[0]
    finally:
        conn.close()
    return {"papers": int(papers), "benchmarks": int(benches), "deployments": int(deploys)}
