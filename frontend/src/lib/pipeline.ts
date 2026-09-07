import type {
  PipelinePayload,
  PipelineStage,
  PipelineStageId,
  PipelineStageStatus,
} from '../types'

export const PIPELINE_STAGES: { id: PipelineStageId; label: string }[] = [
  { id: 'query', label: 'User Query' },
  { id: 'processing', label: 'Query Processing' },
  { id: 'retrieval', label: 'Retrieval' },
  { id: 'chunks', label: 'Retrieved Chunks' },
  { id: 'rerank', label: 'Reranking' },
  { id: 'context', label: 'Context Construction' },
  { id: 'generation', label: 'LLM Generation' },
  { id: 'answer', label: 'Final Answer' },
]

export function emptyPipeline(question: string, mode: string): PipelinePayload {
  return {
    type: 'pipeline',
    stages: PIPELINE_STAGES.map((stage, index) => ({
      id: stage.id,
      label: stage.label,
      status: index === 0 ? 'complete' : index === 1 ? 'running' : 'pending',
      data: index === 0 ? { question, mode } : undefined,
    })),
  }
}

export function classifyStep(step: string): PipelineStageId {
  const s = step.toLowerCase()
  if (
    s.includes('retriev') ||
    s.includes('chunk') ||
    s.includes('search') ||
    s.includes('bm25') ||
    s.includes('hybrid')
  ) {
    return 'retrieval'
  }
  if (
    s.includes('grade') ||
    s.includes('rerank') ||
    s.includes('rewrite') ||
    s.includes('correct')
  ) {
    return 'rerank'
  }
  if (
    s.includes('parent') ||
    s.includes('compress') ||
    s.includes('context') ||
    s.includes('expand')
  ) {
    return 'context'
  }
  if (
    s.includes('generat') ||
    s.includes('synthes') ||
    s.includes('propos') ||
    s.includes('challeng') ||
    s.includes('judge') ||
    s.includes('consensus') ||
    s.includes('answer')
  ) {
    return 'generation'
  }
  if (
    s.includes('route') ||
    s.includes('decompos') ||
    s.includes('sub-query') ||
    s.includes('hop') ||
    s.includes('tool') ||
    s.includes('strateg')
  ) {
    return 'processing'
  }
  return 'processing'
}

function upsertStage(
  stages: PipelineStage[],
  id: PipelineStageId,
  patch: Partial<PipelineStage>,
): PipelineStage[] {
  return stages.map((stage) =>
    stage.id === id
      ? {
          ...stage,
          ...patch,
          data: { ...(stage.data ?? {}), ...(patch.data ?? {}) },
        }
      : stage,
  )
}

function markPriorComplete(stages: PipelineStage[], activeId: PipelineStageId): PipelineStage[] {
  const order = PIPELINE_STAGES.map((s) => s.id)
  const activeIndex = order.indexOf(activeId)
  return stages.map((stage) => {
    const idx = order.indexOf(stage.id as PipelineStageId)
    if (idx >= 0 && idx < activeIndex && stage.status === 'pending') {
      return { ...stage, status: 'complete' as PipelineStageStatus }
    }
    if (idx >= 0 && idx < activeIndex && stage.status === 'running') {
      return { ...stage, status: 'complete' as PipelineStageStatus }
    }
    return stage
  })
}

export function applyLiveStep(pipeline: PipelinePayload, step: string): PipelinePayload {
  const id = classifyStep(step)
  let stages = markPriorComplete(pipeline.stages, id)
  const existing = stages.find((s) => s.id === id)
  const steps = [
    ...(((existing?.data?.steps as string[]) ?? []).filter((s) => s !== step)),
    step,
  ]
  stages = upsertStage(stages, id, {
    status: 'running',
    detail: step,
    data: { steps },
  })
  return { ...pipeline, stages }
}

export function applyGenerationStarted(pipeline: PipelinePayload): PipelinePayload {
  let stages = markPriorComplete(pipeline.stages, 'generation')
  stages = upsertStage(stages, 'generation', { status: 'running', detail: 'Streaming tokens' })
  return { ...pipeline, stages }
}

export function stageStatusLabel(status: PipelineStageStatus): string {
  if (status === 'running') return 'Running'
  if (status === 'complete') return 'Done'
  if (status === 'skipped') return 'Skipped'
  if (status === 'error') return 'Error'
  return 'Waiting'
}
