"""LangChain LCEL chains."""

from src.chains.generation import direct_chain, rag_chain, synthesis_chain, web_search_chain

__all__ = ["rag_chain", "direct_chain", "web_search_chain", "synthesis_chain"]
