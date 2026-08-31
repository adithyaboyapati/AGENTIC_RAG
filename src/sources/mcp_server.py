"""Lab-notes MCP server (JSON-RPC 2.0) plus in-process retrieval.

The same knowledge is reachable three ways:
  - In-process ``search_mcp()`` used by federated retrieval and LangChain tools
  - HTTP ``POST /mcp`` on the Agentic RAG API
  - stdio: ``python -m src.sources.mcp_server`` (Cursor / Claude Desktop)

Protocol version: 2024-11-05 (tools + resources).
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from src.api.security import verify_api_key
from src.config import settings
from src.sources.documents import hit_to_document
from src.sources.seed import EXPERIMENTS, LAB_NOTES, RUNBOOKS
from src.sources.text import lexical_score, tokenize

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "agentic-rag-lab"
SERVER_VERSION = "1.0.0"

mcp_router = APIRouter(tags=["mcp"])

_TOOLS = [
    {
        "name": "search_lab_knowledge",
        "description": (
            "Search unpublished lab experiments, runbooks, and notes. "
            "Use for exp-* IDs, chunking ablations, and BM25 rebuild steps."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language search query"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_experiment",
        "description": "Fetch one lab experiment by id (e.g. exp-42).",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
    {
        "name": "get_runbook",
        "description": "Fetch one operational runbook by id (e.g. rb-bm25).",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
]


def _experiment_body(row: dict) -> str:
    return (
        f"Lab MCP experiment (demo). {row['id']} ({row['date']}): {row['title']}. "
        f"Conclusion: {row['conclusion']} Metrics: {row['metrics']}"
    )


def _runbook_body(row: dict) -> str:
    return f"Lab MCP runbook (demo). {row['id']}: {row['title']}. Steps: {row['steps']}"


def _note_body(row: dict) -> str:
    return (
        f"Lab MCP note (demo). {row['id']} ({row['date']}) by {row['author']}: {row['body']}"
    )


def _all_records() -> list[dict]:
    records: list[dict] = []
    for row in EXPERIMENTS:
        records.append(
            {
                "id": row["id"],
                "kind": "experiment",
                "title": row["title"],
                "body": _experiment_body(row),
                "uri": f"lab://experiments/{row['id']}",
            }
        )
    for row in RUNBOOKS:
        records.append(
            {
                "id": row["id"],
                "kind": "runbook",
                "title": row["title"],
                "body": _runbook_body(row),
                "uri": f"lab://runbooks/{row['id']}",
            }
        )
    for row in LAB_NOTES:
        records.append(
            {
                "id": row["id"],
                "kind": "note",
                "title": row["id"],
                "body": _note_body(row),
                "uri": f"lab://notes/{row['id']}",
            }
        )
    return records


def search_lab_knowledge(query: str, top_k: int = 4) -> list[dict]:
    if not (query or "").strip():
        return []
    min_score = settings.multi_source_min_score
    needle = (query or "").strip().lower()
    scored: list[tuple[float, dict]] = []
    for record in _all_records():
        blob = f"{record['id']} {record['title']} {record['body']}"
        score = lexical_score(query, blob)
        if record["id"].lower() in needle:
            score = max(score, 1.0)
        if tokenize(query) and score < min_score:
            continue
        if score >= min_score:
            scored.append((score, record))
    scored.sort(key=lambda item: item[0], reverse=True)
    hits = []
    for score, record in scored[:top_k]:
        hits.append({**record, "score": round(float(score), 4)})
    return hits


def search_mcp(query: str, top_k: int = 4):
    """Return lab MCP hits as Documents."""
    from langchain_core.documents import Document

    docs: list[Document] = []
    for hit in search_lab_knowledge(query, top_k=top_k):
        docs.append(
            hit_to_document(
                source_type="mcp",
                source=hit["uri"],
                chunk_id=f"mcp-{hit['kind']}-{hit['id']}",
                title=hit["title"],
                body=hit["body"],
                score=float(hit["score"]),
                section=hit["kind"],
            )
        )
    return docs


def _get_experiment(exp_id: str) -> dict | None:
    key = (exp_id or "").strip().lower()
    for row in EXPERIMENTS:
        if row["id"].lower() == key:
            return row
    return None


def _get_runbook(runbook_id: str) -> dict | None:
    key = (runbook_id or "").strip().lower()
    for row in RUNBOOKS:
        if row["id"].lower() == key:
            return row
    return None


def _resource_list() -> list[dict]:
    resources = []
    for record in _all_records():
        resources.append(
            {
                "uri": record["uri"],
                "name": record["title"],
                "description": f"{record['kind']} {record['id']}",
                "mimeType": "text/plain",
            }
        )
    return resources


def _read_resource(uri: str) -> str | None:
    for record in _all_records():
        if record["uri"] == uri:
            return record["body"]
    return None


def _tool_text_result(text: str, *, is_error: bool = False) -> dict:
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def _call_tool(name: str, arguments: dict[str, Any] | None) -> dict:
    args = arguments or {}
    if name == "search_lab_knowledge":
        query = str(args.get("query") or "")
        hits = search_lab_knowledge(query)
        if not hits:
            return _tool_text_result("No lab knowledge matched the query.", is_error=False)
        parts = [f"{h['id']}: {h['body']}" for h in hits]
        return _tool_text_result("\n\n".join(parts))
    if name == "get_experiment":
        row = _get_experiment(str(args.get("id") or ""))
        if row is None:
            return _tool_text_result("Unknown experiment id.", is_error=True)
        return _tool_text_result(_experiment_body(row))
    if name == "get_runbook":
        row = _get_runbook(str(args.get("id") or ""))
        if row is None:
            return _tool_text_result("Unknown runbook id.", is_error=True)
        return _tool_text_result(_runbook_body(row))
    return _tool_text_result(f"Unknown tool: {name}", is_error=True)


def _rpc_error(rpc_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


def handle_rpc(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Handle one JSON-RPC request. Notifications return None."""
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        return _rpc_error(payload.get("id") if isinstance(payload, dict) else None, -32600, "Invalid Request")

    method = payload.get("method")
    rpc_id = payload.get("id")
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        params = {}

    # Notifications have no id
    is_notification = "id" not in payload

    if method == "notifications/initialized":
        return None
    if method == "ping":
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}
    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}, "resources": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
        return {"jsonrpc": "2.0", "id": rpc_id, "result": result}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": _TOOLS}}
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        return {"jsonrpc": "2.0", "id": rpc_id, "result": _call_tool(name, arguments)}
    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"resources": _resource_list()}}
    if method == "resources/read":
        uri = str(params.get("uri") or "")
        text = _read_resource(uri)
        if text is None:
            return _rpc_error(rpc_id, -32002, f"Unknown resource: {uri}")
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "contents": [{"uri": uri, "mimeType": "text/plain", "text": text}],
            },
        }

    if is_notification:
        return None
    return _rpc_error(rpc_id, -32601, f"Method not found: {method}")


