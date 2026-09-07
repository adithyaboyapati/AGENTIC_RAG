import { useRef } from 'react'
import { FileText, LoaderCircle, Trash2, Upload } from 'lucide-react'
import type { IndexedDocument, IngestJob } from '../../types'

interface DocumentsPanelProps {
  open: boolean
  documents: IndexedDocument[]
  totalChunks: number
  jobs: IngestJob[]
  loading: boolean
  uploading: boolean
  error: string | null
  notice: string | null
  onClose: () => void
  onUpload: (files: File[]) => void
  onDelete: (source: string) => void
}

function jobLabel(job: IngestJob): string {
  const name = job.source_paths[0]?.split(/[/\\]/).pop() || job.job_id
  return `${name} · ${job.status}${job.status === 'processing' ? ` ${Math.round(job.progress_pct)}%` : ''}`
}

export function DocumentsPanel({
  open,
  documents,
  totalChunks,
  jobs,
  loading,
  uploading,
  error,
  notice,
  onClose,
  onUpload,
  onDelete,
}: DocumentsPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  if (!open) return null

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()} aria-label="Documents">
        <header className="drawer-header">
          <div>
            <h2>Documents</h2>
            <p>
              {documents.length} source{documents.length === 1 ? '' : 's'} · {totalChunks} chunks
            </p>
          </div>
          <button type="button" className="ghost-btn" onClick={onClose}>
            Close
          </button>
        </header>

        <div
          className="dropzone"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault()
            onUpload([...e.dataTransfer.files])
          }}
        >
          <Upload size={18} />
          <div>
            <strong>Upload PDFs</strong>
            <p>Drop files here or browse. They are indexed through the ingest job API.</p>
          </div>
          <button
            type="button"
            className="primary-btn"
            disabled={uploading}
            onClick={() => inputRef.current?.click()}
          >
            {uploading ? 'Uploading…' : 'Choose files'}
          </button>
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf,.pdf"
            multiple
            hidden
            onChange={(e) => {
              onUpload([...(e.target.files ?? [])])
              e.target.value = ''
            }}
          />
        </div>

        {error && <p className="banner error">{error}</p>}
        {notice && <p className="banner ok">{notice}</p>}

        {jobs.some((j) => j.status === 'queued' || j.status === 'processing' || j.status === 'failed') && (
          <section>
            <p className="section-label">Ingest jobs</p>
            <ul className="job-list">
              {jobs.slice(0, 8).map((job) => (
                <li key={job.job_id} className={`job-item ${job.status}`}>
                  {job.status === 'processing' ? <LoaderCircle size={14} className="spin" /> : <FileText size={14} />}
                  <span>{jobLabel(job)}</span>
                  {job.error && <em>{job.error}</em>}
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="doc-list-wrap">
          <p className="section-label">Indexed sources</p>
          {loading && documents.length === 0 ? (
            <p className="muted">Loading index…</p>
          ) : documents.length === 0 ? (
            <p className="muted">Nothing indexed yet. Upload a PDF to get started.</p>
          ) : (
            <ul className="doc-list">
              {documents.map((doc) => (
                <li key={doc.source} className="doc-item">
                  <FileText size={16} />
                  <div>
                    <strong>{doc.filename}</strong>
                    <p>
                      {doc.chunk_count} chunks
                      {doc.page_count ? ` · ${doc.page_count} pages` : ''}
                    </p>
                  </div>
                  <button
                    type="button"
                    className="chat-icon-btn danger"
                    aria-label={`Remove ${doc.filename}`}
                    onClick={() => {
                      if (window.confirm(`Remove ${doc.filename} from the index?`)) onDelete(doc.source)
                    }}
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </aside>
    </div>
  )
}
