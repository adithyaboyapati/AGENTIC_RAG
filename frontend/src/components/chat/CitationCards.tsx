import { FileText } from 'lucide-react'
import type { Citation } from '../../types'

interface CitationCardsProps {
  citations: Citation[]
  sources?: string[]
  onOpen?: (citation: Citation) => void
}

function fileName(source: string): string {
  const cleaned = source.split(/[#?]/)[0]
  const parts = cleaned.split(/[/\\]/)
  return parts[parts.length - 1] || source
}

function scoreLabel(score: number | null | undefined): string | null {
  if (score == null || Number.isNaN(score)) return null
  const pct = score > 1 ? Math.round(score) : Math.round(score * 100)
  return `${Math.min(100, Math.max(0, pct))}%`
}

export function CitationCards({ citations, sources = [], onOpen }: CitationCardsProps) {
  if (!citations.length && !sources.length) return null

  if (!citations.length) {
    return (
      <div className="citations" aria-label="Sources">
        <p className="citations-label">Sources</p>
        <div className="citation-grid">
          {sources.map((src) => (
            <article key={src} className="citation-card">
              <FileText size={15} />
              <div>
                <strong>{fileName(src)}</strong>
                <p>{src}</p>
              </div>
            </article>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="citations" aria-label="Cited sources">
      <p className="citations-label">Sources</p>
      <div className="citation-grid">
        {citations.map((c) => {
          const score = scoreLabel(c.score)
          return (
            <button
              key={`${c.chunk_id}-${c.index}`}
              type="button"
              className="citation-card"
              onClick={() => onOpen?.(c)}
            >
              <span className="citation-index">{c.index}</span>
              <div className="citation-body">
                <strong>{fileName(c.source)}</strong>
                <span className="citation-meta">
                  {c.page != null ? `p.${c.page}` : 'document'}
                  {c.section ? ` · ${c.section}` : ''}
                  {score ? ` · ${score}` : ''}
                </span>
                {c.snippet && <p>{c.snippet}</p>}
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
