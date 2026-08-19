"""
Structured Table Extraction and Markdown Conversion for PDFs.

Uses PyMuPDF (fitz) page.find_tables() to identify table bounding boxes,
extract headers and data cells, and produce clean GitHub-flavored Markdown tables.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

import fitz  # PyMuPDF
from langchain_core.documents import Document

logger = logging.getLogger(__name__)


@dataclass
class ExtractedTable:
    """Represents a structured table extracted from a PDF page."""

    table_id: str
    page: int  # 0-indexed
    bbox: tuple[float, float, float, float]
    num_rows: int
    num_cols: int
    markdown: str
    caption: str = ""

    def to_document(self, source: str = "", section_path: str = "") -> Document:
        """Convert extracted table into a LangChain Document chunk."""
        meta = {
            "source": source,
            "page": self.page + 1,
            "chunk_type": "table",
            "table_id": self.table_id,
            "num_rows": self.num_rows,
            "num_cols": self.num_cols,
            "bbox": list(self.bbox),
        }
        if section_path:
            meta["section_path"] = section_path
        if self.caption:
            meta["caption"] = self.caption

        caption_prefix = f"Table ({self.caption}):\n" if self.caption else "Table:\n"
        content = f"{caption_prefix}{self.markdown}"
        return Document(page_content=content, metadata=meta)


def table_to_markdown(table_data: list[list[str | None]]) -> str:
    """Convert 2D matrix of table cell strings into a GitHub-flavored Markdown table."""
    if not table_data or not table_data[0]:
        return ""

    # Clean cell text (replace newlines with space, strip whitespace, escape pipes)
    cleaned_rows: list[list[str]] = []
    for row in table_data:
        cleaned_row = [
            (str(cell or "").replace("\n", " ").replace("|", "\\|").strip())
            for cell in row
        ]
        cleaned_rows.append(cleaned_row)

    # Ensure all rows have the same number of columns as the header
    num_cols = len(cleaned_rows[0])
    for row in cleaned_rows:
        while len(row) < num_cols:
            row.append("")
        if len(row) > num_cols:
            row = row[:num_cols]

    headers = cleaned_rows[0]
    separator = ["---"] * num_cols

    lines = [
        f"| {' | '.join(headers)} |",
        f"| {' | '.join(separator)} |",
    ]

    for row in cleaned_rows[1:]:
        lines.append(f"| {' | '.join(row)} |")

    return "\n".join(lines)


def extract_tables_from_page(
    page: fitz.Page,
    page_idx: int,
    source_name: str = "",
) -> list[ExtractedTable]:
    """Extract all structured tables from a single PDF page."""
    tables: list[ExtractedTable] = []
    try:
        table_finder = page.find_tables()
        if not table_finder or not table_finder.tables:
            return []

        for i, tbl in enumerate(table_finder.tables):
            extracted = tbl.extract()
            if not extracted or len(extracted) < 2:
                continue

            md = table_to_markdown(extracted)
            if not md.strip():
                continue

            table_id = hashlib.sha256(
                f"{source_name}:{page_idx}:{i}:{tbl.bbox}".encode()
            ).hexdigest()[:16]

            num_rows = len(extracted)
            num_cols = len(extracted[0])

            # Look for caption text immediately above or below table bbox
            caption = _find_table_caption(page, tbl.bbox)

            tables.append(
                ExtractedTable(
                    table_id=table_id,
                    page=page_idx,
                    bbox=tuple(tbl.bbox),
                    num_rows=num_rows,
                    num_cols=num_cols,
                    markdown=md,
                    caption=caption,
                )
            )
            logger.debug(
                "Extracted table on page %d: %d rows, %d cols | id=%s",
                page_idx + 1,
                num_rows,
                num_cols,
                table_id,
            )
    except Exception:
        logger.debug("Table extraction skipped on page %d", page_idx + 1, exc_info=True)

    return tables


def _find_table_caption(page: fitz.Page, bbox: tuple[float, float, float, float]) -> str:
    """Find caption text such as 'Table 1: Description' near the table bounding box."""
    try:
        x0, y0, x1, y1 = bbox
        # Search a strip 40pt above the table
        search_rect = fitz.Rect(x0 - 20, max(0, y0 - 40), x1 + 20, y0 + 5)
        text = page.get_text("text", clip=search_rect).strip()
        match = re.search(r"(?:Table\s+\d+[:.]?.*)", text, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    except Exception:
        pass
    return ""
