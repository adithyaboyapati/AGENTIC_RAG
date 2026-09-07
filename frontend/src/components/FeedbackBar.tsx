import { useEffect, useState } from 'react'
import { Check, ThumbsDown, ThumbsUp, X } from 'lucide-react'
import type { FeedbackCategory, FeedbackRating, FeedbackSubmission, MessageFeedback } from '../types'

interface FeedbackBarProps {
  feedback?: MessageFeedback
  disabled?: boolean
  onSubmit: (submission: FeedbackSubmission) => void
}

const CATEGORY_LABELS: { id: FeedbackCategory; label: string }[] = [
  { id: 'hallucination', label: 'Made something up' },
  { id: 'wrong_source', label: 'Wrong / missing source' },
  { id: 'incomplete', label: 'Incomplete' },
  { id: 'off_topic', label: 'Off topic' },
  { id: 'too_slow', label: 'Too slow' },
  { id: 'formatting', label: 'Formatting' },
  { id: 'other', label: 'Other' },
]

export function FeedbackBar({ feedback, disabled = false, onSubmit }: FeedbackBarProps) {
  const [draftRating, setDraftRating] = useState<FeedbackRating | null>(null)
  const [comment, setComment] = useState('')
  const [categories, setCategories] = useState<FeedbackCategory[]>([])

  const saved = feedback?.status === 'saved'
  const pending = feedback?.status === 'pending'
  const failed = feedback?.status === 'failed'
  const locked = saved || pending || disabled

  // Close the form once the parent reports the result.
  useEffect(() => {
    if (saved) setDraftRating(null)
  }, [saved])

  function pick(rating: FeedbackRating) {
    if (locked) return
    if (rating === 'up') {
      // Positive signal is one click; a comment is optional and rarely given.
      onSubmit({ rating, comment: '', categories: [] })
      return
    }
    setDraftRating(rating)
  }

  function toggleCategory(id: FeedbackCategory) {
    setCategories((prev) =>
      prev.includes(id) ? prev.filter((c) => c !== id) : prev.length < 5 ? [...prev, id] : prev,
    )
  }

  function submit() {
    if (!draftRating) return
    onSubmit({ rating: draftRating, comment: comment.trim(), categories })
  }

  const activeRating = feedback?.rating ?? draftRating

  return (
    <div className="feedback" aria-label="Rate this answer">
      <div className="feedback-row">
        <span className="feedback-label">
          {saved ? 'Thanks for the feedback' : failed ? 'Could not save feedback' : 'Was this helpful?'}
        </span>
        <div className="feedback-buttons">
          <button
            type="button"
            className={`feedback-btn ${activeRating === 'up' ? 'active up' : ''}`}
            aria-label="Helpful"
            aria-pressed={activeRating === 'up'}
            title="Helpful"
            disabled={locked}
            onClick={() => pick('up')}
          >
            <ThumbsUp size={14} />
          </button>
          <button
            type="button"
            className={`feedback-btn ${activeRating === 'down' ? 'active down' : ''}`}
            aria-label="Not helpful"
            aria-pressed={activeRating === 'down'}
            title="Not helpful"
            disabled={locked}
            onClick={() => pick('down')}
          >
            <ThumbsDown size={14} />
          </button>
          {saved && <Check size={14} className="feedback-saved-icon" aria-hidden />}
        </div>
      </div>

      {draftRating === 'down' && !saved && (
        <form
          className="feedback-form"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <p className="feedback-form-title">What went wrong?</p>
          <div className="feedback-categories">
            {CATEGORY_LABELS.map((c) => (
              <button
                key={c.id}
                type="button"
                className={`feedback-chip ${categories.includes(c.id) ? 'selected' : ''}`}
                aria-pressed={categories.includes(c.id)}
                onClick={() => toggleCategory(c.id)}
              >
                {c.label}
              </button>
            ))}
          </div>
          <textarea
            className="feedback-textarea"
            rows={3}
            maxLength={2000}
            placeholder="Optional: tell us what the correct answer should have been, or what was missing."
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <div className="feedback-actions">
            <button
              type="button"
              className="feedback-cancel"
              onClick={() => {
                setDraftRating(null)
                setComment('')
                setCategories([])
              }}
            >
              <X size={13} /> Cancel
            </button>
            <button type="submit" className="feedback-submit" disabled={pending}>
              {pending ? 'Sending…' : 'Send feedback'}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}