def mcp_status() -> dict:
    return {
        "tools": len(_TOOLS),
        "experiments": len(EXPERIMENTS),
        "runbooks": len(RUNBOOKS),
        "notes": len(LAB_NOTES),
    }


@mcp_router.post("/mcp")
async def mcp_http(request: Request, _: None = Depends(verify_api_key)):
    """JSON-RPC 2.0 MCP endpoint (tools/list, tools/call, resources/*)."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
            status_code=400,
        )
    if not isinstance(payload, dict):
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}},
            status_code=400,
        )
    result = handle_rpc(payload)
    if result is None:
        return JSONResponse({"ok": True}, status_code=202)
    status = 200 if "result" in result else 400
    return JSONResponse(result, status_code=status)


def _read_stdio_message() -> dict | None:
    """Read one LSP-style Content-Length framed JSON object from stdin."""
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        decoded = line.decode("utf-8", errors="replace").strip()
        if ":" in decoded:
            key, value = decoded.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    length_raw = headers.get("content-length")
    if not length_raw:
        return None
    try:
        length = int(length_raw)
    except ValueError:
        return None
    body = sys.stdin.buffer.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def _write_stdio_message(payload: dict) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


def main_stdio() -> None:
    """Serve MCP over stdio (Content-Length framing)."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    logger.info("MCP lab server listening on stdio (%s)", SERVER_NAME)
    while True:
        try:
            message = _read_stdio_message()
        except json.JSONDecodeError:
            logger.warning("MCP stdio parse error")
            continue
        if message is None:
            return
        response = handle_rpc(message)
        if response is not None:
            _write_stdio_message(response)


if __name__ == "__main__":
    main_stdio()
