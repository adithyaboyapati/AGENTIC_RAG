"""Canonical Agentic RAG architecture contracts (Phase 1).

These types define the target data contracts for the migration. They are
introduced alongside the existing implementation without changing runtime
behavior. Conversion helpers bridge LangChain ``Document`` and legacy
``src.schemas`` types at explicit boundaries.
"""

from src.contracts.conversions import (
    document_to_retrieval_result,
    evidence_to_citation,
    retrieval_result_to_evidence,
)
from src.contracts.models import (
    AgentResponse,
    Citation,
    Evidence,
    PlannedQuery,
    RetrievalPlan,
    RetrievalResult,
    ToolResult,
    ToolStatus,
    TraceEvent,
    VerificationResult,
)
from src.contracts.state import CanonicalAgentState
from src.contracts.validation import (
    ContractValidationError,
    validate_canonical_agent_state,
    validate_citation,
    validate_evidence,
    validate_retrieval_result,
    validate_state_transition,
    validate_tool_result,
    validate_verification_result,
)

__all__ = [
    "AgentResponse",
    "CanonicalAgentState",
    "Citation",
    "ContractValidationError",
    "Evidence",
    "PlannedQuery",
    "RetrievalPlan",
    "RetrievalResult",
    "ToolResult",
    "ToolStatus",
    "TraceEvent",
    "VerificationResult",
    "document_to_retrieval_result",
    "evidence_to_citation",
    "retrieval_result_to_evidence",
    "validate_canonical_agent_state",
    "validate_citation",
    "validate_evidence",
    "validate_retrieval_result",
    "validate_state_transition",
    "validate_tool_result",
    "validate_verification_result",
]
