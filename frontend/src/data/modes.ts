import type { AgentMode, ModeMeta } from '../types'

export const MODES: ModeMeta[] = [
  {
    id: 'canonical',
    label: 'Canonical Agentic RAG',
    phase: 'Production',
    description:
      'Unified canonical pipeline with automatic strategy selection, evidence provenance, and verification.',
    example: 'Compare RAG vs Agentic RAG; what is Self-RAG grading?',
  },
  {
    id: 'source_tools',
    label: 'Tool-selected sources',
    phase: 'Tools',
    description:
      'The LLM chooses among PDF, SQLite catalog, ops API, lab MCP, and calculator. Source-backed hits are CRAG-graded before answering.',
    example: 'Who owns retriever-prod and what did experiment 42 conclude about chunking?',
  },
]

const PUBLIC_MODE_IDS = new Set(MODES.map((m) => m.id))

/** Deprecated client mode aliases accepted by the API for backward compatibility. */
export const DEPRECATED_MODE_ALIASES = [
  'agentic',
  'baseline',
  'router',
  'crag',
  'decompose',
  'multi_hop',
  'tools',
  'consensus',
] as const

export function isPublicMode(id: string): id is AgentMode {
  return PUBLIC_MODE_IDS.has(id as AgentMode)
}

export function normalizeMode(id: string | undefined | null): AgentMode {
  if (id && isPublicMode(id)) return id
  return 'canonical'
}

export function getMode(id: string): ModeMeta {
  return MODES.find((m) => m.id === normalizeMode(id)) ?? MODES[0]
}
