import { FileStack, PanelLeftClose, Search, Settings2, SquarePen } from 'lucide-react'
import { useState } from 'react'
import type { AgentMode, ModeMeta, StoredChat } from '../../types'
import { ChatHistory } from './ChatHistory'

interface SidebarProps {
  open: boolean
  chats: StoredChat[]
  activeChatId: string
  mode: AgentMode
  modes: ModeMeta[]
  healthOk: boolean
  healthLabel: string
  onSelectChat: (chatId: string) => void
  onNewChat: () => void
  onDeleteChat: (chatId: string) => void
  onRenameChat: (chatId: string, title: string) => void
  onOpenDocuments: () => void
  onOpenSettings: () => void
  onClose: () => void
}

export function Sidebar({
  open,
  chats,
  activeChatId,
  mode,
  modes,
  healthOk,
  healthLabel,
  onSelectChat,
  onNewChat,
  onDeleteChat,
  onRenameChat,
  onOpenDocuments,
  onOpenSettings,
  onClose,
}: SidebarProps) {
  const [query, setQuery] = useState('')
  const active = modes.find((m) => m.id === mode)

  return (
    <aside className={`sidebar ${open ? 'open' : ''}`} aria-label="Conversations">
      <div className="brand">
        <div className="brand-mark" aria-hidden>
          <svg viewBox="0 0 24 24" fill="none">
            <path
              d="M4 18V6l8 6 8-6v12"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <circle cx="12" cy="12" r="2" fill="currentColor" />
          </svg>
        </div>
        <div className="brand-copy">
          <h1>Agentic RAG</h1>
          <p>{active?.label ?? 'Research assistant'}</p>
        </div>
        <button type="button" className="sidebar-collapse" onClick={onClose} aria-label="Close sidebar">
          <PanelLeftClose size={16} />
        </button>
      </div>

      <button
        type="button"
        className="primary-btn new-chat-btn"
        onClick={() => {
          onNewChat()
          onClose()
        }}
      >
        <SquarePen size={15} />
        New chat
      </button>

      <label className="sidebar-search">
        <Search size={14} />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search chats"
          aria-label="Search chats"
        />
      </label>

      <div className="chat-history-wrap">
        <ChatHistory
          chats={chats}
          activeChatId={activeChatId}
          query={query}
          onSelect={(id) => {
            onSelectChat(id)
            onClose()
          }}
          onDelete={onDeleteChat}
          onRename={onRenameChat}
        />
      </div>

      <div className="sidebar-footer">
        <button type="button" className="ghost-btn sidebar-link" onClick={onOpenDocuments}>
          <FileStack size={15} />
          Documents
        </button>
        <button type="button" className="ghost-btn sidebar-link" onClick={onOpenSettings}>
          <Settings2 size={15} />
          Settings
        </button>
        <span className={`status-pill ${healthOk ? '' : 'warn'}`}>{healthLabel}</span>
      </div>
    </aside>
  )
}
