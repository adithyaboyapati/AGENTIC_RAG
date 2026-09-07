"""Convert extra-source hits into LangChain Documents."""

from __future__ import annotations

from langchain_core.documents import Document


def hit_to_document(
    *,
    source_type: str,
    source: str,
    chunk_id: str,
    title: str,
    body: str,
    score: float,
    section: str | None = None,
) -> Document:
    """Build a Document with stable provenance metadata for citations."""
    header = title.strip()
    content = f"{header}\n{body.strip()}".strip() if header else body.strip()
    meta = {
        "source": source,
        "source_type": source_type,
        "chunk_id": chunk_id,
        "section_title": section or title,
        "score": float(score),
        "page": None,
        # Shared reference catalog — public read, not tenant-owned content.
        "tenant_id": "public",
        "access_groups": "public",
        "classification": "public",
    }
    return Document(page_content=content, metadata=meta)
