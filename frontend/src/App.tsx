import { useEffect, useRef, useState } from 'react'
import './App.css'
import { ChatInput } from './components/ChatInput'
import { ChatMessage } from './components/ChatMessage'
import { EmptyState } from './components/EmptyState'
import { MenuToggle, Sidebar } from './components/Sidebar'
import { Thinking } from './components/Thinking'
import { getMode } from './data/modes'
import { useChat } from './hooks/useChat'

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
    showTrace,
    setShowTrace,
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
  } = useChat()

  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [seedText, setSeedText] = useState('')
  const [seedKey, setSeedKey] = useState(0)
  const bottomRef = useRef<HTMLDivElement>(null)
  const modeMeta = getMode(mode)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading, liveSteps, activeChatId])

  const healthOk =
    Boolean(health) && !healthError && health?.status !== 'unhealthy'
  const healthLabel = healthError
    ? `API offline — ${healthError}`
    : health
      ? `API ${health.status}`
      : 'Checking API…'

  const headerTitle =
    activeChat?.title && activeChat.title !== 'New chat'
      ? activeChat.title
      : 'Research Assistant'

  return (
    <div className="app-shell">
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
        onModeChange={setMode}
        useMemory={useMemory}
        onUseMemoryChange={setUseMemory}
        showTrace={showTrace}
        onShowTraceChange={setShowTrace}
        healthOk={healthOk}
        healthLabel={healthLabel}
        onSelectChat={selectChat}
        onNewChat={newChat}
        onDeleteChat={deleteChat}
        onRenameChat={renameChat}
        onClearChat={clearChat}
        onClose={() => setSidebarOpen(false)}
      />

      <main className="main">
        <header className="main-header">
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem' }}>
            <MenuToggle onClick={() => setSidebarOpen(true)} />
            <div>
              <h2>{headerTitle}</h2>
              <p className="caption">
                Active mode: {modeMeta.label}
                {useMemory ? ` · Memory on (${messages.length} msgs)` : ' · Memory off'}
              </p>
            </div>
          </div>
        </header>

        <div className="chat-scroll">
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
              {messages.map((msg, index) => {
                const isLastAssistant =
                  msg.role === 'assistant' &&
                  index === messages.findLastIndex((m) => m.role === 'assistant')
                return (
                  <ChatMessage
                    key={msg.id}
                    message={msg}
                    showTrace={showTrace}
                    showFollowUps={isLastAssistant}
                    followUpsDisabled={isLoading}
                    onFollowUp={(q) => {
                      void sendMessage(q)
                    }}
                  />
                )
              })}
              {isLoading && <Thinking modeLabel={modeMeta.label} steps={liveSteps} />}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        <ChatInput
          disabled={isLoading}
          isLoading={isLoading}
          seedText={seedText}
          seedKey={seedKey}
          onSend={(q) => {
            void sendMessage(q)
          }}
          onStop={stopGeneration}
        />
      </main>
    </div>
  )
}
