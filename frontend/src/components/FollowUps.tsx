interface FollowUpsProps {
  questions: string[]
  disabled?: boolean
  onSelect: (question: string) => void
}

export function FollowUps({ questions, disabled, onSelect }: FollowUpsProps) {
  if (!questions.length) return null

  return (
    <div className="follow-ups" aria-label="Suggested follow-up questions">
      <p className="follow-ups-label">Continue exploring</p>
      <div className="follow-ups-row">
        {questions.map((q) => (
          <button
            key={q}
            type="button"
            className="follow-up-chip"
            disabled={disabled}
            onClick={() => onSelect(q)}
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  )
}
