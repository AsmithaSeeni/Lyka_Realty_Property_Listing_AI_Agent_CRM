import React from 'react'
import { NavLink, useLocation, Outlet } from 'react-router-dom'
import { useAgent } from './AgentAuth.jsx'
import { useAuth, hasPerm } from '../auth/AuthContext.jsx'

/* Navigation is filtered by PERMISSIONS (render-time UX only — the backend
   re-checks on every request). A user only sees the sections their roles
   actually unlock. */
const NAV = [
  { to: '/agent/dashboard', icon: '▦', label: 'Dashboard', perm: 'leads.read_assigned' },
  { to: '/agent/leads', icon: '◉', label: 'Leads', perm: 'leads.read_assigned' },
  { to: '/agent/conversations', icon: '💬', label: 'Conversations', perm: 'conversations.read_authorized' },
]

const TITLES = [
  { match: '/agent/dashboard', title: 'Dashboard', sub: 'Pipeline overview' },
  { match: '/agent/leads/new', title: 'New lead', sub: 'Review extracted details, confirm & save' },
  { match: '/agent/leads/', title: 'Lead detail', sub: 'Customer profile & AI conversation' },
  { match: '/agent/leads', title: 'Leads', sub: 'All leads in your scope' },
  { match: '/agent/conversations', title: 'Conversations', sub: 'Customer ↔ LykAI threads' },
]

/**
 * Internal agent application shell: fixed dark sidebar + topbar.
 * Visually distinct from the public marketing/chat interface — this is the
 * company's back-office tool, not part of the customer experience.
 */
export default function AgentShell() {
  const { agent, logout } = useAgent()
  const { roles, permissions } = useAuth()
  const location = useLocation()

  const heading = TITLES.find((t) => location.pathname.startsWith(t.match)) || TITLES[0]

  // Only render nav items whose permission the session actually holds.
  const visibleNav = NAV.filter((n) => !n.perm || hasPerm({ permissions }, n.perm))

  // Human-readable role label(s) from the resolved session roles.
  const roleLabel =
    roles && roles.length
      ? roles.map((r) => r.display_name).join(' · ')
      : agent?.role === 'admin'
        ? 'Administrator'
        : 'Sales agent'

  return (
    <div className="ax">
      {/* ---------- Sidebar ---------- */}
      <aside className="ax-side">
        <div className="ax-brand">
          <img src="/lyka_logo.png" alt="" className="ax-brand__logo"
            onError={(e) => { e.currentTarget.style.display = 'none' }} />
          <div>
            <b>Lyka Realty</b>
            <span>Agent CRM</span>
          </div>
        </div>

        <nav className="ax-nav">
          {visibleNav.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) => `ax-nav__item${isActive ? ' on' : ''}`}
            >
              <i>{n.icon}</i>
              {n.label}
            </NavLink>
          ))}
        </nav>

        <div className="ax-side__foot">
          <div className="ax-me">
            <div className="ax-me__avatar">{(agent?.full_name || 'A').slice(0, 1).toUpperCase()}</div>
            <div className="ax-me__meta">
              <b>{agent?.full_name}</b>
              <span>{roleLabel} · {agent?.email}</span>
            </div>
          </div>
          <button className="ax-logout" onClick={logout}>⇄ Sign out</button>
        </div>
      </aside>

      {/* ---------- Main ---------- */}
      <div className="ax-main">
        <header className="ax-top">
          <div>
            <h1>{heading.title}</h1>
            <p>{heading.sub}</p>
          </div>
          <div className="ax-top__right">
            <span className="ax-chip">
              {roles && roles.length ? roles[0].display_name : agent?.role === 'admin' ? 'Admin' : 'Agent'}
            </span>
            <NavLink to="/chat" className="ax-top__link" target="_blank">View public site ↗</NavLink>
          </div>
        </header>

        <div className="ax-canvas">
          <Outlet />
        </div>
      </div>
    </div>
  )
}
