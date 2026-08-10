import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ChatMessage as ChatMessageType } from '../types'
import { FollowUps } from './FollowUps'
import { TracePanel } from './TracePanel'

interface ChatMessageProps {
  message: ChatMessageType
  showTrace: boolean
  showFollowUps?: boolean
  followUpsDisabled?: boolean
  onFollowUp?: (question: string) => void
}

export function ChatMessage({
  message,
  showTrace,
  showFollowUps = false,
  followUpsDisabled = false,
  onFollowUp,
}: ChatMessageProps) {
  const isUser = message.role === 'user'
  const classes = [
    'message',
    message.role,
    message.error ? 'error' : '',
  ]
    .filter(Boolean)
    .join(' ')

  const followUps = message.followUps ?? message.trace?.follow_ups ?? []

  return (
    <article className={classes}>
      <div className="message-avatar" aria-hidden>
        {isUser ? 'Y' : 'A'}
      </div>
      <div className="message-body">
        <div className="message-role">{isUser ? 'You' : 'Assistant'}</div>
        <div className="bubble">
          {isUser ? (
            <p>{message.content}</p>
          ) : (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
          )}
        </div>
        {!isUser && showTrace && message.trace && <TracePanel trace={message.trace} />}
        {!isUser && showFollowUps && onFollowUp && (
          <FollowUps
            questions={followUps}
            disabled={followUpsDisabled}
            onSelect={onFollowUp}
          />
        )}
      </div>
    </article>
  )
}
