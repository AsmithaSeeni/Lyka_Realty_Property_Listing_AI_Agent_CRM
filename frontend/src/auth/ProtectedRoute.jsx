import React from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth, hasPerm } from './AuthContext.jsx'

/* ------------------------------------------------------------------ */
/* ProtectedRoute (Phase 4) — a UX navigation guard.                   */
/*                                                                     */
/* It redirects unauthenticated users to the portal (preserving ?next=) */
/* and renders an access-denied view when a permission requirement is   */
/* not met. THIS IS UX ONLY: the backend re-checks authorisation on    */
/* every single request, so reaching a component never grants access    */
/* to its data.                                                        */
/* ------------------------------------------------------------------ */

export function ProtectedRoute({ children, requirePermission = null, requireStaff = true }) {
  // Hooks run unconditionally (Rules of Hooks) before any early return.
  const { status, isAuthenticated, isStaff, permissions } = useAuth()
  const location = useLocation()

  if (status === 'loading') {
    return (
      <div className="ax-boot">
        <div className="ax-boot__spin" />
        <p>Verifying your session…</p>
      </div>
    )
  }

  if (!isAuthenticated) {
    // Preserve the requested path so the portal can return the user here.
    const next = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?next=${next}`} replace />
  }

  // A staff-only area must not admit a customer session.
  if (requireStaff && !isStaff) {
    return <AccessDenied reason="This area is for Lyka Realty staff." />
  }

  // Permission gate (render-time; the server enforces the real check).
  if (requirePermission && !hasPerm({ permissions }, requirePermission)) {
    return <AccessDenied reason="You do not have permission to view this page." />
  }

  return children
}

/* Access-denied view shown for forbidden routes / insufficient permission. */
export function AccessDenied({ reason = 'You do not have permission to view this page.' }) {
  return (
    <div className="denied">
      <div className="denied__card">
        <div className="denied__icon" aria-hidden>🔒</div>
        <h1>Access denied</h1>
        <p>{reason}</p>
        <p className="denied__hint">
          If you believe this is a mistake, contact a Lyka Realty administrator.
        </p>
        <a className="btn" href="/">Return to home</a>
      </div>
    </div>
  )
}
