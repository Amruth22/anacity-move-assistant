import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { usePersona } from '../context/persona'
import type { Community, Resident } from '../types'

/** Behind the resident door: the communities with their rules on display,
 *  and the people inside them as tiles. */
export default function RoleSwitcher() {
  const [communities, setCommunities] = useState<Community[]>([])
  const [residents, setResidents] = useState<Record<string, Resident[]>>({})
  const { setPersona } = usePersona()
  const navigate = useNavigate()

  useEffect(() => {
    api.communities().then(async (cs) => {
      setCommunities(cs)
      const byCommunity: Record<string, Resident[]> = {}
      for (const c of cs) byCommunity[c.id] = await api.residents(c.id)
      setResidents(byCommunity)
    })
  }, [])

  const pickResident = (r: Resident, communityName: string) => {
    setPersona({ kind: 'resident', resident: r, communityName })
    navigate('/resident')
  }

  const initials = (name: string) =>
    name.split(' ').map((p) => p[0]).slice(0, 2).join('')

  return (
    <>
      <div className="back-row">
        <Link to="/">← Not a resident?</Link>
      </div>

      <section className="switch-head">
        <h1>Step into your community</h1>
        <p>Different communities keep very different rulebooks. The assistant follows whichever one is yours.</p>
      </section>

      <div className="wings">
        {communities.map((c) => {
          const strict = c.policies.move_in.notice_days >= 5
          return (
            <div className={`wing ${strict ? 'strict' : 'easy'}`} key={c.id}>
              <div className="wing-head">
                <div className="wing-kicker">{strict ? 'Strict rulebook' : 'Relaxed rulebook'}</div>
                <h2>{c.name}</h2>
                <div className="profile">{c.profile}</div>
                <div className="wing-chips">
                  <span>{c.policies.move_in.notice_days}d notice</span>
                  <span>
                    {c.policies.move_in.hours.start}–{c.policies.move_in.hours.end}
                  </span>
                  <span>
                    {c.policies.move_in.deposit
                      ? `₹${c.policies.move_in.deposit.amount.toLocaleString('en-IN')} deposit`
                      : 'no deposit'}
                  </span>
                </div>
              </div>
              <div className="wing-body">
                {(residents[c.id] ?? []).map((r) => (
                  <button className="wing-person" key={r.id} onClick={() => pickResident(r, c.name)}>
                    <span className="avatar">{initials(r.name)}</span>
                    <span className="wp-meta">
                      <b>{r.name}</b>
                      <small>{r.unit_label}</small>
                    </span>
                    <span className="wp-role">{r.tenancy}</span>
                  </button>
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </>
  )
}
