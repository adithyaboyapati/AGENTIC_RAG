interface ThinkingProps {
  modeLabel: string
  steps: string[]
}

export function Thinking({ modeLabel, steps }: ThinkingProps) {
  return (
    <div className="thinking" aria-live="polite">
      <div className="message-avatar" aria-hidden>
        A
      </div>
      <div className="thinking-panel">
        <div className="thinking-title">
          <span className="pulse-dot" />
          Running {modeLabel}…
        </div>
        <ul className="thinking-steps">
          {steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ul>
      </div>
    </div>
  )
}
