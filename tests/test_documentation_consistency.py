"""Documentation consistency checks — detect stale references in CURRENT docs."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Deleted legacy graph modules — must not appear as current references
DELETED_GRAPH_FILES = [
    "src/graph/router_graph.py",
    "src/graph/crag_graph.py",
    "src/graph/decompose_graph.py",
    "src/graph/multi_hop_graph.py",
    "src/graph/tools_graph.py",
    "src/graph/agent_graph.py",
    "src/graph/consensus_graph.py",
    "src/rag/baseline.py",
]

# CURRENT docs — must not reference deleted files without historical context
CURRENT_DOC_PATHS = [
    PROJECT_ROOT / "README.md",
    PROJECT_ROOT / "docs/ARCHITECTURE.md",
    PROJECT_ROOT / "docs/LANGGRAPH.md",
    PROJECT_ROOT / "docs/API.md",
    PROJECT_ROOT / "docs/EVALUATION.md",
    PROJECT_ROOT / "docs/PRODUCTION.md",
    PROJECT_ROOT / "docs/QUICK_START.md",
    PROJECT_ROOT / "docs/LANGCHAIN_STACK.md",
    PROJECT_ROOT / "docs/GUARDRAILS.md",
    PROJECT_ROOT / "docs/CANARY_ROLLOUT.md",
    PROJECT_ROOT / "docs/PHASE8_CONTINUOUS_EVAL.md",
    PROJECT_ROOT / "docs/DOCUMENTATION_MAP.md",
    PROJECT_ROOT / "frontend/README.md",
]

# Historical docs — should contain a historical banner
HISTORICAL_DOC_PATHS = [
    PROJECT_ROOT / "AGENTIC_RAG_DEEP_DIVE.md",
    PROJECT_ROOT / "LANGGRAPH_DEEP_DIVE.md",
    PROJECT_ROOT / "INTERVIEW_WALKTHROUGH.md",
]

HISTORICAL_BANNER_PATTERNS = (
    "Historical",
    "HISTORICAL",
    "removed",
    "pre-canonical",
    "Phase 7",
)


def _repo_md_files() -> list[Path]:
    skip = {"node_modules", ".git", ".venv", "dist", "__pycache__"}
    files: list[Path] = []
    for path in PROJECT_ROOT.rglob("*.md"):
        if any(part in skip for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def test_inventory_finds_markdown_files():
    md_files = _repo_md_files()
    assert len(md_files) >= 20
    assert (PROJECT_ROOT / "README.md") in md_files
    assert (PROJECT_ROOT / "docs/ARCHITECTURE.md") in md_files


@pytest.mark.parametrize("doc_path", CURRENT_DOC_PATHS, ids=lambda p: p.name)
def test_current_docs_do_not_reference_deleted_graphs(doc_path: Path):
    if not doc_path.exists():
        pytest.skip(f"missing {doc_path}")
    text = doc_path.read_text(encoding="utf-8")
    for deleted in DELETED_GRAPH_FILES:
        assert deleted not in text, f"{doc_path.name} references deleted {deleted}"


@pytest.mark.parametrize("doc_path", HISTORICAL_DOC_PATHS, ids=lambda p: p.name)
def test_historical_docs_have_banner(doc_path: Path):
    if not doc_path.exists():
        pytest.skip(f"missing {doc_path}")
    head = doc_path.read_text(encoding="utf-8")[:800]
    assert any(p in head for p in HISTORICAL_BANNER_PATTERNS), (
        f"{doc_path.name} missing historical banner in first 800 chars"
    )


def test_canonical_architecture_doc_exists():
    arch = PROJECT_ROOT / "docs/ARCHITECTURE.md"
    assert arch.exists()
    text = arch.read_text(encoding="utf-8")
    assert "canonical_graph.py" in text
    assert "CanonicalAgentState" in text


def test_documentation_map_links():
    doc_map = PROJECT_ROOT / "docs/DOCUMENTATION_MAP.md"
    assert doc_map.exists()
    text = doc_map.read_text(encoding="utf-8")
    assert "ARCHITECTURE.md" in text
    assert "LANGGRAPH.md" in text


def test_deleted_files_absent_from_repo():
    for rel in DELETED_GRAPH_FILES:
        assert not (PROJECT_ROOT / rel).exists(), f"{rel} should be deleted"


def test_canonical_graph_exists():
    assert (PROJECT_ROOT / "src/graph/canonical_graph.py").exists()


def test_broken_local_markdown_links_in_current_docs():
    """Check relative .md links in CURRENT docs resolve."""
    link_re = re.compile(r"\]\(([^)#]+\.md)\)")
    broken: list[str] = []
    for doc_path in CURRENT_DOC_PATHS:
        if not doc_path.exists():
            continue
        text = doc_path.read_text(encoding="utf-8")
        for match in link_re.finditer(text):
            target = match.group(1)
            if target.startswith("http"):
                continue
            resolved = (doc_path.parent / target).resolve()
            if not resolved.exists():
                broken.append(f"{doc_path.name} → {target}")
    assert not broken, "Broken links: " + "; ".join(broken)


def test_legacy_mode_docs_mark_deprecated_in_readme():
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    assert "canonical" in readme.lower()
    assert "Deprecated" in readme or "deprecated" in readme
