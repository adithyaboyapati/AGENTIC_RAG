import { useState } from 'react'
import { Check, Copy } from 'lucide-react'
import type { ChatMessage as ChatMessageType, Citation, FeedbackSubmission } from '../../types'
import { FeedbackBar } from '../FeedbackBar'
import { CitationCards } from './CitationCards'
import { FollowUps } from './FollowUps'
import { MarkdownContent } from './MarkdownContent'

interface ChatMessageProps {
  message: ChatMessageType
  showFollowUps?: boolean
  followUpsDisabled?: boolean
  feedbackEnabled?: boolean
  onFollowUp?: (question: string) => void
  onFeedback?: (submission: FeedbackSubmission) => void
  onOpenCitation?: (citation: Citation) => void
}

export function ChatMessage({
  message,
  showFollowUps = false,
  followUpsDisabled = false,
  feedbackEnabled = true,
  onFollowUp,
  onFeedback,
  onOpenCitation,
}: ChatMessageProps) {
  const isUser = message.role === 'user'
  const [copied, setCopied] = useState(false)
  const followUps = message.followUps ?? message.trace?.follow_ups ?? []
  const citations = message.trace?.citations ?? []
  const sources = message.trace?.sources ?? []
  const classes = ['message', message.role, message.error ? 'error' : '', message.streaming ? 'streaming' : '']
    .filter(Boolean)
    .join(' ')

  async function copy() {
    try {
      await navigator.clipboard.writeText(message.content)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1400)
    } catch {
      /* ignore */
    }
  }

  return (
    <article className={classes}>
      {!isUser && (
        <div className="message-avatar assistant-avatar" aria-hidden>
          A
        </div>
      )}
      <div className="message-body">
        <div className={`bubble ${isUser ? 'user-bubble' : ''}`}>
          {isUser ? (
            <p>{message.content}</p>
          ) : message.error ? (
            <p>{message.content}</p>
          ) : (
            <MarkdownContent content={message.content} />
          )}
          {message.streaming && <span className="stream-caret" aria-hidden />}
        </div>

        {!isUser && !message.error && !message.streaming && message.content && (
          <div className="message-actions">
            <button type="button" className="icon-action" onClick={() => void copy()} aria-label="Copy answer">
              {copied ? <Check size={14} /> : <Copy size={14} />}
            </button>
            {message.trace?.latency_ms ? (
              <span className="latency-chip">{Math.round(message.trace.latency_ms)} ms</span>
            ) : null}
            {message.trace?.consensus_score != null && (
              <span className="latency-chip">
                Consensus {Math.round(message.trace.consensus_score * 100)}%
              </span>
            )}
          </div>
        )}

        {!isUser && !message.error && !message.streaming && feedbackEnabled && onFeedback && (
          <FeedbackBar feedback={message.feedback ?? undefined} onSubmit={onFeedback} />
        )}

        {!isUser && !message.error && (
          <CitationCards citations={citations} sources={sources} onOpen={onOpenCitation} />
        )}

        {!isUser && showFollowUps && onFollowUp && (
          <FollowUps questions={followUps} disabled={followUpsDisabled} onSelect={onFollowUp} />
        )}
      </div>
    </article>
  )
}
