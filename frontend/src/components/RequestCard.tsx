import { Link } from 'react-router-dom'
import type { MoveRequest } from '../types'
import StatusBadge from './StatusBadge'

export default function RequestCard({ request, linkTo }: {
  request: MoveRequest
  linkTo?: string
}) {
  const body = (
    <>
      <div className={`dir-badge ${request.type === 'move_in' ? 'in' : 'out'}`}>
        {request.type === 'move_in' ? '⇥' : '⇤'}
      </div>
      <div className="mid">
        <b>
          {request.type === 'move_in' ? 'Move-in' : 'Move-out'} · {request.unit_label}
        </b>
        <div className="sub">
          {request.resident_name} ({request.tenancy}) · {request.community_name} ·{' '}
          {request.requested_date} {request.time_window} ·{' '}
          <span className="mono">{request.id}</span>
        </div>
      </div>
      <StatusBadge status={request.status} />
    </>
  )

  return linkTo ? (
    <Link className="request-card" to={linkTo}>
      {body}
    </Link>
  ) : (
    <div className="request-card">{body}</div>
  )
}
