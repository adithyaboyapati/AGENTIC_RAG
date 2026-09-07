import { getMode } from '../../data/modes'
import type { AgentMode, ModeMeta, RuntimeConfig } from '../../types'

interface SettingsPanelProps {
  open: boolean
  mode: AgentMode
  modes: ModeMeta[]
  onModeChange: (mode: AgentMode) => void
  useMemory: boolean
  onUseMemoryChange: (value: boolean) => void
  debugMode: boolean
  onDebugModeChange: (value: boolean) => void
  memoryLockedOff?: boolean
  runtimeConfig: RuntimeConfig | null
  onClearChat: () => void
  onClose: () => void
}

export function SettingsPanel({
  open,
  mode,
  modes,
  onModeChange,
  useMemory,
  onUseMemoryChange,
  debugMode,
  onDebugModeChange,
  memoryLockedOff,
  runtimeConfig,
  onClearChat,
  onClose,
}: SettingsPanelProps) {
  const active = modes.find((m) => m.id === mode) ?? getMode(mode)
  if (!open) return null

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()} aria-label="Settings">
        <header className="drawer-header">
          <div>
            <h2>Settings</h2>
            <p>Agent mode and conversation options. Model weights live on the server.</p>
          </div>
          <button type="button" className="ghost-btn" onClick={onClose}>
            Close
          </button>
        </header>

        <p className="section-label">Agent mode</p>
        <div className="mode-list" role="listbox" aria-label="Agent modes">
          {modes.map((m) => (
            <button
              key={m.id}
              type="button"
              role="option"
              aria-selected={mode === m.id}
              className={`mode-btn ${mode === m.id ? 'active' : ''}`}
              onClick={() => onModeChange(m.id)}
            >
              <span className="phase">{m.phase}</span>
              <span className="label">{m.label}</span>
            </button>
          ))}
        </div>
        <p className="mode-desc">{active.description}</p>

        <p className="section-label">Preferences</p>
        <div className="toggles">
          <div className="toggle-row">
            <span>
              Conversation memory
              {memoryLockedOff ? <em className="muted"> · disabled on server</em> : null}
            </span>
            <button
              type="button"
              className={`switch ${useMemory && !memoryLockedOff ? 'on' : ''}`}
              aria-pressed={useMemory}
              disabled={memoryLockedOff}
              onClick={() => onUseMemoryChange(!useMemory)}
            >
              <span />
            </button>
          </div>
          <div className="toggle-row">
            <span>Developer / debug pipeline</span>
            <button
              type="button"
              className={`switch ${debugMode ? 'on' : ''}`}
              aria-pressed={debugMode}
              onClick={() => onDebugModeChange(!debugMode)}
            >
              <span />
            </button>
          </div>
        </div>

        {runtimeConfig && (
          <>
            <p className="section-label">Server configuration</p>
            <dl className="config-grid">
              <div>
                <dt>Chat model</dt>
                <dd>{runtimeConfig.openai_model}</dd>
              </div>
              <div>
                <dt>Embeddings</dt>
                <dd>{runtimeConfig.embedding_model}</dd>
              </div>
              <div>
                <dt>Retrieval</dt>
                <dd>
                  {runtimeConfig.retrieval_search_type} · k={runtimeConfig.retrieval_top_k}
                </dd>
              </div>
              <div>
                <dt>Rerank</dt>
                <dd>
                  {runtimeConfig.rerank_enabled
                    ? `${runtimeConfig.rerank_provider} / ${runtimeConfig.rerank_model}`
                    : 'off'}
                </dd>
              </div>
              <div>
                <dt>Chunking</dt>
                <dd>{runtimeConfig.chunking_strategy}</dd>
              </div>
              <div>
                <dt>Upload limit</dt>
                <dd>{runtimeConfig.ingest_max_upload_mb} MB</dd>
              </div>
            </dl>
          </>
        )}

        <button type="button" className="ghost-btn danger-text" onClick={onClearChat}>
          Clear current chat
        </button>
      </aside>
    </div>
  )
}
