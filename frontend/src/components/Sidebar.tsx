import { Eraser, Menu, Plus, Settings2 } from 'lucide-react'
import { useState } from 'react'
import { MODES, getMode } from '../data/modes'
import type { AgentMode, ModeMeta, StoredChat } from '../types'
import { ChatHistory } from './ChatHistory'

interface SidebarProps {
  open: boolean
  chats: StoredChat[]
  activeChatId: string
  mode: AgentMode
  modes?: ModeMeta[]
  onModeChange: (mode: AgentMode) => void
  useMemory: boolean
  onUseMemoryChange: (value: boolean) => void
  showTrace: boolean
  onShowTraceChange: (value: boolean) => void
  healthOk: boolean
  healthLabel: string
  onSelectChat: (chatId: string) => void
  onNewChat: () => void
  onDeleteChat: (chatId: string) => void
  onRenameChat: (chatId: string, title: string) => void
  onClearChat: () => void
  onClose: () => void
}

export function Sidebar({
  open,
  chats,
  activeChatId,
  mode,
  modes = MODES,
  onModeChange,
  useMemory,
  onUseMemoryChange,
  showTrace,
  onShowTraceChange,
  healthOk,
  healthLabel,
  onSelectChat,
  onNewChat,
  onDeleteChat,
  onRenameChat,
  onClearChat,
  onClose,
}: SidebarProps) {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const active = modes.find((m) => m.id === mode) ?? getMode(mode)

  return (
    <aside className={`sidebar ${open ? 'open' : ''}`} aria-label="Controls">
      <div className="brand">
        <div className="brand-mark" aria-hidden>
          <svg viewBox="0 0 24 24" fill="none">
            <path
              d="M4 18V6l8 6 8-6v12"
              stroke="#2BB5A0"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <circle cx="12" cy="12" r="2" fill="#F0A35E" />
          </svg>
        </div>
        <div>
          <h1>Agentic RAG Lab</h1>
          <p>Adaptive retrieval research assistant</p>
        </div>
      </div>

      <button
        type="button"
        className="primary-btn new-chat-btn"
        onClick={() => {
          onNewChat()
          onClose()
        }}
      >
        <Plus size={16} style={{ marginRight: 6, verticalAlign: -3 }} />
        New chat
      </button>

      <div className="chat-history-wrap">
        <p className="section-label">Chats</p>
        <ChatHistory
          chats={chats}
          activeChatId={activeChatId}
          onSelect={(id) => {
            onSelectChat(id)
            onClose()
          }}
          onDelete={onDeleteChat}
          onRename={onRenameChat}
        />
      </div>

      <div className="sidebar-footer">
        <button
          type="button"
          className={`ghost-btn settings-toggle ${settingsOpen ? 'active' : ''}`}
          onClick={() => setSettingsOpen((v) => !v)}
          aria-expanded={settingsOpen}
        >
          <Settings2 size={15} style={{ marginRight: 6, verticalAlign: -2 }} />
          Settings · {active.label}
        </button>

        {settingsOpen && (
          <div className="settings-panel">
            <p className="section-label">Agent mode</p>
            <div className="mode-list compact" role="listbox" aria-label="Agent modes">
              {modes.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  role="option"
                  aria-selected={mode === m.id}
                  className={`mode-btn ${mode === m.id ? 'active' : ''}`}
                  onClick={() => onModeChange(m.id)}
                >
                  <span className="phase">{m.phase}</span>
                  <span className="label">{m.label}</span>
                </button>
              ))}
            </div>
            <p className="mode-desc">{active.description}</p>

            <p className="section-label" style={{ marginTop: '1rem' }}>
              Preferences
            </p>
            <div className="toggles">
              <div className="toggle-row">
                <span>Conversation memory</span>
                <button
                  type="button"
                  className={`switch ${useMemory ? 'on' : ''}`}
                  aria-pressed={useMemory}
                  aria-label="Toggle conversation memory"
                  onClick={() => onUseMemoryChange(!useMemory)}
                >
                  <span />
                </button>
              </div>
              <div className="toggle-row">
                <span>Show agent trace</span>
                <button
                  type="button"
                  className={`switch ${showTrace ? 'on' : ''}`}
                  aria-pressed={showTrace}
                  aria-label="Toggle agent trace"
                  onClick={() => onShowTraceChange(!showTrace)}
                >
                  <span />
                </button>
              </div>
            </div>

            <div style={{ marginTop: '0.85rem' }}>
              <span className={`status-pill ${healthOk ? '' : 'warn'}`}>{healthLabel}</span>
            </div>

            <button
              type="button"
              className="ghost-btn"
              style={{ marginTop: '0.75rem', width: '100%' }}
              onClick={onClearChat}
            >
              <Eraser size={15} style={{ marginRight: 6, verticalAlign: -2 }} />
              Clear current chat
            </button>
          </div>
        )}
      </div>
    </aside>
  )
}

export function MenuToggle({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" className="menu-btn" onClick={onClick} aria-label="Open menu">
      <Menu size={18} />
    </button>
  )
}
