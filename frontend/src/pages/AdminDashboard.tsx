import { useEffect, useState } from 'react'
import { api } from '../api/client'
import RequestCard from '../components/RequestCard'
import type { Community, MoveRequest } from '../types'

const STATUS_LABELS: [string, string][] = [
  ['submitted', 'Submitted'],
  ['needs_info', 'Needs info'],
  ['approved', 'Approved'],
  ['rejected', 'Rejected'],
  ['completed', 'Completed'],
  ['cancelled', 'Cancelled'],
]

/** The admin's desk: queue filters live in the rail as counted rows, the
 *  request list gets the rest of the page. */
export default function AdminDashboard() {
  const [requests, setRequests] = useState<MoveRequest[]>([])
  const [communities, setCommunities] = useState<Community[]>([])
  const [communityFilter, setCommunityFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [query, setQuery] = useState('')

  useEffect(() => {
    api.communities().then(setCommunities)
    api.requests().then(setRequests)
  }, [])

  const q = query.trim().toLowerCase()
  const matches = (r: MoveRequest) =>
    !q ||
    [r.resident_name, r.unit_label, r.id, r.community_name].some((s) =>
      s.toLowerCase().includes(q),
    )

  const base = requests.filter(
    (r) =>
      (!communityFilter || r.community_id === communityFilter) &&
      (!typeFilter || r.type === typeFilter) &&
      matches(r),
  )
  const filtered = base.filter((r) => !statusFilter || r.status === statusFilter)
  const countFor = (s: string) => base.filter((r) => r.status === s).length
  const countType = (t: string) =>
    requests.filter(
      (r) => (!communityFilter || r.community_id === communityFilter) && r.type === t && matches(r),
    ).length

  return (
    <div className="workspace">
      <aside className="rail">
        <div className="rail-card">
          <h5>Queue</h5>
          <button
            className={`rail-filter ${statusFilter === '' ? 'active' : ''}`}
            onClick={() => setStatusFilter('')}
          >
            <span>All requests</span>
            <span className="n">{base.length}</span>
          </button>
          {STATUS_LABELS.map(([s, label]) => (
            <button
              key={s}
              className={`rail-filter ${statusFilter === s ? 'active' : ''}`}
              onClick={() => setStatusFilter(statusFilter === s ? '' : s)}
            >
              <span>{label}</span>
              <span className="n">{countFor(s)}</span>
            </button>
          ))}
        </div>

        <div className="rail-card">
          <h5>Direction</h5>
          <button
            className={`rail-filter ${typeFilter === '' ? 'active' : ''}`}
            onClick={() => setTypeFilter('')}
          >
            <span>Both</span>
          </button>
          <button
            className={`rail-filter ${typeFilter === 'move_in' ? 'active' : ''}`}
            onClick={() => setTypeFilter(typeFilter === 'move_in' ? '' : 'move_in')}
          >
            <span>Move-in</span>
            <span className="n">{countType('move_in')}</span>
          </button>
          <button
            className={`rail-filter ${typeFilter === 'move_out' ? 'active' : ''}`}
            onClick={() => setTypeFilter(typeFilter === 'move_out' ? '' : 'move_out')}
          >
            <span>Move-out</span>
            <span className="n">{countType('move_out')}</span>
          </button>
        </div>

        <div className="rail-card">
          <h5>Community</h5>
          <button
            className={`rail-filter ${communityFilter === '' ? 'active' : ''}`}
            onClick={() => setCommunityFilter('')}
          >
            <span>All communities</span>
          </button>
          {communities.map((c) => (
            <button
              key={c.id}
              className={`rail-filter ${communityFilter === c.id ? 'active' : ''}`}
              onClick={() => setCommunityFilter(communityFilter === c.id ? '' : c.id)}
            >
              <span>{c.name}</span>
              <span className="n">{requests.filter((r) => r.community_id === c.id).length}</span>
            </button>
          ))}
        </div>
      </aside>

      <section className="workpane">
        <div className="queue-pane">
          <div className="section-head">
            <h1>Move requests</h1>
            <span className="count">{filtered.length} shown</span>
            <div className="filters">
              <input
                className="queue-search"
                placeholder="Search resident, unit, or request id"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
          </div>

          {filtered.length === 0 && <div className="empty-note">No requests match these filters.</div>}
          {filtered.map((r) => (
            <RequestCard key={r.id} request={r} linkTo={`/admin/requests/${r.id}`} />
          ))}
        </div>
      </section>
    </div>
  )
}
