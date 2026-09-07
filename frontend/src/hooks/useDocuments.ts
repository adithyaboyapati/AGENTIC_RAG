import { useCallback, useEffect, useState } from 'react'
import {
  deleteDocument,
  getIngestJob,
  listDocuments,
  listIngestJobs,
  uploadDocuments,
} from '../api/client'
import type { IndexedDocument, IngestJob } from '../types'

const ACTIVE_JOB = new Set(['queued', 'processing'])

export function useDocuments(enabled: boolean) {
  const [documents, setDocuments] = useState<IndexedDocument[]>([])
  const [totalChunks, setTotalChunks] = useState(0)
  const [jobs, setJobs] = useState<IngestJob[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [docs, jobList] = await Promise.all([listDocuments(), listIngestJobs(20)])
      setDocuments(docs.documents)
      setTotalChunks(docs.total_chunks)
      setJobs(jobList)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load documents')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!enabled) return
    void refresh()
  }, [enabled, refresh])

  useEffect(() => {
    const active = jobs.filter((j) => ACTIVE_JOB.has(j.status))
    if (!active.length) return
    const id = window.setInterval(async () => {
      try {
        const updated = await Promise.all(active.map((j) => getIngestJob(j.job_id)))
        setJobs((prev) => {
          const byId = new Map(prev.map((j) => [j.job_id, j]))
          for (const job of updated) byId.set(job.job_id, job)
          return [...byId.values()].sort((a, b) => b.created_at - a.created_at)
        })
        if (updated.some((j) => j.status === 'completed')) {
          const docs = await listDocuments()
          setDocuments(docs.documents)
          setTotalChunks(docs.total_chunks)
        }
      } catch {
        /* keep last snapshot */
      }
    }, 1500)
    return () => window.clearInterval(id)
  }, [jobs])

  const upload = useCallback(async (files: File[]) => {
    const pdfs = files.filter((f) => f.name.toLowerCase().endsWith('.pdf'))
    if (!pdfs.length) {
      setError('Only PDF files can be ingested')
      return
    }
    setUploading(true)
    setError(null)
    try {
      const result = await uploadDocuments(pdfs)
      setNotice(`Queued ${result.job_ids.length} ingest job${result.job_ids.length === 1 ? '' : 's'}`)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }, [refresh])

  const remove = useCallback(async (source: string) => {
    try {
      await deleteDocument(source)
      setNotice('Document removed from the index')
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed')
    }
  }, [refresh])

  return {
    documents,
    totalChunks,
    jobs,
    loading,
    uploading,
    error,
    notice,
    setNotice,
    setError,
    refresh,
    upload,
    remove,
  }
}
