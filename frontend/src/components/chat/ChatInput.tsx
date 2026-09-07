import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { ArrowUp, Paperclip, Square } from 'lucide-react'

interface ChatInputProps {
  disabled?: boolean
  isLoading?: boolean
  uploading?: boolean
  onSend: (question: string) => void
  onStop?: () => void
  onAttach?: (files: File[]) => void
  seedText?: string
  seedKey?: number
  placeholder?: string
}

export function ChatInput({
  disabled,
  isLoading,
  uploading,
  onSend,
  onStop,
  onAttach,
  seedText,
  seedKey,
  placeholder = 'Ask a question about your documents…',
}: ChatInputProps) {
  const [value, setValue] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (seedText && seedKey != null) {
      setValue(seedText)
      ref.current?.focus()
    }
  }, [seedText, seedKey])

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`
  }, [value])

  function submit() {
    const trimmed = value.trim()
    if (!trimmed || disabled || isLoading) return
    onSend(trimmed)
    setValue('')
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    submit()
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="composer-wrap">
      <form className="composer" onSubmit={onSubmit}>
        {onAttach && (
          <>
            <input
              ref={fileRef}
              type="file"
              accept="application/pdf,.pdf"
              multiple
              hidden
              onChange={(e) => {
                const files = [...(e.target.files ?? [])]
                if (files.length) onAttach(files)
                e.target.value = ''
              }}
            />
            <button
              type="button"
              className="composer-icon"
              onClick={() => fileRef.current?.click()}
              aria-label="Upload PDF"
              disabled={uploading || disabled}
              title="Upload PDF"
            >
              <Paperclip size={18} />
            </button>
          </>
        )}
        <textarea
          ref={ref}
          rows={1}
          value={value}
          disabled={disabled && !isLoading}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          aria-label="Message"
        />
        {isLoading ? (
          <button
            type="button"
            className="send-btn stop-btn"
            onClick={() => onStop?.()}
            aria-label="Stop generation"
          >
            <Square size={14} strokeWidth={2.4} fill="currentColor" />
          </button>
        ) : (
          <button
            type="submit"
            className="send-btn"
            disabled={disabled || !value.trim()}
            aria-label="Send message"
          >
            <ArrowUp size={18} strokeWidth={2.4} />
          </button>
        )}
      </form>
      <p className="composer-hint">Enter to send · Shift+Enter for a new line · PDFs only for upload</p>
    </div>
  )
}
