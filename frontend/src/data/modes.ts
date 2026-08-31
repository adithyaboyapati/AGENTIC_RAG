import type { ModeMeta } from '../types'

export const MODES: ModeMeta[] = [
  {
    id: 'baseline',
    label: 'Baseline RAG',
    phase: 'Phase 1',
    description: 'Fixed pipeline: always retrieve → generate. No agentic decisions.',
    example: 'What is retrieval-augmented generation?',
  },
  {
    id: 'router',
    label: 'Query Router',
    phase: 'Phase 2',
    description: 'Routes each question to direct answer, retrieval, or web search.',
    example: 'Hello! What is corrective RAG?',
  },
  {
    id: 'crag',
    label: 'Corrective RAG',
    phase: 'Phase 3',
    description: 'Grades retrieved docs, rewrites on failure, falls back to web search.',
    example: 'What is Self-RAG?',
  },
  {
    id: 'decompose',
    label: 'Decomposition',
    phase: 'Phase 4',
    description: 'Splits complex questions into sub-queries; retrieves in parallel.',
    example: 'Compare naive RAG, advanced RAG, and modular RAG',
  },
  {
    id: 'multi_hop',
    label: 'Multi-Hop',
    phase: 'Phase 5',
    description: 'Chains sequential retrievals where each hop builds on the last.',
    example: 'What fallback does CRAG use when retrieval fails?',
  },
  {
    id: 'tools',
    label: 'Tool Agent',
    phase: 'Phase 6',
    description: 'Picks tools: PDFs, catalog DB, ops API, lab MCP, web search, or calculator.',
    example: 'Who owns retriever-prod and what did experiment 42 conclude about chunking?',
  },
  {
    id: 'agentic',
    label: 'Full Agentic',
    phase: 'Phase 7',
    description: 'Orchestrator: analyzes → picks strategy → grades → generates.',
    example: 'Compare RAG vs Agentic RAG; what is Self-RAG grading?',
  },
  {
    id: 'consensus',
    label: 'Consensus Debate',
    phase: 'Phase 8',
    description: 'Adversarial debate over retrieved chunks. Abstains instead of inventing examples or metrics.',
    example: 'Compare the performance trade-offs between Naive RAG and Modular RAG',
  },
]

export function getMode(id: string): ModeMeta {
  return MODES.find((m) => m.id === id) ?? MODES[MODES.length - 1]
}
