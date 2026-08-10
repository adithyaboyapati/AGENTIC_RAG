import type { AgentMode, ChatMessage, StoredChat, ChatStoreData } from '../types'

export const CHAT_STORE_KEY = 'agentic-rag-chats-v1'
const MAX_CHATS = 50

function newId(): string {
  return crypto.randomUUID().replace(/-/g, '')
}

export function createEmptyChat(mode: AgentMode = 'agentic'): StoredChat {
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

/** Drop bulky fields if needed to fit localStorage. */
export function slimMessages(messages: ChatMessage[]): ChatMessage[] {
  return messages.map((m) => {
    if (!m.trace) return m
    const { question, mode, answer, sources, route, route_reason, steps, follow_ups, latency_ms, session_id } =
      m.trace
    return {
      ...m,
      trace: {
        question,
        mode,
        answer,
        sources,
        route,
        route_reason,
        steps,
        follow_ups,
        latency_ms,
        session_id,
      },
    }
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
    // Ensure active chat exists
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
    // Quota exceeded — strip traces and retry
    const stripped: ChatStoreData = {
      ...payload,
      chats: payload.chats.map((c) => ({
        ...c,
        messages: c.messages.map(({ trace: _t, ...rest }) => rest),
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
