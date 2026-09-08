import { Bug, ChevronDown, Menu } from 'lucide-react'
import type { AgentMode, ModeMeta } from '../types'

interface HeaderProps {
  title: string
  subtitle: string
  mode: AgentMode
  modes: ModeMeta[]
  onModeChange: (mode: AgentMode) => void
  debugMode: boolean
  onDebugToggle: () => void
  onOpenSidebar: () => void
}

export function Header({
  title,
  subtitle,
  mode,
  modes,
  onModeChange,
  debugMode,
  onDebugToggle,
  onOpenSidebar,
}: HeaderProps) {
  return (
    <header className="main-header">
      <div className="header-left">
        <button type="button" className="menu-btn" onClick={onOpenSidebar} aria-label="Open sidebar">
          <Menu size={18} />
        </button>
        <div className="header-titles">
          <h2>{title}</h2>
          <p className="caption">{subtitle}</p>
        </div>
      </div>
      <div className="header-actions">
        <label className="mode-select">
          <span>Mode</span>
          <select
            value={modes.some((m) => m.id === mode) ? mode : (modes[0]?.id ?? 'canonical')}
            onChange={(e) => onModeChange(e.target.value as AgentMode)}
            aria-label="Agent mode"
          >
            {modes.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
          <ChevronDown size={14} />
        </label>
        <button
          type="button"
          className={`ghost-btn debug-toggle ${debugMode ? 'active' : ''}`}
          onClick={onDebugToggle}
          aria-pressed={debugMode}
          title={debugMode ? 'Close debug panel' : 'Open debug panel'}
        >
          <Bug size={15} />
          {debugMode ? 'Close debug' : 'Debug'}
        </button>
      </div>
    </header>
  )
}
