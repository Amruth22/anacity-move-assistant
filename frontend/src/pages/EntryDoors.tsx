import { useNavigate } from 'react-router-dom'
import { usePersona } from '../context/persona'

/** The front door: the whole viewport split into the two sides of the product.
 *  Residents go left to pick their community; the admin door goes straight in. */
export default function EntryDoors() {
  const navigate = useNavigate()
  const { setPersona } = usePersona()

  const enterAdmin = () => {
    setPersona({ kind: 'admin' })
    navigate('/admin')
  }

  return (
    <div className="doors">
      <button className="door door-res" onClick={() => navigate('/residents')}>
        <span className="door-kicker">ANACITY · Move Assistant</span>
        <span className="door-arrow" aria-hidden>
          →
        </span>
        <span className="door-title">
          I live
          <br />
          here.
        </span>
        <span className="door-sub">
          Plan a move-in or move-out with an assistant that already knows your community's rules,
          then follow your request after you file it.
        </span>
      </button>

      <span className="door-seam" aria-hidden />

      <button className="door door-adm" onClick={enterAdmin}>
        <span className="door-arrow" aria-hidden>
          →
        </span>
        <span className="door-title">
          I run
          <br />
          the desk.
        </span>
        <span className="door-sub">
          Review every request with a copilot that checks the policy, flags the risks, and drafts
          the reply. You decide.
        </span>
      </button>
    </div>
  )
}
