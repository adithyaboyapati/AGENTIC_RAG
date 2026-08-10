"""
PDF / text cleansing for the ingestion pipeline.

Removes:
  - running headers & footers (geometry + cross-page repetition)
  - lone page numbers
  - arXiv / corresponding-author boilerplate
  - irrelevant TOC sections (References, Acknowledgments, …)
  - hyphenation artifacts from PDF line wraps

Keeps figure captions (often informative in survey papers) unless configured otherwise.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field

import fitz  # PyMuPDF
from langchain_core.documents import Document

from src.config import settings

logger = logging.getLogger(__name__)

# Sections whose titles match these (case-insensitive) are dropped entirely.
_DEFAULT_DROP_SECTION_PATTERNS = (
    r"^references?\s*$",
    r"^bibliography\s*$",
    r"^acknowledg?e?ments?\s*$",
    r"^appendix(\s+[a-z0-9]+)?\s*$",
    r"^supplementary(\s+material)?\s*$",
    r"^about the authors?\s*$",
)

_PAGE_NUMBER_RE = re.compile(r"^\d{1,3}$")
_ARXIV_RE = re.compile(r"^arXiv:\d{4}\.\d{4,5}", re.I)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
_URL_ONLY_RE = re.compile(r"^https?://\S+$", re.I)
_HYPHEN_BREAK_RE = re.compile(r"(\w)-\n(\w)")
_MULTI_NL_RE = re.compile(r"\n{3,}")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
# Common academic running-header residue / footer boilerplate
_BOILERPLATE_LINE_RE = re.compile(
    r"(?i)^(?:"
    r"corresponding author\.?.*"
    r"|resources?\s+are\s+available\s+at\b.*"
    r"|©\s*\d{4}.*"
    r"|all rights reserved\.?"
    r"|licensed under\b.*"
    r")$"
)


@dataclass
class CleanseStats:
    pages_processed: int = 0
    blocks_dropped_margin: int = 0
    blocks_dropped_repeated: int = 0
    lines_dropped_noise: int = 0
    sections_dropped: int = 0
    hyphen_joins: int = 0

    def as_dict(self) -> dict:
        return {
            "pages_processed": self.pages_processed,
            "blocks_dropped_margin": self.blocks_dropped_margin,
            "blocks_dropped_repeated": self.blocks_dropped_repeated,
            "lines_dropped_noise": self.lines_dropped_noise,
            "sections_dropped": self.sections_dropped,
            "hyphen_joins": self.hyphen_joins,
        }


@dataclass
class CleanseConfig:
    drop_headers_footers: bool = True
    top_margin_ratio: float = 0.06
    bottom_margin_ratio: float = 0.06
    min_repeat_pages: int = 3
    drop_page_numbers: bool = True
    drop_boilerplate: bool = True
    drop_urls_only: bool = True
    fix_hyphenation: bool = True
    drop_irrelevant_sections: bool = True
    drop_section_patterns: tuple[str, ...] = field(
        default_factory=lambda: _DEFAULT_DROP_SECTION_PATTERNS
    )
    # When True, also strip dense TABLE header-only fragments
    drop_table_scaffold: bool = True


def cleanse_config_from_settings() -> CleanseConfig:
    raw = (settings.drop_section_titles or "").strip()
    if raw:
        patterns = tuple(
            rf"^{re.escape(p.strip())}\s*$" for p in raw.split(",") if p.strip()
        )
    else:
        patterns = _DEFAULT_DROP_SECTION_PATTERNS
    return CleanseConfig(
        drop_headers_footers=settings.cleanse_headers_footers,
        top_margin_ratio=settings.cleanse_top_margin_ratio,
        bottom_margin_ratio=settings.cleanse_bottom_margin_ratio,
        min_repeat_pages=settings.cleanse_min_repeat_pages,
        drop_page_numbers=settings.cleanse_drop_page_numbers,
        drop_boilerplate=settings.cleanse_drop_boilerplate,
        fix_hyphenation=settings.cleanse_fix_hyphenation,
        drop_irrelevant_sections=settings.cleanse_drop_irrelevant_sections,
        drop_section_patterns=patterns,
        drop_table_scaffold=settings.cleanse_drop_table_scaffold,
    )


def is_irrelevant_section_title(title: str, config: CleanseConfig | None = None) -> bool:
    cfg = config or cleanse_config_from_settings()
    if not cfg.drop_irrelevant_sections:
        return False
    t = (title or "").strip()
    for pat in cfg.drop_section_patterns:
        if re.search(pat, t, flags=re.I):
            return True
    return False


def _normalize_line_key(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip().lower()


def _is_noise_line(line: str, cfg: CleanseConfig) -> bool:
    text = line.strip()
    if not text:
        return True
    if cfg.drop_page_numbers and _PAGE_NUMBER_RE.match(text):
        return True
    if _ARXIV_RE.match(text):
        return True
    if cfg.drop_boilerplate and _BOILERPLATE_LINE_RE.match(text):
        return True
    if cfg.drop_boilerplate and text.lower().startswith("corresponding author"):
        return True
    if cfg.drop_boilerplate and _EMAIL_RE.search(text) and len(text) < 120:
        # Short email / affiliation contact lines
        if "corresponding" in text.lower() or text.count(" ") < 6:
            return True
    if cfg.drop_urls_only and _URL_ONLY_RE.match(text):
        return True
    if cfg.drop_table_scaffold and text in {
        "Method",
        "Retrieval Source",
        "Retrieval",
        "Data Type",
        "Retrieval Granularity",
        "Augmentation",
        "Stage",
        "process",
    }:
        return True
    return False


def find_repeated_margin_lines(
    doc: fitz.Document,
    cfg: CleanseConfig,
) -> set[str]:
    """Lines that appear in header/footer bands on many pages → running chrome."""
    counts: Counter[str] = Counter()
    for page in doc:
        h = page.rect.height
        top_cut = h * cfg.top_margin_ratio
        bot_cut = h * (1.0 - cfg.bottom_margin_ratio)
        seen: set[str] = set()
        for block in page.get_text("blocks"):
            if len(block) < 5:
                continue
            x0, y0, x1, y1, text = block[:5]
            text = (text or "").strip()
            if not text:
                continue
            in_margin = y1 <= top_cut + 2 or y0 >= bot_cut - 2
            if not in_margin:
                continue
            for line in text.splitlines():
                key = _normalize_line_key(line)
                if not key or len(key) > 100:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                counts[key] += 1
    return {k for k, v in counts.items() if v >= cfg.min_repeat_pages}


def cleanse_block_text(text: str, cfg: CleanseConfig, stats: CleanseStats | None = None) -> str:
    """Clean a single extracted text block / string."""
    if not text:
        return ""
    lines_out: list[str] = []
    for line in text.splitlines():
        if _is_noise_line(line, cfg):
            if stats:
                stats.lines_dropped_noise += 1
            continue
        lines_out.append(line.rstrip())
    joined = "\n".join(lines_out)
    if cfg.fix_hyphenation:
        def _join(m: re.Match[str]) -> str:
            if stats:
                stats.hyphen_joins += 1
            return m.group(1) + m.group(2)

        joined = _HYPHEN_BREAK_RE.sub(_join, joined)
        # Also join hyphen + space+newline variants: "con- tained" / "con-\n tained"
        joined = re.sub(r"(\w)-\s*\n\s*(\w)", _join, joined)
    joined = _MULTI_SPACE_RE.sub(" ", joined)
    joined = _MULTI_NL_RE.sub("\n\n", joined)
    return joined.strip()


def iter_clean_page_blocks(
    page: fitz.Page,
    *,
    cfg: CleanseConfig | None = None,
    repeated_keys: set[str] | None = None,
    stats: CleanseStats | None = None,
) -> list[tuple[float, float, float, float, str]]:
    """
    Geometry-aware block extraction with header/footer + noise filtering.

    Returns (x0, y0, x1, y1, cleaned_text) in reading order (two-column aware).
    """
    cfg = cfg or cleanse_config_from_settings()
    stats = stats or CleanseStats()
    stats.pages_processed += 1

    h = page.rect.height
    top_cut = h * cfg.top_margin_ratio
    bot_cut = h * (1.0 - cfg.bottom_margin_ratio)
    repeated_keys = repeated_keys or set()

    raw: list[tuple[float, float, float, float, str]] = []
    for block in page.get_text("blocks"):
        if len(block) < 5:
            continue
        x0, y0, x1, y1, text = block[:5]
        text = (text or "").strip()
        if not text:
            continue

        if cfg.drop_headers_footers:
            # Lone page-number blocks near the top/bottom
            if _PAGE_NUMBER_RE.match(text) and (y1 <= top_cut + 8 or y0 >= bot_cut - 8):
                stats.blocks_dropped_margin += 1
                continue
            # Entire block inside margin band and short → chrome
            if (y1 <= top_cut + 2 or y0 >= bot_cut - 2) and len(text) < 80:
                key = _normalize_line_key(text)
                if key in repeated_keys or _PAGE_NUMBER_RE.match(text) or _ARXIV_RE.match(text):
                    stats.blocks_dropped_margin += 1
                    continue

        # Drop blocks whose every line is a known repeated header/footer
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if lines and all(_normalize_line_key(ln) in repeated_keys for ln in lines):
            stats.blocks_dropped_repeated += 1
            continue

        cleaned = cleanse_block_text(text, cfg, stats)
        if not cleaned:
            continue
        raw.append((float(x0), float(y0), float(x1), float(y1), cleaned))

    mid = page.rect.width / 2
    left = sorted([b for b in raw if b[0] < mid - 20], key=lambda b: (b[1], b[0]))
    right = sorted([b for b in raw if b[0] >= mid - 20], key=lambda b: (b[1], b[0]))
    if not right or not left:
        return sorted(raw, key=lambda b: (b[1], b[0]))
    return left + right


def cleanse_pdf_text(
    pdf_path: str,
    *,
    cfg: CleanseConfig | None = None,
) -> tuple[list[str], CleanseStats]:
    """Return cleaned per-page text and stats for a PDF path."""
    cfg = cfg or cleanse_config_from_settings()
    stats = CleanseStats()
    doc = fitz.open(pdf_path)
    try:
        repeated = find_repeated_margin_lines(doc, cfg) if cfg.drop_headers_footers else set()
        pages: list[str] = []
        for page in doc:
            blocks = iter_clean_page_blocks(
                page, cfg=cfg, repeated_keys=repeated, stats=stats
            )
            pages.append("\n\n".join(b[4] for b in blocks).strip())
        return pages, stats
    finally:
        doc.close()


def cleanse_page_documents(
    pages: list[Document],
    *,
    cfg: CleanseConfig | None = None,
) -> list[Document]:
    """Clean LangChain page Documents produced by PyMuPDFLoader (fixed strategy)."""
    cfg = cfg or cleanse_config_from_settings()
    stats = CleanseStats()
    cleaned: list[Document] = []
    for doc in pages:
        text = cleanse_block_text(doc.page_content, cfg, stats)
        if not text:
            continue
        meta = dict(doc.metadata)
        cleaned.append(Document(page_content=text, metadata=meta))
    logger.info("Cleansed %d/%d page docs | %s", len(cleaned), len(pages), stats.as_dict())
    return cleaned


def filter_irrelevant_parents(
    parents: list[Document],
    *,
    cfg: CleanseConfig | None = None,
    stats: CleanseStats | None = None,
) -> list[Document]:
    """Drop parent sections whose titles are bibliography / appendix / etc."""
    cfg = cfg or cleanse_config_from_settings()
    stats = stats or CleanseStats()
    kept: list[Document] = []
    for parent in parents:
        title = str(
            parent.metadata.get("section_title")
            or parent.metadata.get("section_path")
            or ""
        )
        # Also drop if path ends with a dropped section
        leaf = title.split(">")[-1].strip() if title else ""
        if is_irrelevant_section_title(title, cfg) or is_irrelevant_section_title(leaf, cfg):
            stats.sections_dropped += 1
            logger.info("Dropping irrelevant section: %s", title)
            continue
        # Clean parent body again (hyphenation / residual noise)
        body = cleanse_block_text(parent.page_content, cfg, stats)
        if len(body) < 20:
            continue
        meta = dict(parent.metadata)
        kept.append(Document(page_content=body, metadata=meta))
    return kept
