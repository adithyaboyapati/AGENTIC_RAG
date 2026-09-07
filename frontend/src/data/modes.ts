import type { ModeMeta } from '../types'

export const MODES: ModeMeta[] = [
  {
    id: 'canonical',
    label: 'Agentic RAG',
    phase: 'Production',
    description:
      'Unified canonical pipeline with automatic strategy selection, evidence provenance, and verification.',
    example: 'Compare RAG vs Agentic RAG; what is Self-RAG grading?',
  },
]

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

export function getMode(id: string): ModeMeta {
  if (id === 'agentic') {
    return MODES[0]
  }
  return MODES.find((m) => m.id === id) ?? MODES[0]
}
