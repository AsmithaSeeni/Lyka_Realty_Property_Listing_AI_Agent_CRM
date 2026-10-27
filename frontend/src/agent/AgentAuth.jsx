import React from 'react'
import { Navigate, Outlet } from 'react-router-dom'
import api from '../api.js'

/* ------------------------------------------------------------------ */
/* Agent auth context                                                  */
/* ------------------------------------------------------------------ */
export const AgentContext = React.createContext(null)
export const useAgent = () => React.useContext(AgentContext)

/* ------------------------------------------------------------------ */
/* Route guard: /agent/* requires a valid backend session.             */
/* Validates with GET /api/auth/me (server-side truth), redirects      */
/* unauthenticated users to /agent/login.                              */
/* ------------------------------------------------------------------ */
export function RequireAgent() {
  const [status, setStatus] = React.useState('loading') // loading | ok | fail
  const [agent, setAgent] = React.useState(null)

  React.useEffect(() => {
    let alive = true
    api
      .me()
      .then((r) => {
        if (!alive) return
        setAgent(r.agent)
        setStatus('ok')
      })
      .catch(() => {
        if (!alive) return
        setStatus('fail')
      })
    return () => {
      alive = false
    }
  }, [])

  if (status === 'loading') {
    return (
      <div className="ax-boot">
        <div className="ax-boot__spin" />
        <p>Verifying your session…</p>
      </div>
    )
  }

  if (status === 'fail') {
    // Frontend convenience redirect — the backend still rejects every
    // request independently (defence in depth).
    return <Navigate to="/agent/login" replace />
  }

  const logout = async () => {
    try {
      await api.logout()
    } catch {
      /* ignore — session may already be gone */
    }
    setAgent(null)
    window.location.assign('/agent/login')
  }

  return (
    <AgentContext.Provider value={{ agent, logout }}>
      <Outlet />
    </AgentContext.Provider>
  )
}
