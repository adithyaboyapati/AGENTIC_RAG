import { useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, PanelLeft, PanelRight, X } from 'lucide-react'
import { PIPELINE_STAGES, stageStatusLabel } from '../../lib/pipeline'
import type { DebugDock } from '../../lib/chatStore'
import type { PipelinePayload, PipelineStage, PipelineStageStatus } from '../../types'

interface PipelinePanelProps {
  pipeline: PipelinePayload | null
  liveSteps: string[]
  isLoading: boolean
  dock: DebugDock
  onDockChange: (dock: DebugDock) => void
  onClose: () => void
}

function pretty(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function StageCard({ stage, defaultOpen }: { stage: PipelineStage; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const hasData = stage.data && Object.keys(stage.data).length > 0

  useEffect(() => {
    if (stage.status === 'running') setOpen(true)
  }, [stage.status])

  return (
    <article className={`stage-card status-${stage.status}`}>
      <button type="button" className="stage-head" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span className={`stage-dot status-${stage.status}`} />
        <span className="stage-label">{stage.label}</span>
        <span className="stage-status">{stageStatusLabel(stage.status)}</span>
      </button>
      {open && (
        <div className="stage-body">
          {stage.detail && <p className="stage-detail">{stage.detail}</p>}
          {hasData ? (
            <pre className="stage-json">{pretty(stage.data)}</pre>
          ) : (
            <p className="muted">No payload for this stage yet.</p>
          )}
        </div>
      )}
    </article>
  )
}

function mergeOrder(pipeline: PipelinePayload | null): PipelineStage[] {
  const byId = new Map((pipeline?.stages ?? []).map((s) => [s.id, s]))
  return PIPELINE_STAGES.map((meta) => {
    const existing = byId.get(meta.id)
    if (existing) return existing
    return {
      id: meta.id,
      label: meta.label,
      status: 'pending' as PipelineStageStatus,
    }
  })
}

export function PipelinePanel({
  pipeline,
  liveSteps,
  isLoading,
  dock,
  onDockChange,
  onClose,
}: PipelinePanelProps) {
  const stages = mergeOrder(pipeline)
  const active = stages.find((s) => s.status === 'running')

  return (
    <aside className={`debug-panel dock-${dock}`} aria-label="RAG pipeline">
      <header className="debug-header">
        <div>
          <p className="eyebrow">Developer mode</p>
          <h2>RAG pipeline</h2>
        </div>
        <div className="debug-actions">
          <span className={`status-pill ${isLoading ? 'warn' : ''}`}>
            {isLoading ? active?.label || 'Running' : 'Inspect'}
          </span>
          <button
            type="button"
            className={`icon-action ${dock === 'left' ? 'active' : ''}`}
            aria-label="Dock pipeline to the left"
            title="Dock left"
            onClick={() => onDockChange('left')}
          >
            <PanelLeft size={15} />
          </button>
          <button
            type="button"
            className={`icon-action ${dock === 'right' ? 'active' : ''}`}
            aria-label="Dock pipeline to the right"
            title="Dock right"
            onClick={() => onDockChange('right')}
          >
            <PanelRight size={15} />
          </button>
          <button
            type="button"
            className="ghost-btn debug-close"
            aria-label="Close debug panel"
            title="Close debug panel"
            onClick={onClose}
          >
            <X size={15} />
            Close
          </button>
        </div>
      </header>
      <p className="debug-flow">
        Query → Processing → Tools → Retrieval → Chunks → Rerank → Context → Generation → Answer
      </p>
      <div className="stage-list">
        {stages.map((stage, index) => (
          <StageCard
            key={stage.id}
            stage={stage}
            defaultOpen={stage.status === 'running' || (index === 0 && !isLoading)}
          />
        ))}
      </div>
      {liveSteps.length > 0 && isLoading && (
        <div className="live-steps">
          <p className="section-label">Live steps</p>
          <ol>
            {liveSteps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </div>
      )}
    </aside>
  )
}
