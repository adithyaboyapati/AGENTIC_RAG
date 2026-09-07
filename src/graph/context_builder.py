"""Token-aware context construction for the canonical graph."""

from __future__ import annotations

from dataclasses import dataclass

from src.config import settings
from src.contracts.models import Evidence
from src.retrieval.compression import compress_documents
from langchain_core.documents import Document


def count_tokens(text: str) -> int:
    if not text:
        return 0
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 4)


@dataclass(frozen=True)
class ContextBudget:
    model_context_tokens: int
    reserved_output_tokens: int
    reserved_prompt_tokens: int

    @property
    def available_context_tokens(self) -> int:
        return max(
            256,
            self.model_context_tokens
            - self.reserved_output_tokens
            - self.reserved_prompt_tokens,
        )


def default_context_budget() -> ContextBudget:
    return ContextBudget(
        model_context_tokens=getattr(settings, "model_context_tokens", 8192),
        reserved_output_tokens=settings.max_output_tokens,
        reserved_prompt_tokens=512,
    )


def compress_evidence(question: str, items: list[Evidence]) -> list[Evidence]:
    if not items or not settings.context_compression_enabled:
        return items
    docs = [
        Document(page_content=item.content, metadata=dict(item.result.metadata))
        for item in items
    ]
    compressed_docs = compress_documents(question, docs)
    compressed: list[Evidence] = []
    for item, doc in zip(items, compressed_docs, strict=False):
        compressed.append(item.model_copy(update={"content": doc.page_content}))
    return compressed


def fit_context_budget(
    items: list[Evidence],
    *,
    budget: ContextBudget | None = None,
) -> tuple[list[Evidence], list[Evidence]]:
    """Select evidence that fits token budget; mark excluded items explicitly."""
    budget = budget or default_context_budget()
    included: list[Evidence] = []
    excluded: list[Evidence] = []
    used = 0
    for item in items:
        tokens = count_tokens(item.content)
        if used + tokens <= budget.available_context_tokens:
            included.append(item)
            used += tokens
        else:
            excluded.append(
                item.model_copy(
                    update={
                        "shown_to_generation": False,
                        "included_in_context": False,
                        "excluded_reason": "token_budget",
                    }
                )
            )
    return included, excluded


def build_generation_context(
    question: str,
    items: list[Evidence],
    *,
    budget: ContextBudget | None = None,
) -> tuple[str, list[Evidence], list[Evidence]]:
    """Compress, budget, order, and number evidence for generation."""
    compressed = compress_evidence(question, items)
    included, excluded = fit_context_budget(compressed, budget=budget)

    parts: list[str] = []
    numbered: list[Evidence] = []
    for position, item in enumerate(included, 1):
        result = item.result
        header = f"[{position}] Source: {result.source}"
        if result.page is not None:
            header += f", page {result.page}"
        if result.section:
            header += f", section={result.section}"
        header += f" ({result.chunk_id})"
        parts.append(f"{header}\n{item.content}")
        numbered.append(
            item.model_copy(
                update={
                    "included_in_context": True,
                    "context_position": position,
                    "shown_to_generation": True,
                    "index": position,
                }
            )
        )
    context_text = "\n\n---\n\n".join(parts)
    return context_text, numbered, excluded
