"""Restrict ingestion to an allowlisted directory tree."""

from __future__ import annotations

from pathlib import Path

from src.config import PROJECT_ROOT, settings

_DEFAULT_ROOT = PROJECT_ROOT / "data"


class UnsafeIngestPath(ValueError):
    """Raised when a requested ingest path is outside the allowlist."""


def ingest_allowed_roots() -> list[Path]:
    raw = (settings.ingest_allowed_roots or "").strip()
    if not raw:
        return [_DEFAULT_ROOT.resolve()]
    return [Path(part.strip()).expanduser().resolve() for part in raw.split(",") if part.strip()]


def resolve_ingest_path(path_str: str) -> Path:
    """Resolve ``path_str`` and require it to sit under an allowed root."""
    if not (path_str or "").strip():
        raise UnsafeIngestPath("ingest path is empty")

    candidate = Path(path_str).expanduser()
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise UnsafeIngestPath(f"ingest path could not be resolved: {path_str}") from exc

    roots = ingest_allowed_roots()
    if not any(_is_under(resolved, root) for root in roots):
        raise UnsafeIngestPath(
            f"ingest path is outside allowed roots ({', '.join(str(r) for r in roots)})"
        )
    return resolved


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
