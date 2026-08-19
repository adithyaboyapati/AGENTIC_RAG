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
  const hasConsensus = trace.consensus_score != null

  if (!hasRoute && !hasSteps && !hasSources && !hasCitations && !hasConsensus) return null

  return (
    <details className="trace">
      <summary>
        <span>Agent trace</span>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          {trace.tenant_id && trace.tenant_id !== 'default' && (
            <span className="trace-chip" style={{ fontSize: '0.75rem' }}>Tenant: {trace.tenant_id}</span>
          )}
          {hasConsensus && (
            <span
              className="trace-chip"
              style={{
                fontSize: '0.75rem',
                backgroundColor: 'rgba(34, 197, 94, 0.15)',
                color: '#22c55e',
                border: '1px solid rgba(34, 197, 94, 0.3)',
              }}
            >
              Consensus: {Math.round((trace.consensus_score || 0) * 100)}%
            </span>
          )}
          <span className="latency">{Math.round(trace.latency_ms)} ms</span>
        </div>
      </summary>
      <div className="trace-body">
        {hasConsensus && trace.critique_summary && (
          <div>
            <span className="trace-chip">Adversarial Critique Summary</span>
            <p className="trace-meta" style={{ marginTop: '0.2rem' }}>{trace.critique_summary}</p>
          </div>
        )}

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
