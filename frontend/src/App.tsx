import { Suspense, lazy } from 'react'
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { usePersona } from './context/persona'
import AdminDashboard from './pages/AdminDashboard'
import AdminRequestDetail from './pages/AdminRequestDetail'

// the docs page pulls in a diagram renderer, so it stays out of the main bundle
const DocsPage = lazy(() => import('./pages/DocsPage'))
import EntryDoors from './pages/EntryDoors'
import ResidentHome from './pages/ResidentHome'
import RoleSwitcher from './pages/RoleSwitcher'

export default function App() {
  const { persona, setPersona } = usePersona()
  const navigate = useNavigate()
  const { pathname } = useLocation()

  const switchOut = () => {
    setPersona(null)
    navigate('/')
  }

  // the front door owns the whole viewport - no chrome around it
  if (pathname === '/') return <EntryDoors />

  return (
    <div className="shell">
      <header className="topbar">
        <Link to="/" className="brand">
          ANACITY<span>·</span>Move Assistant
        </Link>
        <nav>
          {persona?.kind === 'resident' && <NavLink to="/resident">My community</NavLink>}
          {persona?.kind === 'admin' && <NavLink to="/admin">Requests</NavLink>}
          <NavLink to="/docs">How it works</NavLink>
        </nav>
        <div className="who">
          {persona?.kind === 'resident' && (
            <>
              <span>
                <b>{persona.resident.name}</b> · {persona.communityName}
              </span>
              <button onClick={switchOut}>Switch</button>
            </>
          )}
          {persona?.kind === 'admin' && (
            <>
              <span>
                <b>Community Admin</b>
              </span>
              <button onClick={switchOut}>Switch</button>
            </>
          )}
        </div>
      </header>

      <main className={pathname === '/resident' || pathname.startsWith('/admin') ? 'main flush' : 'main'}>
        <Routes>
          <Route path="/residents" element={<RoleSwitcher />} />
          <Route
            path="/resident"
            element={persona?.kind === 'resident' ? <ResidentHome /> : <Navigate to="/" />}
          />
          <Route
            path="/admin"
            element={persona?.kind === 'admin' ? <AdminDashboard /> : <Navigate to="/" />}
          />
          <Route
            path="/admin/requests/:id"
            element={persona?.kind === 'admin' ? <AdminRequestDetail /> : <Navigate to="/" />}
          />
          <Route
            path="/docs"
            element={
              <Suspense fallback={<div className="docs-body">Loading…</div>}>
                <DocsPage />
              </Suspense>
            }
          />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </main>
    </div>
  )
}
