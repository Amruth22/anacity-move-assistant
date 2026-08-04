import { useRef, useState } from 'react'
import { api } from '../api/client'
import type { MoveRequest } from '../types'

/** Checklist with real files. Residents upload; admins view and verify.
 *  The same component serves both - the role decides which controls show. */
export default function DocChecklist({ request, role, residentId, onChange }: {
  request: MoveRequest
  role: 'resident' | 'admin'
  residentId?: string
  onChange: (updated: MoveRequest) => void
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const pendingDoc = useRef<string | null>(null)

  const residentCanEdit = request.status === 'submitted' || request.status === 'needs_info'
  const adminCanAct = residentCanEdit || request.status === 'approved'

  const pickFile = (docId: string) => {
    pendingDoc.current = docId
    fileInput.current?.click()
  }

  const onFileChosen = async () => {
    const file = fileInput.current?.files?.[0]
    const docId = pendingDoc.current
    if (!file || !docId || !residentId) return
    setBusy(docId)
    setError('')
    try {
      onChange(await api.uploadDocument(request.id, docId, residentId, file))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setBusy(null)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  const verify = async (docId: string) => {
    setBusy(docId)
    setError('')
    try {
      onChange(await api.verifyDocument(request.id, docId))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not verify')
    } finally {
      setBusy(null)
    }
  }

  const markDone = async (itemId: string) => {
    setBusy(itemId)
    setError('')
    try {
      onChange(await api.completeTask(request.id, itemId))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not update the task')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div>
      {role === 'resident' && (
        <input
          ref={fileInput}
          type="file"
          accept=".pdf,.png,.jpg,.jpeg,.webp"
          style={{ display: 'none' }}
          onChange={onFileChosen}
        />
      )}
      {request.checklist.map((c) =>
        c.kind === 'task' ? (
          <div className={`doc-row task ${c.done ? 'done' : ''}`} key={c.id}>
            <span className="box">{c.done ? '✓' : ''}</span>
            <div className="doc-meta">
              <span className="doc-name">{c.name}</span>
              <small>{c.done ? 'done' : 'handled with the admin desk'}</small>
            </div>
            {role === 'admin' && !c.done && adminCanAct && (
              <button className="doc-btn verify" disabled={busy === c.id} onClick={() => markDone(c.id)}>
                {busy === c.id ? '…' : 'Mark done'}
              </button>
            )}
          </div>
        ) : (
          <div className={`doc-row ${c.done ? 'done' : c.file ? 'uploaded' : ''}`} key={c.id}>
            <span className="box">{c.done ? '✓' : c.file ? '·' : ''}</span>
            <div className="doc-meta">
              <span className="doc-name">{c.name}</span>
              {c.done && c.file && (
                <small>
                  verified ·{' '}
                  <a href={api.documentUrl(request.id, c.id)} target="_blank" rel="noreferrer">
                    {c.file.filename}
                  </a>
                </small>
              )}
              {c.done && !c.file && <small>verified offline by admin</small>}
              {!c.done && c.file && (
                <small>
                  awaiting review ·{' '}
                  <a href={api.documentUrl(request.id, c.id)} target="_blank" rel="noreferrer">
                    {c.file.filename}
                  </a>
                </small>
              )}
              {!c.done && !c.file && <small>not uploaded yet</small>}
            </div>

            {role === 'resident' && !c.done && residentCanEdit && (
              <button className="doc-btn" disabled={busy === c.id} onClick={() => pickFile(c.id)}>
                {busy === c.id ? 'Uploading…' : c.file ? 'Replace' : 'Upload'}
              </button>
            )}
            {role === 'admin' && !c.done && c.file && adminCanAct && (
              <button className="doc-btn verify" disabled={busy === c.id} onClick={() => verify(c.id)}>
                {busy === c.id ? '…' : 'Verify'}
              </button>
            )}
          </div>
        ),
      )}
      {error && <div className="error-note">{error}</div>}
    </div>
  )
}
