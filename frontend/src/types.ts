export type AgentMode = 'canonical' | 'agentic'

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

export type PipelineStageId =
  | 'query'
  | 'processing'
  | 'retrieval'
  | 'chunks'
  | 'rerank'
  | 'context'
  | 'generation'
  | 'answer'

export type PipelineStageStatus = 'pending' | 'running' | 'complete' | 'skipped' | 'error'

export interface ClippedText {
  text: string
  truncated: boolean
  original_length?: number
}

export interface PipelineStage {
  id: PipelineStageId | string
  label: string
  status: PipelineStageStatus
  detail?: string
  data?: Record<string, unknown>
}

export interface PipelinePayload {
  type?: 'pipeline'
  stages: PipelineStage[]
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
  verification_status?: string | null
  confidence?: number | null
  response_status?: string | null
  pipeline_version?: string | null
  request_id?: string | null
}

export interface RuntimeConfig {
  openai_model: string
  embedding_model: string
  retrieval_top_k: number
  retrieval_candidate_k: number
  retrieval_search_type: string
  rerank_enabled: boolean
  rerank_provider: string
  rerank_model: string
  memory_enabled: boolean
  consensus_enabled: boolean
  multi_source_enabled: boolean
  feedback_enabled: boolean
  max_output_tokens: number
  chunking_strategy: string
  expand_to_parent: boolean
  context_compression_enabled: boolean
  ingest_max_upload_mb: number
}

export interface IndexedDocument {
  source: string
  filename: string
  chunk_count: number
  tenant_id: string
  page_count: number | null
}

export interface DocumentListResponse {
  documents: IndexedDocument[]
  total_chunks: number
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

export interface UploadResponse {
  files: Array<{
    filename: string
    saved_path: string
    job_id: string
    status: string
    error?: string | null
  }>
  job_ids: string[]
}

export type FeedbackRating = 'up' | 'down'

export type FeedbackCategory =
  | 'hallucination'
  | 'wrong_source'
  | 'incomplete'
  | 'off_topic'
  | 'too_slow'
  | 'formatting'
  | 'other'

export interface MessageFeedback {
  rating: FeedbackRating
  status: 'pending' | 'saved' | 'failed'
  comment?: string
  categories?: FeedbackCategory[]
}

export interface FeedbackSubmission {
  rating: FeedbackRating
  comment: string
  categories: FeedbackCategory[]
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  trace?: QueryResponse | null
  pipeline?: PipelinePayload | null
  followUps?: string[]
  error?: boolean
  streaming?: boolean
  feedback?: MessageFeedback | null
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

export interface HealthCheck {
  status: string
  detail?: string
}

export interface HealthStatus {
  status: string
  service?: string
  environment?: string
  checks?: Record<string, HealthCheck>
}
