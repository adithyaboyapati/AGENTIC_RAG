"""
Section-aware parent–child chunking for structured PDFs.

Best fit for academic / LaTeX surveys (e.g. rag.pdf): a rich hierarchical
TOC defines semantic parents; long sections are split into smaller child
chunks for precise retrieval. At query time children expand back to the
parent section for generation context.

Fallback order:
  1. PDF outline / TOC bookmarks → section parents
  2. Regex heading detection (Markdown / numbered / Roman sections)
  3. Fixed-size RecursiveCharacterTextSplitter (legacy)
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.config import settings
from src.ingestion.cleanse import (
    CleanseStats,
    cleanse_config_from_settings,
    cleanse_page_documents,
    filter_irrelevant_parents,
    find_repeated_margin_lines,
    is_irrelevant_section_title,
    iter_clean_page_blocks,
)

logger = logging.getLogger(__name__)

_HEADING_RE = re.compile(
    r"^(?:"
    r"#{1,6}\s+.+"  # markdown
    r"|(?:[IVXLCDM]+)\.\s+[A-Z][A-Za-z0-9 ,/\-]{2,100}"  # Roman (I. INTRODUCTION)
    r"|\d+(?:\.\d+){0,3}\s+[A-Z][A-Za-z0-9 ,/\-]{2,100}"  # 3.2.1 Chunking
    r"|Abstract(?:—|-|\s).*"
    r"|References?\s*$"
    r")",
    re.MULTILINE,
)


@dataclass
class TocAnchor:
    level: int
    title: str
    page: int  # 0-based
    y: float
    nameddest: str = ""


def _stable_id(*parts: str) -> str:
    payload = "|".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _extract_span(
    doc: fitz.Document,
    start_page: int,
    start_y: float,
    end_page: int,
    end_y: float,
    *,
    repeated_keys: set[str] | None = None,
    stats: CleanseStats | None = None,
) -> str:
    """Extract cleansed text from (start_page, start_y) up to (end_page, end_y)."""
    cfg = cleanse_config_from_settings()
    # When cleansing is disabled, still extract via the same path but with
    # header/footer / noise filters turned off.
    if not settings.cleanse_enabled:
        cfg.drop_headers_footers = False
        cfg.drop_page_numbers = False
        cfg.drop_boilerplate = False
        cfg.drop_urls_only = False
        cfg.fix_hyphenation = False
        cfg.drop_table_scaffold = False
        repeated_keys = set()

    parts: list[str] = []
    for page_idx in range(start_page, end_page + 1):
        if page_idx < 0 or page_idx >= doc.page_count:
            continue
        page = doc[page_idx]
        for _x0, y0, _x1, y1, text in iter_clean_page_blocks(
            page,
            cfg=cfg,
            repeated_keys=repeated_keys or set(),
            stats=stats,
        ):
            if page_idx == start_page and y1 < start_y - 1:
                continue
            if page_idx == end_page and y0 >= end_y - 1:
                continue
            parts.append(text)
    return "\n\n".join(parts).strip()


def _load_toc_anchors(doc: fitz.Document) -> list[TocAnchor]:
    toc = doc.get_toc(simple=False)
    anchors: list[TocAnchor] = []
    for item in toc:
        level, title, page1 = item[0], str(item[1]).strip(), int(item[2])
        dest = item[3] if len(item) > 3 and isinstance(item[3], dict) else {}
        page = int(dest.get("page", page1 - 1))
        point = dest.get("to")
        y = float(point.y) if point is not None else 0.0
        anchors.append(
            TocAnchor(
                level=level,
                title=title,
                page=page,
                y=y,
                nameddest=str(dest.get("nameddest") or ""),
            )
        )
    return anchors


def _section_path(stack: list[str]) -> str:
    return " > ".join(stack)


def build_toc_parents(pdf_path: Path) -> list[Document]:
    """
    Build one parent Document per TOC entry.

    Span = start of this entry → start of the next TOC entry (any level).
    Also emits a synthetic 'Preamble / Abstract' parent before the first heading.
    Applies header/footer cleansing and drops irrelevant sections (e.g. References).
    """
    doc = fitz.open(pdf_path)
    try:
        anchors = _load_toc_anchors(doc)
        if len(anchors) < 2:
            return []

        cfg = cleanse_config_from_settings()
        stats = CleanseStats()
        repeated: set[str] = set()
        if settings.cleanse_enabled and cfg.drop_headers_footers:
            repeated = find_repeated_margin_lines(doc, cfg)

        parents: list[Document] = []
        source = str(pdf_path)

        # Preamble (title + abstract) before first TOC heading
        first = anchors[0]
        preamble = _extract_span(
            doc, 0, 0.0, first.page, first.y, repeated_keys=repeated, stats=stats
        )
        if preamble and len(preamble) > 80:
            parent_id = _stable_id(source, "preamble", preamble[:200])
            parents.append(
                Document(
                    page_content=preamble,
                    metadata={
                        "source": source,
                        "page": 0,
                        "section_title": "Preamble / Abstract",
                        "section_path": "Preamble / Abstract",
                        "section_level": 0,
                        "parent_id": parent_id,
                        "doc_type": "parent",
                        "nameddest": "",
                    },
                )
            )

        hierarchy: list[tuple[int, str]] = []
        for i, anchor in enumerate(anchors):
            # Skip bibliography / appendix / acknowledgments entirely
            if is_irrelevant_section_title(anchor.title, cfg):
                stats.sections_dropped += 1
                logger.info("Skipping irrelevant TOC section: %s", anchor.title)
                continue

            while hierarchy and hierarchy[-1][0] >= anchor.level:
                hierarchy.pop()
            hierarchy.append((anchor.level, anchor.title))
            path = _section_path([t for _, t in hierarchy])

            if i + 1 < len(anchors):
                nxt = anchors[i + 1]
                end_page, end_y = nxt.page, nxt.y
            else:
                end_page, end_y = doc.page_count - 1, float("inf")

            text = _extract_span(
                doc,
                anchor.page,
                anchor.y,
                end_page,
                end_y,
                repeated_keys=repeated,
                stats=stats,
            )
            if not text or len(text) < 40:
                continue

            parent_id = _stable_id(source, path, str(anchor.page), text[:200])
            parents.append(
                Document(
                    page_content=text,
                    metadata={
                        "source": source,
                        "page": anchor.page,
                        "section_title": anchor.title,
                        "section_path": path,
                        "section_level": anchor.level,
                        "parent_id": parent_id,
                        "doc_type": "parent",
                        "nameddest": anchor.nameddest,
                    },
                )
            )

        parents = filter_irrelevant_parents(parents, cfg=cfg, stats=stats)
        logger.info(
            "TOC section parents: %d from %s (%d outline entries) | cleanse=%s",
            len(parents),
            pdf_path.name,
            len(anchors),
            stats.as_dict(),
        )
        return parents
    finally:
        doc.close()


def build_regex_parents(pages: list[Document]) -> list[Document]:
    """Fallback: split concatenated page text on heading-like lines."""
    if not pages:
        return []
    source = str(pages[0].metadata.get("source", "unknown"))
    # Track page offsets roughly by joining with markers
    pieces: list[str] = []
    page_starts: list[tuple[int, int]] = []  # (char_offset, page)
    offset = 0
    for page_doc in pages:
        page_no = int(page_doc.metadata.get("page", 0) or 0)
        page_starts.append((offset, page_no))
        pieces.append(page_doc.page_content)
        offset += len(page_doc.page_content) + 2
    full = "\n\n".join(pieces)

    matches = list(_HEADING_RE.finditer(full))
    if len(matches) < 2:
        return []

    parents: list[Document] = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full)
        text = full[start:end].strip()
        if len(text) < 20:
            continue
        title = match.group(0).strip().lstrip("#").strip()
        # Map char offset → page
        page = 0
        for off, p in page_starts:
            if off <= start:
                page = p
            else:
                break
        parent_id = _stable_id(source, title, str(page), text[:200])
        parents.append(
            Document(
                page_content=text,
                metadata={
                    "source": source,
                    "page": page,
                    "section_title": title[:120],
                    "section_path": title[:120],
                    "section_level": 1,
                    "parent_id": parent_id,
                    "doc_type": "parent",
                    "nameddest": "",
                },
            )
        )
    logger.info("Regex section parents: %d from %s", len(parents), source)
    return parents


def parents_to_children(
    parents: list[Document],
    *,
    child_chunk_size: int | None = None,
    child_chunk_overlap: int | None = None,
) -> list[Document]:
    """Split parent sections into smaller child chunks for embedding/retrieval."""
    size = child_chunk_size if child_chunk_size is not None else settings.child_chunk_size
    overlap = (
        child_chunk_overlap
        if child_chunk_overlap is not None
        else settings.child_chunk_overlap
    )
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ". ", "; ", ", ", " ", ""],
    )

    children: list[Document] = []
    for parent in parents:
        parent_id = str(parent.metadata.get("parent_id"))
        section_title = str(parent.metadata.get("section_title", ""))
        section_path = str(parent.metadata.get("section_path", section_title))
        parts = splitter.split_text(parent.page_content)
        if not parts:
            continue
        # Tiny sections stay as a single child equal to the parent
        for idx, part in enumerate(parts):
            # Prepend breadcrumb so embeddings carry section context
            content = f"Section: {section_path}\n\n{part}"
            child_id = _stable_id(parent_id, str(idx), part)
            meta = {
                **dict(parent.metadata),
                "doc_type": "child",
                "chunk_id": child_id,
                "parent_id": parent_id,
                "child_index": idx,
                "child_total": len(parts),
                "section_title": section_title,
                "section_path": section_path,
            }
            children.append(Document(page_content=content, metadata=meta))
    return children


def fixed_size_chunks(
    pages: list[Document],
    *,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[Document]:
    """Legacy fixed-size chunking over page documents."""
    size = chunk_size if chunk_size is not None else settings.chunk_size
    overlap = chunk_overlap if chunk_overlap is not None else settings.chunk_overlap
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(pages)
    for chunk in chunks:
        chunk.metadata["doc_type"] = "child"
        chunk.metadata.setdefault("section_title", "")
        chunk.metadata.setdefault("section_path", "")
        chunk.metadata.setdefault("parent_id", "")
    return chunks


def chunk_documents(
    pdf_path: Path | None,
    pages: list[Document],
    *,
    strategy: str | None = None,
    child_chunk_size: int | None = None,
    child_chunk_overlap: int | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> tuple[list[Document], list[Document]]:
    """
    Returns (children_to_index, parents_for_store).

    Strategy `section_parent_child` (default for structured PDFs):
      TOC/regex parents → child splits.
    Strategy `fixed`: classic recursive character splitting (parents empty).
    """
    strategy = (strategy or settings.chunking_strategy).lower().strip()

    # Cleanse loader pages (used by fixed + regex fallback paths)
    working_pages = (
        cleanse_page_documents(pages) if settings.cleanse_enabled else pages
    )

    if strategy == "fixed":
        children = fixed_size_chunks(
            working_pages, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        return children, []

    parents: list[Document] = []
    if pdf_path is not None and pdf_path.exists():
        try:
            parents = build_toc_parents(pdf_path)
        except Exception:
            logger.exception("TOC parent extraction failed for %s", pdf_path)

    if not parents:
        parents = build_regex_parents(working_pages)
        if parents and settings.cleanse_enabled:
            parents = filter_irrelevant_parents(parents)

    if not parents:
        logger.warning(
            "No section structure found — falling back to fixed-size chunking for %s",
            pdf_path or "pages",
        )
        children = fixed_size_chunks(
            working_pages, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        return children, []

    children = parents_to_children(
        parents,
        child_chunk_size=child_chunk_size,
        child_chunk_overlap=child_chunk_overlap,
    )
    return children, parents
