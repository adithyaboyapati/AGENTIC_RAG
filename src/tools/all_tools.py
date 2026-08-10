"""
LangChain tools for the Phase 6 tool-augmented agent.

Each tool is a @tool — the LLM calls them by name with parameters.

Failure / empty results use machine-readable prefixes so node gates can
quarantine them before they contaminate graph state:
  [TOOL_ERROR] …   — execution failed
  [TOOL_EMPTY] …   — succeeded but no content
  [CIRCUIT_OPEN] … — upstream circuit breaker open
"""

from __future__ import annotations

import ast
import operator as op

from langchain_core.tools import tool

from src.resilience.node_gate import (
    PREFIX_CIRCUIT_OPEN,
    PREFIX_TOOL_EMPTY,
    PREFIX_TOOL_ERROR,
)

# Arithmetic-only expression evaluator. Never use eval() here: the expression
# comes from the LLM, which is steerable by user input (prompt injection → RCE).
_ALLOWED_BINOPS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.FloorDiv: op.floordiv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
}
_ALLOWED_UNARYOPS = {ast.UAdd: op.pos, ast.USub: op.neg}

_MAX_POW_EXPONENT = 1000


def _safe_eval(node: ast.expr) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_POW_EXPONENT:
            raise ValueError(f"Exponent too large (max {_MAX_POW_EXPONENT})")
        return _ALLOWED_BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARYOPS:
        return _ALLOWED_UNARYOPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError(f"Unsupported expression element: {ast.dump(node)}")


def safe_calculate(expression: str) -> float:
    """Evaluate a pure-arithmetic expression without executing code."""
    if len(expression) > 200:
        raise ValueError("Expression too long")
    tree = ast.parse(expression, mode="eval")
    return _safe_eval(tree.body)


_ddg_search = None


def _get_ddg_search():
    """Lazy-init DuckDuckGoSearchRun."""
    global _ddg_search
    if _ddg_search is None:
        from langchain_community.tools import DuckDuckGoSearchRun

        _ddg_search = DuckDuckGoSearchRun()
    return _ddg_search


@tool
def retrieve_docs(query: str) -> str:
    """
    Search the knowledge base for documents about a topic.

    Use this to find information from indexed corpus documents.
    """
    from src.retrieval.retriever import format_docs, retrieve

    docs = retrieve(query)
    if not docs:
        return f"{PREFIX_TOOL_EMPTY} No documents found."
    return format_docs(docs)


@tool
def web_search(query: str) -> str:
    """
    Search the internet for recent or external information.

    Use this for current events, recent news, or information not in your knowledge base.
    """
    from src.resilience.circuit_breaker import CircuitOpenError, get_breaker

    breaker = get_breaker("web_search")
    try:
        result = breaker.call(_get_ddg_search().run, query)
    except CircuitOpenError:
        return f"{PREFIX_CIRCUIT_OPEN} Web search temporarily unavailable."
    except Exception as exc:
        return f"{PREFIX_TOOL_ERROR} Web search failed: {type(exc).__name__}"

    text = (result or "").strip()
    if not text:
        return f"{PREFIX_TOOL_EMPTY} Web search returned no results."
    return text


@tool
def calculator(expression: str) -> str:
    """
    Evaluate a mathematical expression.

    Examples:
    - "847 * 293" → computes multiplication
    - "2 ** 10" → computes powers
    - "(100 + 50) / 3" → respects order of operations
    """
    try:
        result = safe_calculate(expression)
        return str(result)
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as e:
        return f"{PREFIX_TOOL_ERROR} Error evaluating '{expression}': {e}"


# Tool registry for LangGraph
TOOLS = [retrieve_docs, web_search, calculator]
TOOL_MAP = {tool.name: tool for tool in TOOLS}
