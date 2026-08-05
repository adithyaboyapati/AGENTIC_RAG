"""
Bootstrap — MUST be imported before any LangChain/LangGraph modules.

Ensures LangSmith tracing env vars are set before chain/graph modules load.
"""

from src.observability import init_langsmith_tracing

init_langsmith_tracing()
