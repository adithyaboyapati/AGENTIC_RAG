import { useEffect, useRef, useState } from 'react'
import { MessageSquare, Pencil, Trash2 } from 'lucide-react'
import { formatRelativeTime, groupChatsByTime } from '../lib/chatStore'
import type { StoredChat } from '../types'

interface ChatHistoryProps {
  chats: StoredChat[]
  activeChatId: string
  onSelect: (chatId: string) => void
  onDelete: (chatId: string) => void
  onRename: (chatId: string, title: string) => void
}

export function ChatHistory({
  chats,
  activeChatId,
  onSelect,
  onDelete,
  onRename,
}: ChatHistoryProps) {
  const groups = groupChatsByTime(chats)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editingId) inputRef.current?.focus()
  }, [editingId])

  function startRename(chat: StoredChat) {
    setEditingId(chat.id)
    setDraft(chat.title)
  }

  function commitRename() {
    if (!editingId) return
    onRename(editingId, draft)
    setEditingId(null)
  }

  if (chats.length === 0) {
    return <p className="chat-history-empty">No chats yet</p>
  }

  return (
    <div className="chat-history">
      {groups.map((group) => (
        <div key={group.label} className="chat-group">
          <p className="section-label">{group.label}</p>
          <ul className="chat-list">
            {group.chats.map((chat) => {
              const active = chat.id === activeChatId
              const editing = chat.id === editingId
              return (
                <li key={chat.id}>
                  <div className={`chat-item ${active ? 'active' : ''}`}>
                    {editing ? (
                      <form
                        className="chat-rename-form"
                        onSubmit={(e) => {
                          e.preventDefault()
                          commitRename()
                        }}
                      >
                        <input
                          ref={inputRef}
                          value={draft}
                          onChange={(e) => setDraft(e.target.value)}
                          onBlur={commitRename}
                          onKeyDown={(e) => {
                            if (e.key === 'Escape') setEditingId(null)
                          }}
                          aria-label="Rename chat"
                        />
                      </form>
                    ) : (
                      <button
                        type="button"
                        className="chat-item-main"
                        onClick={() => onSelect(chat.id)}
                        title={chat.title}
                      >
                        <MessageSquare size={14} className="chat-item-icon" />
                        <span className="chat-item-text">
                          <span className="chat-item-title">{chat.title}</span>
                          <span className="chat-item-meta">{formatRelativeTime(chat.updatedAt)}</span>
                        </span>
                      </button>
                    )}
                    {!editing && (
                      <div className="chat-item-actions">
                        <button
                          type="button"
                          className="chat-icon-btn"
                          aria-label="Rename chat"
                          title="Rename"
                          onClick={() => startRename(chat)}
                        >
                          <Pencil size={13} />
                        </button>
                        <button
                          type="button"
                          className="chat-icon-btn danger"
                          aria-label="Delete chat"
                          title="Delete"
                          onClick={() => {
                            if (window.confirm('Delete this chat?')) onDelete(chat.id)
                          }}
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        </div>
      ))}
    </div>
  )
}
