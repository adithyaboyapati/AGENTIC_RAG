import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { ArrowUp, Square } from 'lucide-react'

interface ChatInputProps {
  disabled?: boolean
  isLoading?: boolean
  onSend: (question: string) => void
  onStop?: () => void
  /** Prefill the composer; pair with seedKey to re-apply the same text. */
  seedText?: string
  seedKey?: number
}

export function ChatInput({
  disabled,
  isLoading,
  onSend,
  onStop,
  seedText,
  seedKey,
}: ChatInputProps) {
  const [value, setValue] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)

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
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
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
        <textarea
          ref={ref}
          rows={1}
          value={value}
          disabled={disabled && !isLoading}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask a question about RAG…"
          aria-label="Message"
        />
        {isLoading ? (
          <button
            type="button"
            className="send-btn stop-btn"
            onClick={() => onStop?.()}
            aria-label="Stop generation"
          >
            <Square size={16} strokeWidth={2.4} fill="currentColor" />
          </button>
        ) : (
          <button
            type="submit"
            className="send-btn"
            disabled={disabled || !value.trim()}
            aria-label="Send message"
          >
            <ArrowUp size={20} strokeWidth={2.4} />
          </button>
        )}
      </form>
      <p className="composer-hint">Enter to send · Shift+Enter for a new line</p>
    </div>
  )
}
