import type { AgentMode, Citation, HealthStatus, QueryResponse } from '../types'

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') || '/api'
/** Optional escape hatch — prefer server-side API_KEY via Vite/nginx proxy. */
const API_KEY = (import.meta.env.VITE_API_KEY as string | undefined) || ''

function headers(): HeadersInit {
  const h: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (API_KEY) {
    h['X-API-Key'] = API_KEY
  }
  return h
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

export async function checkHealth(): Promise<HealthStatus> {
  const res = await fetch(`${API_BASE}/health`, { headers: headers() })
  if (!res.ok) throw new ApiError(await parseError(res), res.status)
  return res.json()
}

export async function checkReady(): Promise<HealthStatus> {
  const res = await fetch(`${API_BASE}/health/ready`, { headers: headers() })
  // readiness may return 503 with a useful body
  const body = await res.json().catch(() => null)
  if (!body) throw new ApiError(await parseError(res), res.status)
  return body as HealthStatus
}

export async function fetchModes(): Promise<Record<string, string>> {
  const res = await fetch(`${API_BASE}/modes`, { headers: headers() })
  if (!res.ok) throw new ApiError(await parseError(res), res.status)
  return res.json()
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
  signal?: AbortSignal
}

export async function queryAgent(params: QueryParams): Promise<QueryResponse> {
  const res = await fetch(`${API_BASE}/query`, {
    method: 'POST',
    headers: headers(),
    signal: params.signal,
    body: JSON.stringify({
      question: params.question,
      mode: params.mode,
      session_id: params.sessionId || undefined,
      use_memory: params.useMemory ?? true,
      chat_history: params.chatHistory?.length ? params.chatHistory : undefined,
    }),
  })

  if (!res.ok) throw new ApiError(await parseError(res), res.status)
  return res.json()
}

export interface StreamHandlers {
  onStep?: (step: string) => void
  onToken?: (token: string) => void
  onAnswer?: (answer: string) => void
  onFollowUps?: (followUps: string[]) => void
  onSources?: (sources: string[], citations: Citation[]) => void
  onDone?: (meta: {
    latency_ms: number
    session_id: string | null
    mode?: string
    route?: string | null
    route_reason?: string | null
    steps?: string[]
  }) => void
  onError?: (message: string) => void
}

/** Progressive SSE: steps as nodes finish, tokens as the final answer streams. */
export async function streamQuery(
  params: QueryParams,
  handlers: StreamHandlers,
): Promise<void> {
  const res = await fetch(`${API_BASE}/query/stream`, {
    method: 'POST',
    headers: headers(),
    signal: params.signal,
    body: JSON.stringify({
      question: params.question,
      mode: params.mode,
      session_id: params.sessionId || undefined,
      use_memory: params.useMemory ?? true,
      chat_history: params.chatHistory?.length ? params.chatHistory : undefined,
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
      const line = chunk
        .split('\n')
        .find((l) => l.startsWith('data: '))
      if (!line) continue
      try {
        const event = JSON.parse(line.slice(6)) as {
          type: string
          content?: string | string[]
          message?: string
          citations?: Citation[]
          latency_ms?: number
          session_id?: string | null
          mode?: string
          route?: string | null
          route_reason?: string | null
          steps?: string[]
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
        } else if (event.type === 'done') {
          handlers.onDone?.({
            latency_ms: event.latency_ms ?? 0,
            session_id: event.session_id ?? null,
            mode: event.mode,
            route: event.route,
            route_reason: event.route_reason,
            steps: event.steps,
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
