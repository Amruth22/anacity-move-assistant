import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import CopilotPanel from '../components/CopilotPanel'
import DocChecklist from '../components/DocChecklist'
import StatusBadge from '../components/StatusBadge'
import type { Community, MoveRequest } from '../types'

const ACTION_FOR_STATUS: Record<string, string[]> = {
  submitted: ['approve', 'reject', 'request_info'],
  needs_info: ['approve', 'reject', 'request_info'],
  approved: ['complete'],
}

export default function AdminRequestDetail() {
  const { id } = useParams<{ id: string }>()
  const [request, setRequest] = useState<MoveRequest | null>(null)
  const [communities, setCommunities] = useState<Community[]>([])
  const [note, setNote] = useState('')
  const [acting, setActing] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api.communities().then(setCommunities)
  }, [])

  const load = useCallback(() => {
    if (id) api.request(id).then(setRequest).catch(() => setError('Request not found'))
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  const act = async (action: string) => {
    if (!id || acting) return
    setActing(true)
    setError('')
    try {
      const updated = await api.adminAction(id, action, note)
      setRequest(updated)
      setNote('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Action failed')
    } finally {
      setActing(false)
    }
  }

  if (error && !request) return <div className="error-note">{error}</div>
  if (!request) return <div className="empty-note">Loading…</div>

  const available = ACTION_FOR_STATUS[request.status] ?? []
  const fields = communities.find((c) => c.id === request.community_id)?.policies[request.type]?.custom_fields
  const labelFor = (key: string) => fields?.find((f) => f.key === key)?.label ?? key.replace(/_/g, ' ')

  return (
    <div className="request-pane">
      <div className="detail-wrap">
      <div className="section-head">
        <h1>
          {request.type === 'move_in' ? 'Move-in' : 'Move-out'} · {request.unit_label}
        </h1>
        <StatusBadge status={request.status} />
        <span className="count mono">{request.id}</span>
        <div className="filters">
          <Link to="/admin">← All requests</Link>
        </div>
      </div>

      <div className="detail-grid">
        <div>
          <div className="panel">
            <h2>Request</h2>
            <dl className="fact-rows">
              <div>
                <dt>Resident</dt>
                <dd>
                  {request.resident_name} ({request.tenancy})
                </dd>
              </div>
              <div>
                <dt>Community</dt>
                <dd>{request.community_name}</dd>
              </div>
              <div>
                <dt>Date</dt>
                <dd>{request.requested_date}</dd>
              </div>
              <div>
                <dt>Time window</dt>
                <dd>{request.time_window}</dd>
              </div>
              {Object.entries(request.custom_fields).map(([k, v]) => (
                <div key={k}>
                  <dt>{labelFor(k)}</dt>
                  <dd>{String(v)}</dd>
                </div>
              ))}
              {request.notes && (
                <div>
                  <dt>Notes</dt>
                  <dd>{request.notes}</dd>
                </div>
              )}
            </dl>
          </div>

          <div className="panel">
            <h2>Documents &amp; tasks</h2>
            <DocChecklist
              request={request}
              role="admin"
              onChange={(updated) => setRequest((prev) => (prev ? { ...prev, ...updated } : prev))}
            />
          </div>

          <div className="panel">
            <h2>Timeline</h2>
            <ul className="timeline">
              {request.timeline.map((t, i) => (
                <li key={i}>
                  <span className="ts">{t.ts.replace('T', ' · ')}</span>
                  <div className="ev">{t.event.replace('_', ' ')}</div>
                  {t.note && <div className="note">{t.note}</div>}
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div>
          <CopilotPanel
            requestId={request.id}
            cached={request.copilot}
            onAssessed={() => load()}
            onUseReply={(text) => setNote(text)}
          />

          {available.length > 0 && (
            <div className="panel">
              <h2>Take action</h2>
              <textarea
                className="note-input"
                placeholder="Note to the resident (required for reject / request info, and for approving over pending items)"
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
              {error && <div className="error-note">{error}</div>}
              <div className="action-row">
                {available.includes('approve') && (
                  <button className="approve" disabled={acting} onClick={() => act('approve')}>
                    Approve
                  </button>
                )}
                {available.includes('request_info') && (
                  <button
                    className="info"
                    disabled={acting || !note.trim()}
                    title={note.trim() ? undefined : 'Tell the resident what you need first'}
                    onClick={() => act('request_info')}
                  >
                    Request info
                  </button>
                )}
                {available.includes('reject') && (
                  <button
                    className="reject"
                    disabled={acting || !note.trim()}
                    title={note.trim() ? undefined : 'A rejection needs a reason the resident can read'}
                    onClick={() => act('reject')}
                  >
                    Reject
                  </button>
                )}
                {available.includes('complete') && (
                  <button className="approve" disabled={acting} onClick={() => act('complete')}>
                    Mark completed
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
      </div>
    </div>
  )
}
