import type {
  Citation,
  DocumentListResponse,
  FeedbackCategory,
  FeedbackRating,
  HealthStatus,
  IngestJob,
  PipelinePayload,
  QueryResponse,
  RuntimeConfig,
  UploadResponse,
} from '../types'
import type { AgentMode } from '../types'

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') || '/api'
const API_KEY = (import.meta.env.VITE_API_KEY as string | undefined) || ''

function headers(extra?: Record<string, string>): HeadersInit {
  const h: Record<string, string> = { ...extra }
  if (API_KEY) h['X-API-Key'] = API_KEY
  return h
}

function jsonHeaders(): HeadersInit {
  return headers({ 'Content-Type': 'application/json' })
}

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body?.detail === 'string') return body.detail
    if (Array.isArray(body?.detail)) {
      return body.detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join('; ')
    }
    return body?.message || res.statusText || 'Request failed'
  } catch {
    return res.statusText || 'Request failed'
  }
}

async function readJson<T>(res: Response): Promise<T> {
  if (!res.ok) throw new ApiError(await parseError(res), res.status)
  return res.json() as Promise<T>
}

export async function checkHealth(): Promise<HealthStatus> {
  const res = await fetch(`${API_BASE}/health`, { headers: jsonHeaders() })
  return readJson<HealthStatus>(res)
}

export async function checkReady(): Promise<HealthStatus> {
  const res = await fetch(`${API_BASE}/health/ready`, { headers: jsonHeaders() })
  const body = await res.json().catch(() => null)
  if (!body) throw new ApiError(await parseError(res), res.status)
  return body as HealthStatus
}

export async function fetchModes(): Promise<Record<string, string>> {
  const res = await fetch(`${API_BASE}/modes`, { headers: jsonHeaders() })
  return readJson<Record<string, string>>(res)
}

export async function fetchRuntimeConfig(): Promise<RuntimeConfig> {
  const res = await fetch(`${API_BASE}/config`, { headers: jsonHeaders() })
  return readJson<RuntimeConfig>(res)
}

export interface ChatTurnPayload {
  role: 'user' | 'assistant'
  content: string
}

export interface QueryParams {
  question: string
  mode: AgentMode
  sessionId?: string | null
  useMemory?: boolean
  chatHistory?: ChatTurnPayload[]
  tenantId?: string
  userRoles?: string[]
  signal?: AbortSignal
}

export async function queryAgent(params: QueryParams): Promise<QueryResponse> {
  const res = await fetch(`${API_BASE}/query`, {
    method: 'POST',
    headers: jsonHeaders(),
    signal: params.signal,
    body: JSON.stringify({
      question: params.question,
      mode: params.mode,
      session_id: params.sessionId || undefined,
      use_memory: params.useMemory ?? true,
      chat_history: params.chatHistory?.length ? params.chatHistory : undefined,
      tenant_id: params.tenantId || 'default',
      user_roles: params.userRoles || ['public'],
    }),
  })
  return readJson<QueryResponse>(res)
}

export interface StreamHandlers {
  onStep?: (step: string) => void
  onToken?: (token: string) => void
  onAnswer?: (answer: string) => void
  onFollowUps?: (followUps: string[]) => void
  onSources?: (sources: string[], citations: Citation[]) => void
  onPipeline?: (pipeline: PipelinePayload) => void
  onDone?: (meta: {
    latency_ms: number
    session_id: string | null
    mode?: string
    route?: string | null
    route_reason?: string | null
    steps?: string[]
    cached?: boolean
    error_code?: string | null
  }) => void
  onError?: (message: string) => void
}

