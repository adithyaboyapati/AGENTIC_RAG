import { useEffect, useRef, useState } from 'react'
import './App.css'
import { ChatInput } from './components/chat/ChatInput'
import { ChatMessage } from './components/chat/ChatMessage'
import { EmptyState } from './components/chat/EmptyState'
import { Thinking } from './components/chat/Thinking'
import { PipelinePanel } from './components/debug/PipelinePanel'
import { DocumentsPanel } from './components/documents/DocumentsPanel'
import { Header } from './components/Header'
import { SettingsPanel } from './components/settings/SettingsPanel'
import { Sidebar } from './components/sidebar/Sidebar'
import { getMode } from './data/modes'
import { useChat } from './hooks/useChat'
import { useDocuments } from './hooks/useDocuments'
import { loadDebugDock, saveDebugDock, type DebugDock } from './lib/chatStore'
import type { Citation } from './types'

export default function App() {
  const {
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
  } = useChat()

  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [docsOpen, setDocsOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [debugDock, setDebugDockState] = useState<DebugDock>(() => loadDebugDock())
  const [seedText, setSeedText] = useState('')
  const [seedKey, setSeedKey] = useState(0)
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickRef = useRef(true)
  const modeMeta = getMode(mode)
  const docs = useDocuments(docsOpen)

  function setDebugDock(dock: DebugDock) {
    setDebugDockState(dock)
    saveDebugDock(dock)
  }

  useEffect(() => {
    if (!debugMode) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setDebugMode(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [debugMode, setDebugMode])

  useEffect(() => {
    if (!stickRef.current) return
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading, liveSteps, activeChatId])

  const healthOk = Boolean(health) && !healthError && health?.status !== 'unhealthy'
  const healthLabel = healthError
    ? `API offline — ${healthError}`
    : health
      ? `API ${health.status}`
      : 'Checking API…'

  const headerTitle =
    activeChat?.title && activeChat.title !== 'New chat' ? activeChat.title : 'Research assistant'

  const lastAssistantIndex = messages.findLastIndex((m) => m.role === 'assistant')
  const showThinking = isLoading && !messages.some((m) => m.role === 'assistant' && m.streaming)
  const inspectPipeline =
    livePipeline ??
    [...messages].reverse().find((m) => m.role === 'assistant' && m.pipeline)?.pipeline ??
    null

  return (
    <div className={`app-shell ${debugMode ? `debug-open debug-${debugDock}` : ''}`}>
      <div
        className={`sidebar-backdrop ${sidebarOpen ? 'show' : ''}`}
        onClick={() => setSidebarOpen(false)}
        aria-hidden
      />

      <Sidebar
        open={sidebarOpen}
        chats={chats}
        activeChatId={activeChatId}
        mode={mode}
        modes={availableModes}
        healthOk={healthOk}
        healthLabel={healthLabel}
        onSelectChat={selectChat}
        onNewChat={newChat}
        onDeleteChat={deleteChat}
        onRenameChat={renameChat}
        onOpenDocuments={() => {
          setDocsOpen(true)
          setSidebarOpen(false)
        }}
        onOpenSettings={() => {
          setSettingsOpen(true)
          setSidebarOpen(false)
        }}
        onClose={() => setSidebarOpen(false)}
      />

      <main className="main">
        <Header
          title={headerTitle}
          subtitle={`${modeMeta.label}${useMemory ? ` · Memory on` : ' · Memory off'}`}
          mode={mode}
          modes={availableModes}
          onModeChange={setMode}
          debugMode={debugMode}
          onDebugToggle={() => setDebugMode(!debugMode)}
          onOpenSidebar={() => setSidebarOpen(true)}
        />

        {healthError && (
          <div className="error-banner" role="alert">
            Cannot reach the API. Start the backend on port 8000, then retry.
            <span>{healthError}</span>
          </div>
        )}

        <div
          className="chat-scroll"
          ref={scrollRef}
          onScroll={(e) => {
            const el = e.currentTarget
            stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 96
          }}
        >
          {messages.length === 0 && !isLoading ? (
            <EmptyState
              mode={mode}
              onExample={(q) => {
                setSeedText(q)
                setSeedKey((k) => k + 1)
              }}
            />
          ) : (
            <div className="message-list">
              {messages.map((msg, index) => (
                <ChatMessage
                  key={msg.id}
                  message={msg}
                  showFollowUps={msg.role === 'assistant' && index === lastAssistantIndex}
                  followUpsDisabled={isLoading}
                  feedbackEnabled={runtimeConfig?.feedback_enabled !== false}
                  onFollowUp={(q) => {
                    void sendMessage(q)
                  }}
                  onFeedback={(submission) => {
                    void rateMessage(msg.id, submission)
                  }}
                  onOpenCitation={setSelectedCitation}
                />
              ))}
              {showThinking && <Thinking modeLabel={modeMeta.label} steps={liveSteps} />}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        <ChatInput
          disabled={isLoading}
          isLoading={isLoading}
          uploading={docs.uploading}
          seedText={seedText}
          seedKey={seedKey}
          onSend={(q) => {
            void sendMessage(q)
          }}
          onStop={stopGeneration}
          onAttach={(files) => {
            setDocsOpen(true)
            void docs.upload(files)
          }}
        />
      </main>

      {debugMode && (
        <PipelinePanel
          pipeline={inspectPipeline}
          liveSteps={liveSteps}
          isLoading={isLoading}
          dock={debugDock}
          onDockChange={setDebugDock}
          onClose={() => setDebugMode(false)}
        />
      )}

      <DocumentsPanel
        open={docsOpen}
        documents={docs.documents}
        totalChunks={docs.totalChunks}
        jobs={docs.jobs}
        loading={docs.loading}
        uploading={docs.uploading}
        error={docs.error}
        notice={docs.notice}
        onClose={() => setDocsOpen(false)}
        onUpload={(files) => void docs.upload(files)}
        onDelete={(source) => void docs.remove(source)}
      />

      <SettingsPanel
        open={settingsOpen}
        mode={mode}
        modes={availableModes}
        onModeChange={setMode}
        useMemory={useMemory}
        onUseMemoryChange={setUseMemory}
        debugMode={debugMode}
        onDebugModeChange={setDebugMode}
        memoryLockedOff={runtimeConfig?.memory_enabled === false}
        runtimeConfig={runtimeConfig}
        onClearChat={() => {
          clearChat()
          setSettingsOpen(false)
        }}
        onClose={() => setSettingsOpen(false)}
      />

      {selectedCitation && (
        <div className="drawer-backdrop" onClick={() => setSelectedCitation(null)}>
          <aside className="drawer citation-drawer" onClick={(e) => e.stopPropagation()}>
            <header className="drawer-header">
              <div>
                <h2>Source {selectedCitation.index}</h2>
                <p>
                  {selectedCitation.source}
                  {selectedCitation.page != null ? ` · page ${selectedCitation.page}` : ''}
                </p>
              </div>
              <button type="button" className="ghost-btn" onClick={() => setSelectedCitation(null)}>
                Close
              </button>
            </header>
            {selectedCitation.section && <p className="muted">{selectedCitation.section}</p>}
            <pre className="citation-snippet">{selectedCitation.snippet || 'No snippet returned.'}</pre>
            {selectedCitation.score != null && (
              <p className="muted">Score {selectedCitation.score.toFixed(3)}</p>
            )}
          </aside>
        </div>
      )}
    </div>
  )
}
