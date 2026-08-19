"""
Multimodal Figure and Diagram Extraction for PDFs.

Detects embedded figures, diagrams, and charts on PDF pages, extracts their
bounding boxes and surrounding captions, and generates visual context chunks.
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
class ExtractedFigure:
    """Represents a visual figure or diagram on a PDF page."""

    figure_id: str
    page: int  # 0-indexed
    bbox: tuple[float, float, float, float]
    caption: str
    description: str = ""

    def to_document(self, source: str = "", section_path: str = "") -> Document:
        """Convert extracted figure into a LangChain Document chunk."""
        meta = {
            "source": source,
            "page": self.page + 1,
            "chunk_type": "figure",
            "figure_id": self.figure_id,
            "bbox": list(self.bbox),
            "caption": self.caption,
        }
        if section_path:
            meta["section_path"] = section_path

        body = f"Visual Figure / Diagram on Page {self.page + 1}:\n"
        if self.caption:
            body += f"Caption: {self.caption}\n"
        if self.description:
            body += f"Description: {self.description}\n"

        return Document(page_content=body.strip(), metadata=meta)


def _find_figure_caption(page: fitz.Page, bbox: tuple[float, float, float, float]) -> str:
    """Search for 'Figure X: ...' or 'Fig. X: ...' below or above the figure."""
    try:
        x0, y0, x1, y1 = bbox
        # Search a strip below the image (standard caption placement)
        search_rect = fitz.Rect(max(0, x0 - 30), y1 - 5, min(page.rect.width, x1 + 30), min(page.rect.height, y1 + 60))
        text = page.get_text("text", clip=search_rect).strip()
        match = re.search(r"(?:Fig(?:ure)?\.?\s+\d+[:.]?.*)", text, re.IGNORECASE)
        if match:
            return match.group(0).strip()

        # Fallback: search the entire page for figure captions
        page_text = page.get_text("text")
        match_page = re.search(r"(?:Fig(?:ure)?\.?\s+\d+[:.][^\n]+)", page_text, re.IGNORECASE)
        if match_page:
            return match_page.group(0).strip()
    except Exception:
        pass
    return ""


def extract_figures_from_page(
    page: fitz.Page,
    page_idx: int,
    source_name: str = "",
) -> list[ExtractedFigure]:
    """Extract figures, drawings, and images from a PDF page."""
    figures: list[ExtractedFigure] = []
    try:
        image_list = page.get_images(full=True)
        if not image_list:
            return []

        for i, img_info in enumerate(image_list):
            xref = img_info[0]
            rects = page.get_image_rects(xref)
            bbox = tuple(rects[0]) if rects else (0.0, 0.0, float(page.rect.width), float(page.rect.height))

            # Skip tiny icons / logos (less than 50x50 pt)
            if rects:
                w = abs(rects[0].width)
                h = abs(rects[0].height)
                if w < 50 or h < 50:
                    continue

            caption = _find_figure_caption(page, bbox)
            figure_id = hashlib.sha256(
                f"{source_name}:{page_idx}:{i}:{xref}".encode()
            ).hexdigest()[:16]

            figures.append(
                ExtractedFigure(
                    figure_id=figure_id,
                    page=page_idx,
                    bbox=bbox,
                    caption=caption or f"Figure {i+1} on page {page_idx+1}",
                    description=f"Diagram/Figure embedded in document ({int(bbox[2]-bbox[0])}x{int(bbox[3]-bbox[1])}pt).",
                )
            )
            logger.debug(
                "Extracted figure on page %d | id=%s | caption=%r",
                page_idx + 1,
                figure_id,
                caption[:60],
            )
    except Exception:
        logger.debug("Figure extraction skipped on page %d", page_idx + 1, exc_info=True)

    return figures
