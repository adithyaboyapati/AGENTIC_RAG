"""LangChain LCEL chains — composable Runnable pipelines."""

from langchain_core.output_parsers import StrOutputParser

from src.llm import get_llm
from src.prompts import DIRECT_PROMPT, RAG_PROMPT, SYNTHESIS_PROMPT, WEB_SEARCH_PROMPT

str_parser = StrOutputParser()

# Phase 1 & retrieve path: context + question → answer
rag_chain = RAG_PROMPT | get_llm() | str_parser

# Router direct path: question → answer (no retrieval)
direct_chain = DIRECT_PROMPT | get_llm() | str_parser

# Router web path: web results + question → answer
web_search_chain = WEB_SEARCH_PROMPT | get_llm() | str_parser

# Phase 4: synthesize sub-query results into one answer
synthesis_chain = SYNTHESIS_PROMPT | get_llm() | str_parser
