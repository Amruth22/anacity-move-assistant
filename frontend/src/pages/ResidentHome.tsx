import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import Chat from '../components/Chat'
import DocChecklist from '../components/DocChecklist'
import StatusBadge from '../components/StatusBadge'
import { usePersona } from '../context/persona'
import type { Community, MoveRequest } from '../types'

const OPEN = new Set(['submitted', 'needs_info', 'approved'])

/** The resident's desk: a context rail on the left (who you are, house rules,
 *  your requests), and the assistant filling the rest of the page. Clicking a
 *  request in the rail swaps the chat for that request's detail; the chat
 *  stays mounted so the conversation survives the detour. */
export default function ResidentHome() {
  const { persona } = usePersona()
  const [requests, setRequests] = useState<MoveRequest[]>([])
  const [community, setCommunity] = useState<Community | null>(null)
  const [view, setView] = useState<string>('chat')
  const [prefill, setPrefill] = useState<{ text: string; nonce: number } | undefined>()

  const resident = persona?.kind === 'resident' ? persona.resident : null

  const refresh = useCallback(() => {
    if (resident) api.residentRequests(resident.id).then(setRequests)
  }, [resident?.id])

  useEffect(() => {
    refresh()
  }, [refresh])

  useEffect(() => {
    if (resident)
      api.communities().then((cs) => setCommunity(cs.find((c) => c.id === resident.community_id) ?? null))
  }, [resident?.community_id])

  if (!resident || persona?.kind !== 'resident') return null

  const open = requests.filter((r) => OPEN.has(r.status))
  const selected = requests.find((r) => r.id === view)
  const hour = new Date().getHours()
  const hello = `${hour < 12 ? 'Morning' : hour < 17 ? 'Afternoon' : 'Evening'}, ${resident.name.split(' ')[0]}.`
  const context = `${resident.unit_label} · ${persona.communityName} · ${
    open.length === 0 ? 'no open requests' : open.length === 1 ? 'one open request' : `${open.length} open requests`
  }`

  const mi = community?.policies.move_in
  const mo = community?.policies.move_out

  const openRequest = (id: string) => {
    refresh()
    setView(view === id ? 'chat' : id)
  }

  const patchRequest = (updated: MoveRequest) =>
    setRequests((prev) => prev.map((x) => (x.id === updated.id ? { ...x, ...updated } : x)))

  const replyToAdmin = (r: MoveRequest) => {
    const kind = r.type === 'move_in' ? 'move-in' : 'move-out'
    const day = new Date(`${r.requested_date}T00:00:00`).toLocaleDateString('en-IN', {
      day: 'numeric',
      month: 'long',
    })
    setPrefill({ text: `About my ${kind} on ${day}: `, nonce: Date.now() })
    setView('chat')
  }

  const labelFor = (r: MoveRequest, key: string) =>
    community?.policies[r.type]?.custom_fields.find((f) => f.key === key)?.label ??
    key.replace(/_/g, ' ')

  return (
    <div className="workspace">
      <aside className="rail">
        <div className="rail-card">
          <h5>You</h5>
          <b>{resident.name}</b>
          <small>
            {resident.unit_label} · {resident.tenancy}
          </small>
          <small>{persona.communityName}</small>
        </div>

        {mi && mo && (
          <div className="rail-card">
            <h5>House rules</h5>
            <small>
              Move-in: {mi.notice_days} day{mi.notice_days === 1 ? '' : 's'} notice
              {mi.deposit ? `, ₹${mi.deposit.amount.toLocaleString('en-IN')} deposit` : ''}
            </small>
            <small>
              Move-out: {mo.notice_days} day{mo.notice_days === 1 ? '' : 's'} notice
            </small>
            <small>
              Hours: {mi.hours.start} to {mi.hours.end}
            </small>
            <small className="rail-hint">The assistant checks the fine print for you.</small>
          </div>
        )}

        <div className="rail-card">
          <h5>Your requests</h5>
          {requests.length === 0 && <small>None yet. The assistant files them for you.</small>}
          {requests.map((r) => {
            const done = r.checklist.filter((c) => c.done).length
            return (
              <button
                key={r.id}
                className={`rail-req ${view === r.id ? 'active' : ''}`}
                onClick={() => openRequest(r.id)}
              >
                <b>
                  {r.type === 'move_in' ? 'Move-in' : 'Move-out'} · {r.requested_date}
                </b>
                <StatusBadge status={r.status} />
                {r.checklist.length > 0 && (
                  <>
                    <span className="prog">
                      <i style={{ width: `${(done / r.checklist.length) * 100}%` }} />
                    </span>
                    <small>
                      {done}/{r.checklist.length} items done
                    </small>
                  </>
                )}
              </button>
            )
          })}
        </div>

        {view !== 'chat' && (
          <button className="rail-back" onClick={() => setView('chat')}>
            ← Back to the assistant
          </button>
        )}
      </aside>

      <section className="workpane">
        <div className="chat-holder" style={{ display: view === 'chat' ? 'flex' : 'none' }}>
          <Chat
            residentId={resident.id}
            onRequestCreated={refresh}
            greeting={{ hello, context }}
            prefill={prefill}
          />
        </div>

        {selected && view !== 'chat' && (
          <div className="request-pane">
            <div className="section-head">
              <h1>
                {selected.type === 'move_in' ? 'Move-in' : 'Move-out'} · {selected.requested_date}
              </h1>
              <StatusBadge status={selected.status} />
              <span className="count mono">{selected.id}</span>
            </div>

            {selected.status === 'needs_info' && (
              <div className="needs-info-nudge">
                The admin desk needs something from you. Check the latest timeline note below, then
                reply through the assistant (or upload the missing document here). Replying
                resubmits your request automatically.
                <button className="nudge-cta" onClick={() => replyToAdmin(selected)}>
                  Reply to the admin
                </button>
              </div>
            )}

            <div className="panel">
              <h2>Details</h2>
              <dl className="fact-rows">
                <div>
                  <dt>Time window</dt>
                  <dd>{selected.time_window}</dd>
                </div>
                {Object.entries(selected.custom_fields).map(([k, v]) => (
                  <div key={k}>
                    <dt>{labelFor(selected, k)}</dt>
                    <dd>{String(v)}</dd>
                  </div>
                ))}
                {selected.notes && (
                  <div>
                    <dt>Notes</dt>
                    <dd>{selected.notes}</dd>
                  </div>
                )}
              </dl>
            </div>

            <div className="panel">
              <h2>Documents &amp; tasks</h2>
              <DocChecklist request={selected} role="resident" residentId={resident.id} onChange={patchRequest} />
            </div>

            <div className="panel">
              <h2>Timeline</h2>
              <ul className="timeline">
                {selected.timeline.map((t, i) => (
                  <li key={i}>
                    <span className="ts">{t.ts.replace('T', ' · ')}</span>
                    <div className="ev">{t.event.replace('_', ' ')}</div>
                    {t.note && <div className="note">{t.note}</div>}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
