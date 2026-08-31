"""Sample operations catalog API — HTTP surface plus in-process search."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.security import verify_api_key
from src.config import settings
from src.sources.documents import hit_to_document
from src.sources.seed import GLOSSARY, INCIDENTS, SYSTEMS
from src.sources.text import lexical_score, tokenize

router = APIRouter(prefix="/kb", tags=["sample-knowledge-api"])


def _glossary_body(row: dict) -> str:
    return (
        f"Ops catalog glossary (demo). Term '{row['term']}': {row['definition']}"
    )


def _system_body(row: dict) -> str:
    return (
        f"Ops catalog system (demo). id={row['id']} name={row['name']}. "
        f"Owner: {row['owner']}. Environment: {row['environment']}. "
        f"Replicas: {row['replicas']}. Index lag: {row['index_lag_seconds']} seconds. "
        f"Status: {row['status']}. On-call: {row['oncall']}."
    )


def _incident_body(row: dict) -> str:
    return (
        f"Ops catalog incident (demo). {row['id']} on {row['service']} "
        f"({row['severity']}) started {row['started_at']}. "
        f"Summary: {row['summary']} Resolution: {row['resolution']}"
    )


def _all_records() -> list[dict]:
    records: list[dict] = []
    for row in GLOSSARY:
        records.append(
            {
                "id": row["term"],
                "kind": "glossary",
                "title": row["term"],
                "body": _glossary_body(row),
            }
        )
    for row in SYSTEMS:
        records.append(
            {
                "id": row["id"],
                "kind": "system",
                "title": row["name"],
                "body": _system_body(row),
            }
        )
    for row in INCIDENTS:
        records.append(
            {
                "id": row["id"],
                "kind": "incident",
                "title": f"{row['id']} {row['service']}",
                "body": _incident_body(row),
            }
        )
    return records


def search_catalog(query: str, top_k: int = 4) -> list[dict]:
    """In-process catalog search used by retrieval and the HTTP API."""
    if not (query or "").strip():
        return []
    min_score = settings.multi_source_min_score
    q_tokens = tokenize(query)
    scored: list[tuple[float, dict]] = []
    for record in _all_records():
        blob = f"{record['id']} {record['title']} {record['body']}"
        score = lexical_score(query, blob)
        # Exact id / term hits (retriever-prod, INC-1042, index_lag)
        needle = (query or "").strip().lower()
        if record["id"].lower() in needle:
            score = max(score, 1.0)
        elif q_tokens and score < min_score:
            continue
        if score >= min_score:
            scored.append((score, record))
    scored.sort(key=lambda item: item[0], reverse=True)
    hits = []
    for score, record in scored[:top_k]:
        hits.append({**record, "score": round(float(score), 4)})
    return hits


def search_api(query: str, top_k: int = 4):
    """Return catalog hits as Documents for the retriever / tools."""
    from langchain_core.documents import Document

    docs: list[Document] = []
    for hit in search_catalog(query, top_k=top_k):
        docs.append(
            hit_to_document(
                source_type="api",
                source=f"api://{hit['kind']}/{hit['id']}",
                chunk_id=f"api-{hit['kind']}-{hit['id']}",
                title=hit["title"],
                body=hit["body"],
                score=float(hit["score"]),
                section=hit["kind"],
            )
        )
    return docs


def catalog_status() -> dict:
    return {
        "glossary": len(GLOSSARY),
        "systems": len(SYSTEMS),
        "incidents": len(INCIDENTS),
    }


@router.get("/v1/health")
def kb_health(_: None = Depends(verify_api_key)) -> dict:
    return {"status": "ok", "service": "sample-knowledge-api", "counts": catalog_status()}


@router.get("/v1/search")
def kb_search(
    q: str = Query(..., min_length=1, max_length=400),
    top_k: int = Query(4, ge=1, le=10),
    _: None = Depends(verify_api_key),
) -> dict:
    return {"query": q, "results": search_catalog(q, top_k=top_k)}


@router.get("/v1/glossary")
def kb_glossary(_: None = Depends(verify_api_key)) -> dict:
    return {"items": GLOSSARY}


@router.get("/v1/glossary/{term}")
def kb_glossary_term(term: str, _: None = Depends(verify_api_key)) -> dict:
    key = term.strip().lower()
    for row in GLOSSARY:
        if row["term"].lower() == key:
            return row
    raise HTTPException(status_code=404, detail=f"Unknown glossary term: {term}")


@router.get("/v1/systems")
def kb_systems(_: None = Depends(verify_api_key)) -> dict:
    return {"items": SYSTEMS}


@router.get("/v1/systems/{system_id}")
def kb_system(system_id: str, _: None = Depends(verify_api_key)) -> dict:
    key = system_id.strip().lower()
    for row in SYSTEMS:
        if row["id"].lower() == key:
            return row
    raise HTTPException(status_code=404, detail=f"Unknown system: {system_id}")


@router.get("/v1/incidents")
def kb_incidents(_: None = Depends(verify_api_key)) -> dict:
    return {"items": INCIDENTS}


@router.get("/v1/incidents/{incident_id}")
def kb_incident(incident_id: str, _: None = Depends(verify_api_key)) -> dict:
    key = incident_id.strip().lower()
    for row in INCIDENTS:
        if row["id"].lower() == key:
            return row
    raise HTTPException(status_code=404, detail=f"Unknown incident: {incident_id}")
