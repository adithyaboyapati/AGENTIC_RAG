import { getMode } from '../data/modes'
import type { AgentMode } from '../types'

interface EmptyStateProps {
  mode: AgentMode
  onExample: (question: string) => void
}

export function EmptyState({ mode, onExample }: EmptyStateProps) {
  const meta = getMode(mode)

  return (
    <section className="empty-state">
      <p className="eyebrow">{meta.phase} · {meta.label}</p>
      <h2 className="brand-hero">Agentic RAG Lab</h2>
      <p className="lede">
        Ask grounded questions over the RAG survey corpus. The agent decides whether to
        retrieve, rewrite, decompose, or reach for tools — then shows you the trail.
      </p>
      <div className="example-row">
        <button type="button" className="example-chip" onClick={() => onExample(meta.example)}>
          Try: {meta.example}
        </button>
        <button
          type="button"
          className="example-chip"
          onClick={() => onExample('What is Self-RAG?')}
        >
          What is Self-RAG?
        </button>
        <button
          type="button"
          className="example-chip"
          onClick={() => onExample('Compare naive RAG and modular RAG')}
        >
          Compare RAG variants
        </button>
      </div>
    </section>
  )
}
