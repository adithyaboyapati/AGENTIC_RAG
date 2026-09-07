import { getMode } from '../../data/modes'
import type { AgentMode } from '../../types'

interface EmptyStateProps {
  mode: AgentMode
  onExample: (question: string) => void
}

export function EmptyState({ mode, onExample }: EmptyStateProps) {
  const meta = getMode(mode)

  return (
    <section className="empty-state">
      <p className="eyebrow">
        {meta.phase} · {meta.label}
      </p>
      <h2>How can I help you research?</h2>
      <p className="lede">
        Ask a grounded question over the indexed PDFs, paper catalog, ops API, and lab notes. The
        agent decides whether to retrieve, rewrite, decompose, or use tools — then cites what it
        used.
      </p>
      <div className="example-row">
        <button type="button" className="example-chip" onClick={() => onExample(meta.example)}>
          {meta.example}
        </button>
        <button type="button" className="example-chip" onClick={() => onExample('What is Self-RAG?')}>
          What is Self-RAG?
        </button>
        <button
          type="button"
          className="example-chip"
          onClick={() => onExample('Who owns retriever-prod and what did experiment 42 conclude?')}
        >
          Catalog + lab MCP
        </button>
      </div>
    </section>
  )
}
