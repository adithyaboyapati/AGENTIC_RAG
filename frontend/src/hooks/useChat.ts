import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, checkHealth, checkReady, fetchModes, streamQuery } from '../api/client'
import { MODES } from '../data/modes'
import {
  createEmptyChat,
  loadChatStore,
  saveChatStore,
  titleFromMessage,
} from '../lib/chatStore'
import type {
  AgentMode,
  ChatMessage,
  Citation,
  HealthStatus,
  ModeMeta,
  QueryResponse,
  StoredChat,
} from '../types'

function newId(): string {
  return crypto.randomUUID()
}

function sortChats(chats: StoredChat[]): StoredChat[] {
  return chats.slice().sort((a, b) => b.updatedAt - a.updatedAt)
}

export function useChat() {
  const initial = useMemo(() => loadChatStore(), [])
  const [chats, setChats] = useState<StoredChat[]>(() => sortChats(initial.chats))
  const [activeChatId, setActiveChatId] = useState(initial.activeChatId)
  const [useMemory, setUseMemory] = useState(true)
  const [showTrace, setShowTrace] = useState(true)
  const [loadingChatId, setLoadingChatId] = useState<string | null>(null)
  const [liveSteps, setLiveSteps] = useState<string[]>([])
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [healthError, setHealthError] = useState<string | null>(null)
  const [availableModes, setAvailableModes] = useState<ModeMeta[]>(MODES)
  const abortRef = useRef<AbortController | null>(null)
  const activeChatIdRef = useRef(activeChatId)
  const isLoading = loadingChatId === activeChatId

  useEffect(() => {
    activeChatIdRef.current = activeChatId
  }, [activeChatId])

  const activeChat = chats.find((c) => c.id === activeChatId) ?? chats[0]
  const messages = activeChat?.messages ?? []
  const mode: AgentMode = activeChat?.mode ?? 'agentic'
  const sessionId = activeChat?.sessionId ?? ''

  // Persist whenever chats / active id change
  useEffect(() => {
    saveChatStore({ version: 1, activeChatId, chats })
  }, [chats, activeChatId])

  useEffect(() => {
    let cancelled = false
    const poll = () => {
      checkReady()
        .then((h) => {
          if (!cancelled) {
            setHealth(h)
            setHealthError(null)
          }
        })
        .catch(() =>
          checkHealth()
            .then((h) => {
              if (!cancelled) {
                setHealth(h)
                setHealthError(null)
              }
            })
            .catch((err: unknown) => {
              if (!cancelled) {
                setHealth(null)
                setHealthError(err instanceof Error ? err.message : 'API unreachable')
              }
            }),
        )
    }
    poll()
    const id = window.setInterval(poll, 30_000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    fetchModes()
      .then((labels) => {
        if (cancelled) return
        const fromApi: ModeMeta[] = Object.entries(labels).map(([id, label]) => {
          const fallback = MODES.find((m) => m.id === id)
          return {
            id: id as AgentMode,
            label,
            phase: fallback?.phase ?? '',
            description: fallback?.description ?? label,
            example: fallback?.example ?? '',
          }
        })
        if (fromApi.length) setAvailableModes(fromApi)
      })
      .catch(() => {
        /* keep static MODES */
      })
    return () => {
      cancelled = true
    }
  }, [])

  const updateActiveChat = useCallback((updater: (chat: StoredChat) => StoredChat) => {
    setChats((prev) => {
      const id = activeChatIdRef.current
      return sortChats(
        prev.map((c) => (c.id === id ? updater({ ...c, updatedAt: Date.now() }) : c)),
      )
    })
  }, [])

  const setMode = useCallback(
    (next: AgentMode) => {
      updateActiveChat((c) => ({ ...c, mode: next }))
    },
    [updateActiveChat],
  )

  const selectChat = useCallback((chatId: string) => {
    if (chatId === activeChatIdRef.current) return
    setActiveChatId(chatId)
  }, [])

  const newChat = useCallback(() => {
    // Reuse an existing empty "New chat" if one is already open
    setChats((prev) => {
      const empty = prev.find((c) => c.messages.length === 0 && c.title === 'New chat')
      if (empty) {
        setActiveChatId(empty.id)
        return sortChats(prev)
      }
      const chat = createEmptyChat(mode)
      setActiveChatId(chat.id)
      return sortChats([chat, ...prev])
    })
  }, [mode])

  const deleteChat = useCallback(
    (chatId: string) => {
      setChats((prev) => {
        const remaining = prev.filter((c) => c.id !== chatId)
        if (remaining.length === 0) {
          const fresh = createEmptyChat(mode)
          setActiveChatId(fresh.id)
          return [fresh]
        }
        if (chatId === activeChatIdRef.current) {
          setActiveChatId(remaining[0].id)
        }
        return remaining
      })
    },
    [mode],
  )

  const renameChat = useCallback((chatId: string, title: string) => {
    const next = title.trim() || 'New chat'
    setChats((prev) =>
      prev.map((c) => (c.id === chatId ? { ...c, title: next, updatedAt: Date.now() } : c)),
    )
  }, [])

  const clearChat = useCallback(() => {
    updateActiveChat((c) => ({
      ...c,
      messages: [],
      title: 'New chat',
      sessionId: crypto.randomUUID().replace(/-/g, ''),
    }))
    setLiveSteps([])
  }, [updateActiveChat])

  const sendMessage = useCallback(
    async (question: string) => {
      const trimmed = question.trim()
      const chatIdAtSend = activeChatIdRef.current
      if (!trimmed || loadingChatId === chatIdAtSend) return

      const current = chats.find((c) => c.id === chatIdAtSend)
      if (!current) return

      const sendSessionId = current.sessionId
      const sendMode = current.mode
      // Prior turns only. Server packs them compactly:
      // last 3 exchanges = Q + answer truncated to 500 chars; older = queries only.
      const priorHistory = useMemory
        ? current.messages
            .filter((m) => !m.error && (m.role === 'user' || m.role === 'assistant'))
            .slice(-26)
            .map((m) => ({ role: m.role, content: m.content }))
        : []

      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      const userMsg: ChatMessage = {
        id: newId(),
        role: 'user',
        content: trimmed,
      }

      setChats((prev) =>
        sortChats(
          prev.map((c) => {
            if (c.id !== chatIdAtSend) return c
            const isFirst = c.messages.length === 0
            return {
              ...c,
              title: isFirst ? titleFromMessage(trimmed) : c.title,
              messages: [...c.messages, userMsg],
              updatedAt: Date.now(),
            }
          }),
        ),
      )

      setLoadingChatId(chatIdAtSend)
      setLiveSteps([])

      const assistantId = newId()
      let answerText = ''
      let followUps: string[] = []
      let sources: string[] = []
      let citations: Citation[] = []
      let streamSteps: string[] = []
      let streamError: string | null = null

      const upsertAssistant = (content: string, done = false, meta?: Partial<QueryResponse>) => {
        setChats((prev) =>
          sortChats(
            prev.map((c) => {
              if (c.id !== chatIdAtSend) return c
              const others = c.messages.filter((m) => m.id !== assistantId)
              const assistantMsg: ChatMessage = {
                id: assistantId,
                role: 'assistant',
                content,
                followUps: done ? followUps : undefined,
                trace: done
                  ? {
                      question: trimmed,
                      mode: meta?.mode ?? sendMode,
                      answer: content,
                      sources,
                      citations,
                      route: meta?.route ?? null,
                      route_reason: meta?.route_reason ?? null,
                      steps: meta?.steps ?? streamSteps,
                      follow_ups: followUps,
                      latency_ms: meta?.latency_ms ?? 0,
                      session_id: meta?.session_id ?? null,
                    }
                  : null,
              }
              return {
                ...c,
                messages: [...others, assistantMsg],
                updatedAt: Date.now(),
              }
            }),
          ),
        )
      }

      try {
        await streamQuery(
          {
            question: trimmed,
            mode: sendMode,
            sessionId: useMemory ? sendSessionId : null,
            useMemory,
            chatHistory: priorHistory,
            signal: controller.signal,
          },
          {
            onStep: (step) => {
              streamSteps = [...streamSteps, step]
              if (activeChatIdRef.current === chatIdAtSend) {
                setLiveSteps(streamSteps)
              }
            },
            onToken: (token) => {
              answerText += token
              upsertAssistant(answerText)
            },
            onAnswer: (answer) => {
              answerText = answer
              upsertAssistant(answerText)
            },
            onFollowUps: (next) => {
              followUps = next
            },
            onSources: (nextSources, nextCitations) => {
              sources = nextSources
              citations = nextCitations
            },
            onDone: (meta) => {
              if (meta.steps?.length) streamSteps = meta.steps
              upsertAssistant(answerText, true, {
                mode: meta.mode ?? sendMode,
                route: meta.route ?? null,
                route_reason: meta.route_reason ?? null,
                steps: streamSteps,
                latency_ms: meta.latency_ms,
                session_id: meta.session_id,
              })
              setChats((prev) =>
                sortChats(
                  prev.map((c) => {
                    if (c.id !== chatIdAtSend) return c
                    if (!meta.session_id || meta.session_id === c.sessionId) return c
                    return { ...c, sessionId: meta.session_id, updatedAt: Date.now() }
                  }),
                ),
              )
            },
            onError: (message) => {
              streamError = message
            },
          },
        )

        if (streamError) {
          throw new ApiError(streamError, 500)
        }
        if (!answerText) {
          throw new ApiError('Empty response from agent', 500)
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        const message =
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : 'Something went wrong while processing your question.'
        setChats((prev) =>
          sortChats(
            prev.map((c) => {
              if (c.id !== chatIdAtSend) return c
              const others = c.messages.filter((m) => m.id !== assistantId)
              return {
                ...c,
                messages: [
                  ...others,
                  {
                    id: assistantId,
                    role: 'assistant',
                    content: message,
                    error: true,
                    trace: null,
                  },
                ],
                updatedAt: Date.now(),
              }
            }),
          ),
        )
      } finally {
        setLoadingChatId((id) => (id === chatIdAtSend ? null : id))
        if (activeChatIdRef.current === chatIdAtSend) {
          setLiveSteps([])
        }
        abortRef.current = null
      }
    },
    [chats, loadingChatId, useMemory],
  )

  const stopGeneration = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setLoadingChatId(null)
    setLiveSteps([])
  }, [])

  return {
    chats,
    activeChatId,
    activeChat,
    messages,
    mode,
    setMode,
    availableModes,
    useMemory,
    setUseMemory,
    showTrace,
    setShowTrace,
    sessionId,
    isLoading,
    liveSteps,
    health,
    healthError,
    selectChat,
    newChat,
    deleteChat,
    renameChat,
    clearChat,
    sendMessage,
    stopGeneration,
  }
}
