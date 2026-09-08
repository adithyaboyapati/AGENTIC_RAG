import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ApiError,
  checkHealth,
  checkReady,
  fetchModes,
  fetchRuntimeConfig,
  streamQuery,
  submitFeedback,
} from '../api/client'
import { isPublicMode, MODES } from '../data/modes'
import {
  applyGenerationStarted,
  applyLiveStep,
  emptyPipeline,
} from '../lib/pipeline'
import {
  createEmptyChat,
  loadChatStore,
  loadDebugMode,
  saveChatStore,
  saveDebugMode,
  titleFromMessage,
} from '../lib/chatStore'
import type {
  AgentMode,
  ChatMessage,
  Citation,
  FeedbackSubmission,
  HealthStatus,
  ModeMeta,
  PipelinePayload,
  QueryResponse,
  RuntimeConfig,
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
  const [debugMode, setDebugModeState] = useState(() => loadDebugMode())
  const [loadingChatId, setLoadingChatId] = useState<string | null>(null)
  const [liveSteps, setLiveSteps] = useState<string[]>([])
  const [livePipeline, setLivePipeline] = useState<PipelinePayload | null>(null)
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [healthError, setHealthError] = useState<string | null>(null)
  const [runtimeConfig, setRuntimeConfig] = useState<RuntimeConfig | null>(null)
  const [availableModes, setAvailableModes] = useState<ModeMeta[]>(MODES)
  const abortRef = useRef<AbortController | null>(null)
  const activeChatIdRef = useRef(activeChatId)
  const isLoading = loadingChatId === activeChatId

  useEffect(() => {
    activeChatIdRef.current = activeChatId
  }, [activeChatId])

  const activeChat = chats.find((c) => c.id === activeChatId) ?? chats[0]
  const messages = activeChat?.messages ?? []
  const mode: AgentMode = activeChat?.mode ?? 'canonical'
  const sessionId = activeChat?.sessionId ?? ''

  useEffect(() => {
    saveChatStore({ version: 1, activeChatId, chats })
  }, [chats, activeChatId])

  const setDebugMode = useCallback((on: boolean) => {
    setDebugModeState(on)
    saveDebugMode(on)
  }, [])

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
        const fromApi: ModeMeta[] = Object.entries(labels)
          .filter(([id]) => isPublicMode(id))
          .map(([id, label]) => {
            const fallback = MODES.find((m) => m.id === id)
            return {
              id: id as AgentMode,
              label,
              phase: fallback?.phase ?? 'Production',
              description: fallback?.description ?? label,
              example: fallback?.example ?? '',
            }
          })
        if (fromApi.length) setAvailableModes(fromApi)
      })
      .catch(() => {
        /* keep static MODES */
      })
    fetchRuntimeConfig()
      .then((cfg) => {
        if (!cancelled) {
          setRuntimeConfig(cfg)
          if (cfg.memory_enabled === false) setUseMemory(false)
        }
      })
      .catch(() => {
        /* optional */
      })
    return () => {
      cancelled = true
    }
  }, [])

  const updateActiveChat = useCallback((updater: (chat: StoredChat) => StoredChat) => {
    setChats((prev) => {
      const id = activeChatIdRef.current
      return sortChats(prev.map((c) => (c.id === id ? updater({ ...c, updatedAt: Date.now() }) : c)))
    })
  }, [])

  const setMode = useCallback(
    (next: AgentMode) => {
      updateActiveChat((c) => ({ ...c, mode: isPublicMode(next) ? next : 'canonical' }))
    },
    [updateActiveChat],
  )

  const selectChat = useCallback((chatId: string) => {
    if (chatId === activeChatIdRef.current) return
    setActiveChatId(chatId)
  }, [])

  const newChat = useCallback(() => {
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
    setLivePipeline(null)
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
      setLivePipeline(emptyPipeline(trimmed, sendMode))

      const assistantId = newId()
      let answerText = ''
      let followUps: string[] = []
      let sources: string[] = []
      let citations: Citation[] = []
      let streamSteps: string[] = []
      let streamError: string | null = null
      let pipeline: PipelinePayload | null = emptyPipeline(trimmed, sendMode)
      let sawTokens = false

      const upsertAssistant = (
        content: string,
        done = false,
        meta?: Partial<QueryResponse>,
        extras?: { pipeline?: PipelinePayload | null; streaming?: boolean },
      ) => {
        setChats((prev) =>
          sortChats(
            prev.map((c) => {
              if (c.id !== chatIdAtSend) return c
              const others = c.messages.filter((m) => m.id !== assistantId)
              const assistantMsg: ChatMessage = {
                id: assistantId,
                role: 'assistant',
                content,
                streaming: extras?.streaming ?? !done,
                followUps: done ? followUps : undefined,
                pipeline: extras?.pipeline ?? pipeline,
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
                      tenant_id: meta?.tenant_id,
                      consensus_score: meta?.consensus_score,
                      critique_summary: meta?.critique_summary,
                      error_code: meta?.error_code,
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
              pipeline = applyLiveStep(pipeline ?? emptyPipeline(trimmed, sendMode), step)
              if (activeChatIdRef.current === chatIdAtSend) {
                setLiveSteps(streamSteps)
                setLivePipeline(pipeline)
              }
            },
            onToken: (token) => {
              answerText += token
              if (!sawTokens) {
                sawTokens = true
                pipeline = applyGenerationStarted(pipeline ?? emptyPipeline(trimmed, sendMode))
                if (activeChatIdRef.current === chatIdAtSend) {
                  setLivePipeline(pipeline)
                }
              }
              upsertAssistant(answerText, false, undefined, { streaming: true })
            },
            onAnswer: (answer) => {
              answerText = answer
              upsertAssistant(answerText, false, undefined, { streaming: true })
            },
            onFollowUps: (next) => {
              followUps = next
            },
            onSources: (nextSources, nextCitations) => {
              sources = nextSources
              citations = nextCitations
            },
            onPipeline: (next) => {
              pipeline = next
              if (activeChatIdRef.current === chatIdAtSend) {
                setLivePipeline(next)
              }
            },
            onDone: (meta) => {
              if (meta.steps?.length) streamSteps = meta.steps
              upsertAssistant(
                answerText,
                true,
                {
                  mode: meta.mode ?? sendMode,
                  route: meta.route ?? null,
                  route_reason: meta.route_reason ?? null,
                  steps: streamSteps,
                  latency_ms: meta.latency_ms,
                  session_id: meta.session_id,
                  error_code: meta.error_code,
                },
                { pipeline, streaming: false },
              )
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
                    pipeline,
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

  const rateMessage = useCallback(
    async (messageId: string, submission: FeedbackSubmission) => {
      const chat = chats.find((c) => c.id === activeChatIdRef.current)
      if (!chat) return
      const assistant = chat.messages.find((m) => m.id === messageId)
      const user = [...chat.messages].reverse().find((m) => m.role === 'user' && m.id !== messageId)
      if (!assistant || assistant.role !== 'assistant' || assistant.error) return

      const patch = (status: 'pending' | 'saved' | 'failed') =>
        setChats((prev) =>
          prev.map((c) =>
            c.id !== chat.id
              ? c
              : {
                  ...c,
                  messages: c.messages.map((m) =>
                    m.id === messageId
                      ? {
                          ...m,
                          feedback: {
                            rating: submission.rating,
                            status,
                            comment: submission.comment,
                            categories: submission.categories,
                          },
                        }
                      : m,
                  ),
                },
          ),
        )

      patch('pending')
      try {
        await submitFeedback({
          rating: submission.rating,
          question: user?.content || assistant.trace?.question || '',
          answer: assistant.content,
          mode: assistant.trace?.mode || chat.mode,
          comment: submission.comment,
          categories: submission.categories,
          sessionId: chat.sessionId,
          messageId,
          route: assistant.trace?.route,
          sources: assistant.trace?.sources,
          citations: assistant.trace?.citations,
          latencyMs: assistant.trace?.latency_ms,
          consensusScore: assistant.trace?.consensus_score,
        })
        patch('saved')
      } catch {
        patch('failed')
      }
    },
    [chats],
  )

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
    debugMode,
    setDebugMode,
    sessionId,
    isLoading,
    liveSteps,
    livePipeline,
    health,
    healthError,
    runtimeConfig,
    selectChat,
    newChat,
    deleteChat,
    renameChat,
    clearChat,
    sendMessage,
    stopGeneration,
    rateMessage,
  }
}
