"""LangChain tools for agent use."""

from langchain_core.tools import tool

_ddg_search = None


def _get_ddg_search():
    """Lazy-init LangChain DuckDuckGoSearchRun (only needed for web_search route)."""
    global _ddg_search
    if _ddg_search is None:
        from langchain_community.tools import DuckDuckGoSearchRun

        _ddg_search = DuckDuckGoSearchRun()
    return _ddg_search


# Deprecated: use src.tools.all_tools.web_search instead
# This is kept for backward compatibility with router_graph.py imports
@tool
def web_search(query: str) -> str:
    """Search the web for recent or external information not in the knowledge base."""
    return _get_ddg_search().run(query)
