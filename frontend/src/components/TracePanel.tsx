import type { QueryResponse } from '../types'

interface TracePanelProps {
  trace: QueryResponse
}

export function TracePanel({ trace }: TracePanelProps) {
  const hasRoute = Boolean(trace.route)
  const hasSteps = trace.steps.length > 0
  const citations = trace.citations ?? []
  const hasCitations = citations.length > 0
  const hasSources = trace.sources.length > 0

  if (!hasRoute && !hasSteps && !hasSources && !hasCitations) return null

  return (
    <details className="trace">
      <summary>
        <span>Agent trace</span>
        <span className="latency">{Math.round(trace.latency_ms)} ms</span>
      </summary>
      <div className="trace-body">
        {hasRoute && (
          <div>
            <span className="trace-chip">Route · {trace.route}</span>
            {trace.route_reason && <p className="trace-meta">{trace.route_reason}</p>}
          </div>
        )}

        {hasSteps && (
          <div>
            <p className="section-label" style={{ marginBottom: '0.4rem' }}>
              Steps
            </p>
            <ol className="trace-list">
              {trace.steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          </div>
        )}

        {hasCitations ? (
          <div>
            <p className="section-label" style={{ marginBottom: '0.4rem' }}>
              Citations
            </p>
            <ul className="trace-list">
              {citations.map((c) => (
                <li key={`${c.chunk_id}-${c.index}`}>
                  <code>
                    [{c.index}] {c.source}
                    {c.page != null ? ` · p${c.page}` : ''}
                    {c.section ? ` · ${c.section}` : ''}
                  </code>
                  {c.snippet && <p className="trace-meta">{c.snippet}</p>}
                </li>
              ))}
            </ul>
          </div>
        ) : (
          hasSources && (
            <div>
              <p className="section-label" style={{ marginBottom: '0.4rem' }}>
                Sources
              </p>
              <ul className="trace-list">
                {trace.sources.map((src) => (
                  <li key={src}>
                    <code>{src}</code>
                  </li>
                ))}
              </ul>
            </div>
          )
        )}
      </div>
    </details>
  )
}
