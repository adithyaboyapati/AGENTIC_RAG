import { classifyStep } from '../../lib/pipeline'

interface ThinkingProps {
  modeLabel: string
  steps: string[]
}

function statusFromSteps(steps: string[]): string {
  if (!steps.length) return 'Understanding your question'
  const last = classifyStep(steps[steps.length - 1])
  if (last === 'retrieval' || last === 'chunks') return 'Retrieving documents'
  if (last === 'rerank') return 'Reranking and grading evidence'
  if (last === 'context') return 'Building grounded context'
  if (last === 'generation') return 'Generating an answer'
  return 'Processing query'
}

export function Thinking({ modeLabel, steps }: ThinkingProps) {
  return (
    <div className="thinking" aria-live="polite">
      <div className="message-avatar assistant-avatar" aria-hidden>
        A
      </div>
      <div className="thinking-panel">
        <div className="thinking-title">
          <span className="pulse-dot" />
          {statusFromSteps(steps)}
          <span className="thinking-mode">{modeLabel}</span>
        </div>
        {steps.length > 0 && (
          <ul className="thinking-steps">
            {steps.slice(-6).map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