export async function streamQuery(params: QueryParams, handlers: StreamHandlers): Promise<void> {
  const res = await fetch(`${API_BASE}/query/stream`, {
    method: 'POST',
    headers: jsonHeaders(),
    signal: params.signal,
    body: JSON.stringify({
      question: params.question,
      mode: params.mode,
      session_id: params.sessionId || undefined,
      use_memory: params.useMemory ?? true,
      chat_history: params.chatHistory?.length ? params.chatHistory : undefined,
      tenant_id: params.tenantId || 'default',
      user_roles: params.userRoles || ['public'],
    }),
  })

  if (!res.ok) throw new ApiError(await parseError(res), res.status)
  if (!res.body) throw new ApiError('No response body', 500)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let errorMessage: string | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() || ''

    for (const chunk of chunks) {
      const line = chunk.split('\n').find((l) => l.startsWith('data: '))
      if (!line) continue
      try {
        const event = JSON.parse(line.slice(6)) as {
          type: string
          content?: string | string[]
          message?: string
          citations?: Citation[]
          stages?: PipelinePayload['stages']
          latency_ms?: number
          session_id?: string | null
          mode?: string
          route?: string | null
          route_reason?: string | null
          steps?: string[]
          cached?: boolean
          error_code?: string | null
        }

        if (event.type === 'step' && typeof event.content === 'string') {
          handlers.onStep?.(event.content)
        } else if (event.type === 'token' && typeof event.content === 'string') {
          handlers.onToken?.(event.content)
        } else if (event.type === 'answer' && typeof event.content === 'string') {
          handlers.onAnswer?.(event.content)
        } else if (event.type === 'follow_ups' && Array.isArray(event.content)) {
          handlers.onFollowUps?.(event.content)
        } else if (event.type === 'sources') {
          const sources = Array.isArray(event.content) ? event.content : []
          handlers.onSources?.(sources, event.citations ?? [])
        } else if (event.type === 'pipeline' && Array.isArray(event.stages)) {
          handlers.onPipeline?.({ type: 'pipeline', stages: event.stages })
        } else if (event.type === 'done') {
          handlers.onDone?.({
            latency_ms: event.latency_ms ?? 0,
            session_id: event.session_id ?? null,
            mode: event.mode,
            route: event.route,
            route_reason: event.route_reason,
            steps: event.steps,
            cached: event.cached,
            error_code: event.error_code,
          })
        } else if (event.type === 'error') {
          errorMessage = event.message || 'Stream error'
          handlers.onError?.(errorMessage)
        }
      } catch {
        // ignore malformed SSE frames
      }
    }
  }

  if (errorMessage) {
    throw new ApiError(errorMessage, 500)
  }
}

export async function listDocuments(): Promise<DocumentListResponse> {
  const res = await fetch(`${API_BASE}/documents`, { headers: jsonHeaders() })
  return readJson<DocumentListResponse>(res)
}

export async function deleteDocument(source: string): Promise<{ source: string; deleted_chunks: number }> {
  const res = await fetch(`${API_BASE}/documents?source=${encodeURIComponent(source)}`, {
    method: 'DELETE',
    headers: jsonHeaders(),
  })
  return readJson(res)
}

export async function uploadDocuments(files: File[]): Promise<UploadResponse> {
  const body = new FormData()
  for (const file of files) body.append('files', file)
  const res = await fetch(`${API_BASE}/ingest/upload`, {
    method: 'POST',
    headers: headers(),
    body,
  })
  return readJson<UploadResponse>(res)
}

export async function submitIngestJob(
  sourcePaths: string[],
  tenantId = 'default',
  accessGroups = ['public'],
  webhookUrl?: string,
): Promise<IngestJob> {
  const res = await fetch(`${API_BASE}/ingest/jobs`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({
      source_paths: sourcePaths,
      tenant_id: tenantId,
      access_groups: accessGroups,
      webhook_url: webhookUrl,
    }),
  })
  return readJson<IngestJob>(res)
}

export async function getIngestJob(jobId: string): Promise<IngestJob> {
  const res = await fetch(`${API_BASE}/ingest/jobs/${jobId}`, { headers: jsonHeaders() })
  return readJson<IngestJob>(res)
}

export async function listIngestJobs(limit = 50): Promise<IngestJob[]> {
  const res = await fetch(`${API_BASE}/ingest/jobs?limit=${limit}`, { headers: jsonHeaders() })
  return readJson<IngestJob[]>(res)
}

export async function submitFeedback(payload: {
  rating: FeedbackRating
  question: string
  answer: string
  mode?: string
  comment?: string
  categories?: FeedbackCategory[]
  sessionId?: string | null
  messageId?: string
  route?: string | null
  sources?: string[]
  citations?: Citation[]
  latencyMs?: number
  consensusScore?: number | null
}): Promise<{ ok: boolean; id: string }> {
  const res = await fetch(`${API_BASE}/feedback`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({
      rating: payload.rating,
      question: payload.question,
      answer: payload.answer,
      mode: payload.mode || '',
      comment: payload.comment || '',
      categories: payload.categories || [],
      session_id: payload.sessionId || undefined,
      message_id: payload.messageId,
      route: payload.route,
      sources: payload.sources || [],
      citations: payload.citations || [],
      latency_ms: payload.latencyMs,
      consensus_score: payload.consensusScore,
      client: 'web',
    }),
  })
  return readJson(res)
}
