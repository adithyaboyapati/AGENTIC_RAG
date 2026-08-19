export type AgentMode =
  | 'baseline'
  | 'router'
  | 'crag'
  | 'decompose'
  | 'multi_hop'
  | 'tools'
  | 'agentic'
  | 'consensus'

export interface ModeMeta {
  id: AgentMode
  label: string
  phase: string
  description: string
  example: string
}

export interface Citation {
  index: number
  chunk_id: string
  source: string
  page: number | null
  section?: string | null
  snippet: string
  score: number | null
}

export interface QueryResponse {
  question: string
  mode: string
  answer: string
  sources: string[]
  citations?: Citation[]
  route: string | null
  route_reason: string | null
  steps: string[]
  follow_ups: string[]
  latency_ms: number
  session_id: string | null
  tenant_id?: string | null
  consensus_score?: number | null
  critique_summary?: string | null
  error_code?: string | null
}

export interface IngestJob {
  job_id: string
  status: 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled'
  source_paths: string[]
  tenant_id: string
  access_groups: string[]
  progress_pct: number
  total_files: number
  processed_files: number
  total_chunks: number
  error?: string | null
  webhook_url?: string | null
  created_at: number
  completed_at?: number | null
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  trace?: QueryResponse | null
  followUps?: string[]
  error?: boolean
}

export interface StoredChat {
  id: string
  title: string
  sessionId: string
  mode: AgentMode
  messages: ChatMessage[]
  createdAt: number
  updatedAt: number
}

export interface ChatStoreData {
  version: 1
  activeChatId: string
  chats: StoredChat[]
}

export interface HealthStatus {
  status: string
  service?: string
}
