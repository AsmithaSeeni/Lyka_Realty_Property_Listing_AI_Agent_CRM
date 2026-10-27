import React from 'react'
import api from '../api.js'

/* ------------------------------------------------------------------ */
/* Central authentication context (Phase 3).                           */
/*                                                                     */
/* Single source of truth for "who am I?" across the whole app. It     */
/* resolves the session once via GET /api/auth/session (staff OR       */
/* customer) and exposes identity, roles, permissions and the          */
/* post-login landing route.                                           */
/*                                                                     */
/* SECURITY: roles/permissions here are REFERENCE ONLY, for rendering  */
/* (which nav items to show). Every authorization decision is made     */
/* server-side on each request — the backend never trusts this state.  */
/* Nothing sensitive is stored in localStorage; the httpOnly cookie    */
/* is the only credential.                                             */
/* ------------------------------------------------------------------ */

export const AuthContext = React.createContext(null)

export function useAuth() {
  return React.useContext(AuthContext)
}

/* Helper: does the session hold a permission? (render-time only) */
export function hasPerm(session, perm) {
  return Boolean(session && session.permissions && session.permissions.includes(perm))
}

/* Helper: does the session hold ANY of the listed roles? */
export function hasRole(session, ...roleKeys) {
  if (!session || !session.roles) return false
  const keys = session.roles.map((r) => r.key)
  return roleKeys.some((k) => keys.includes(k))
}

export function AuthProvider({ children }) {
  const [session, setSession] = React.useState(null) // null = loading
  const [status, setStatus] = React.useState('loading') // loading | ready | error

  const load = React.useCallback(() => {
    setStatus('loading')
    return api
      .session()
      .then((s) => {
        setSession(s)
        setStatus('ready')
        return s
      })
      .catch(() => {
        // Network/backend down: treat as anonymous so the portal still renders.
        setSession({ authenticated: false, kind: null })
        setStatus('ready')
      })
  }, [])

  React.useEffect(() => {
    let alive = true
    api
      .session()
      .then((s) => {
        if (!alive) return
        setSession(s)
        setStatus('ready')
      })
      .catch(() => {
        if (!alive) return
        setSession({ authenticated: false, kind: null })
        setStatus('ready')
      })
    // Re-broadcast hook: other surfaces can dispatch 'lyka:auth' to refresh.
    const onAuth = () => load()
    window.addEventListener('lyka:auth', onAuth)
    return () => {
      alive = false
      window.removeEventListener('lyka:auth', onAuth)
    }
  }, [load])

  /* Sign in through the unified portal endpoint. Returns the session so the
     caller can navigate to session.landing. Throws on failure (401 etc.). */
  const login = React.useCallback(async (identifier, password) => {
    const result = await api.portalLogin(identifier, password)
    // Refresh the canonical session from the backend (cookie is now set).
    const fresh = await api.session().catch(() => result)
    setSession(fresh)
    setStatus('ready')
    return fresh
  }, [])

  /* Sign out whichever identity is active. */
  const logout = React.useCallback(async () => {
    try {
      if (session && session.kind === 'staff') {
        await api.logout()
      } else if (session && session.kind === 'customer') {
        await api.customerLogout()
      } else {
        // Unknown/anonymous: try staff logout (idempotent) then customer.
        await api.logout().catch(() => {})
        await api.customerLogout().catch(() => {})
      }
    } catch {
      /* ignore — session may already be gone */
    }
    setSession({ authenticated: false, kind: null })
    window.dispatchEvent(new Event('lyka:customer'))
  }, [session])

  const value = React.useMemo(
    () => ({
      session,
      status,
      isAuthenticated: Boolean(session && session.authenticated),
      isStaff: Boolean(session && session.authenticated && session.kind === 'staff'),
      isCustomer: Boolean(session && session.authenticated && session.kind === 'customer'),
      roles: (session && session.roles) || [],
      permissions: (session && session.permissions) || [],
      landing: (session && session.landing) || '/',
      login,
      logout,
      refresh: load,
    }),
    [session, status, login, logout, load],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
