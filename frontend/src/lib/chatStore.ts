import type { AgentMode, ChatMessage, StoredChat, ChatStoreData } from '../types'

export const CHAT_STORE_KEY = 'agentic-rag-chats-v1'
const MAX_CHATS = 50

function newId(): string {
  return crypto.randomUUID().replace(/-/g, '')
}

export function createEmptyChat(mode: AgentMode = 'canonical'): StoredChat {
  const now = Date.now()
  return {
    id: newId(),
    title: 'New chat',
    sessionId: newId(),
    mode,
    messages: [],
    createdAt: now,
    updatedAt: now,
  }
}

export function titleFromMessage(content: string): string {
  const cleaned = content.replace(/\s+/g, ' ').trim()
  if (!cleaned) return 'New chat'
  return cleaned.length > 48 ? `${cleaned.slice(0, 48).trim()}…` : cleaned
}

export function slimMessages(messages: ChatMessage[]): ChatMessage[] {
  return messages.map((m) => {
    if (!m.trace && !m.pipeline) return m
    const trace = m.trace
      ? {
          question: m.trace.question,
          mode: m.trace.mode,
          answer: m.trace.answer,
          sources: m.trace.sources,
          citations: m.trace.citations,
          route: m.trace.route,
          route_reason: m.trace.route_reason,
          steps: m.trace.steps,
          follow_ups: m.trace.follow_ups,
          latency_ms: m.trace.latency_ms,
          session_id: m.trace.session_id,
          tenant_id: m.trace.tenant_id,
          consensus_score: m.trace.consensus_score,
          critique_summary: m.trace.critique_summary,
          error_code: m.trace.error_code,
        }
      : m.trace
    const pipeline = m.pipeline
      ? {
          type: 'pipeline' as const,
          stages: m.pipeline.stages.map((stage) => {
            if (stage.id !== 'context' || !stage.data) return stage
            const docs = Array.isArray(stage.data.context_docs)
              ? (stage.data.context_docs as Array<{ text?: string }>).slice(0, 8).map((doc) => ({
                  ...doc,
                  text: (doc.text || '').slice(0, 1200),
                }))
              : stage.data.context_docs
            return { ...stage, data: { ...stage.data, context_docs: docs } }
          }),
        }
      : m.pipeline
    return { ...m, streaming: undefined, trace, pipeline }
  })
}

export function loadChatStore(): ChatStoreData {
  try {
    const raw = localStorage.getItem(CHAT_STORE_KEY)
    if (!raw) {
      const chat = createEmptyChat()
      return { version: 1, activeChatId: chat.id, chats: [chat] }
    }
    const parsed = JSON.parse(raw) as ChatStoreData
    if (!parsed?.chats?.length || !parsed.activeChatId) {
      const chat = createEmptyChat()
      return { version: 1, activeChatId: chat.id, chats: [chat] }
    }
    if (!parsed.chats.some((c) => c.id === parsed.activeChatId)) {
      parsed.activeChatId = parsed.chats[0].id
    }
    return parsed
  } catch {
    const chat = createEmptyChat()
    return { version: 1, activeChatId: chat.id, chats: [chat] }
  }
}

export function saveChatStore(store: ChatStoreData): void {
  const payload: ChatStoreData = {
    version: 1,
    activeChatId: store.activeChatId,
    chats: store.chats
      .slice()
      .sort((a, b) => b.updatedAt - a.updatedAt)
      .slice(0, MAX_CHATS)
      .map((c) => ({
        ...c,
        messages: slimMessages(c.messages),
      })),
  }

  try {
    localStorage.setItem(CHAT_STORE_KEY, JSON.stringify(payload))
  } catch {
    const stripped: ChatStoreData = {
      ...payload,
      chats: payload.chats.map((c) => ({
        ...c,
        messages: c.messages.map(({ trace: _t, pipeline: _p, ...rest }) => rest),
      })),
    }
    try {
      localStorage.setItem(CHAT_STORE_KEY, JSON.stringify(stripped))
    } catch {
      console.warn('Unable to persist chat history — localStorage full')
    }
  }
}

export type ChatTimeGroup = 'Today' | 'Yesterday' | 'Previous 7 days' | 'Older'

export function groupChatsByTime(chats: StoredChat[]): { label: ChatTimeGroup; chats: StoredChat[] }[] {
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const startOfYesterday = startOfToday - 86_400_000
  const startOfWeek = startOfToday - 7 * 86_400_000

  const buckets: Record<ChatTimeGroup, StoredChat[]> = {
    Today: [],
    Yesterday: [],
    'Previous 7 days': [],
    Older: [],
  }

  for (const chat of chats) {
    if (chat.updatedAt >= startOfToday) buckets.Today.push(chat)
    else if (chat.updatedAt >= startOfYesterday) buckets.Yesterday.push(chat)
    else if (chat.updatedAt >= startOfWeek) buckets['Previous 7 days'].push(chat)
    else buckets.Older.push(chat)
  }

  return (Object.keys(buckets) as ChatTimeGroup[])
    .map((label) => ({ label, chats: buckets[label] }))
    .filter((g) => g.chats.length > 0)
}

export function formatRelativeTime(ts: number): string {
  const diff = Date.now() - ts
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`
  return new Date(ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

const DEBUG_KEY = 'agentic-rag-debug'
const DEBUG_DOCK_KEY = 'agentic-rag-debug-dock'

export type DebugDock = 'left' | 'right'

export function loadDebugMode(): boolean {
  try {
    return localStorage.getItem(DEBUG_KEY) === '1'
  } catch {
    return false
  }
}

export function saveDebugMode(on: boolean): void {
  try {
    localStorage.setItem(DEBUG_KEY, on ? '1' : '0')
  } catch {
    /* ignore */
  }
}

export function loadDebugDock(): DebugDock {
  try {
    return localStorage.getItem(DEBUG_DOCK_KEY) === 'left' ? 'left' : 'right'
  } catch {
    return 'right'
  }
}

export function saveDebugDock(dock: DebugDock): void {
  try {
    localStorage.setItem(DEBUG_DOCK_KEY, dock)
  } catch {
    /* ignore */
  }
}
