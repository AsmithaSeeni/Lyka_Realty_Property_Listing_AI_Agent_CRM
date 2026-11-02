import React from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth, hasPerm } from './AuthContext.jsx'

/* ------------------------------------------------------------------ */
/* ProtectedRoute (Phase 4 / Stage 6K.4) — enterprise navigation guard.*/
/*                                                                     */
/* It redirects unauthenticated users to /login (preserving ?next=)   */
/* and renders an access-denied view when role or permission          */
/* requirements are not met. THIS IS UX ONLY: the backend re-checks   */
/* authorisation on every request (defence in depth).                 */
/* ------------------------------------------------------------------ */

export function ProtectedRoute({
  children,
  requirePermission = null,
  requireAnyPermission = null,
  requireRoles = null,
  requireStaff = true,
}) {
  const { session, status, isAuthenticated, isStaff, permissions, roles } = useAuth()
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
    // Preserve requested path so login portal can return the user here.
    const next = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?next=${next}`} replace />
  }

  // A staff-only area must not admit a customer session.
  if (requireStaff && !isStaff) {
    return <AccessDenied reason="This workspace is restricted to authorized Lyka Realty staff." />
  }

  // Role gate (if specific roles are required)
  if (requireRoles && requireRoles.length > 0) {
    const userRoleKeys = (roles || []).map((r) => r.key)
    if (session?.identity?.role) userRoleKeys.push(session.identity.role)
    const hasAllowedRole = requireRoles.some((rk) => userRoleKeys.includes(rk))
    if (!hasAllowedRole) {
      return (
        <AccessDenied
          reason="Your account role does not have authorization to access this administration section."
        />
      )
    }
  }

  // Single permission gate
  if (requirePermission && !hasPerm({ permissions }, requirePermission)) {
    return <AccessDenied reason="You do not possess the required permission to access this page." />
  }

  // Any-permission gate
  if (requireAnyPermission && requireAnyPermission.length > 0) {
    const hasAny = requireAnyPermission.some((p) => hasPerm({ permissions }, p))
    if (!hasAny) {
      // Check if user has admin/superadmin bypass
      const userRoleKeys = (roles || []).map((r) => r.key)
      if (session?.identity?.role) userRoleKeys.push(session.identity.role)
      const isAdmin = userRoleKeys.includes('admin') || userRoleKeys.includes('superadmin')
      if (!isAdmin) {
        return <AccessDenied reason="You do not possess the required permissions to access this workspace." />
      }
    }
  }

  return children
}

/* Access-denied view shown for forbidden routes / insufficient permission. */
export function AccessDenied({ reason = 'You do not have permission to view this page.' }) {
  return (
    <div className="denied" style={{ display: 'grid', placeItems: 'center', minHeight: '60vh', padding: 24 }}>
      <div className="denied__card" style={{ maxWidth: 480, textAlign: 'center', background: '#fff', borderRadius: 16, padding: '36px 32px', boxShadow: '0 10px 30px rgba(0,0,0,0.08)' }}>
        <div className="denied__icon" aria-hidden style={{ fontSize: 44, marginBottom: 12 }}>🔒</div>
        <h1 style={{ fontSize: 22, fontWeight: 800, color: '#1e293b', margin: '0 0 10px' }}>Access Denied</h1>
        <p style={{ fontSize: 14, color: '#64748b', lineHeight: 1.5, margin: '0 0 20px' }}>{reason}</p>
        <p className="denied__hint" style={{ fontSize: 12, color: '#94a3b8', margin: '0 0 24px' }}>
          If you require access to this workspace or administrative feature, please contact your System Administrator.
        </p>
        <div style={{ display: 'flex', gap: 12, justifyContent: 'center' }}>
          <a className="btn" href="/agent/dashboard" style={{ textDecoration: 'none', padding: '9px 18px', borderRadius: 8, background: '#2c0f20', color: '#fff', fontSize: 13, fontWeight: 600 }}>
            Return to Dashboard
          </a>
        </div>
      </div>
    </div>
  )
}
