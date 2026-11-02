import React, { useState, useEffect } from 'react'
import { NavLink, useLocation, Outlet } from 'react-router-dom'
import { useAgent } from './AgentAuth.jsx'
import { useAuth, hasPerm } from '../auth/AuthContext.jsx'
import api from '../api.js'
import MustChangePasswordModal from '../components/MustChangePasswordModal.jsx'
import AgentLeaveModal from '../components/AgentLeaveModal.jsx'

/* Navigation is filtered by PERMISSIONS (render-time UX only — the backend
   re-checks on every request). A user only sees the sections their roles
   actually unlock. */
const NAV = [
  { to: '/agent/dashboard', icon: '▦', label: 'Dashboard', perm: 'leads.read_assigned' },
  { to: '/agent/leads', icon: '◉', label: 'Leads', perm: 'leads.read_assigned' },
  { to: '/agent/appointments', icon: '📅', label: 'Appointments', perm: 'appointments.read' },
  { to: '/agent/deals', icon: '🤝', label: 'Deals & Offers', perm: 'deals.read' },
  { to: '/agent/properties', icon: '🏢', label: 'Properties', perm: 'properties.read' },
  { to: '/agent/conversations', icon: '💬', label: 'Conversations', perm: 'conversations.read_authorized' },
  { to: '/agent/management', icon: '👥', label: 'Agent Management', perm: 'users.read', adminOnly: true },
  { to: '/agent/workforce', icon: '🏛️', label: 'Workforce & HR Oversight', perm: 'users.read', adminOnly: true },
  { to: '/agent/users', icon: '🔐', label: 'User & Role Administration', perm: 'users.read', adminOnly: true },
  { to: '/agent/audit', icon: '📜', label: 'Audit Logs', perm: 'users.read', adminOnly: true },
]

const TITLES = [
  { match: '/agent/dashboard', title: 'Dashboard', sub: 'Pipeline overview', section: 'Overview' },
  { match: '/agent/leads/new', title: 'New lead', sub: 'Review extracted details, confirm & save', section: 'Leads' },
  { match: '/agent/leads/', title: 'Lead detail', sub: 'Customer profile & AI conversation', section: 'Leads' },
  { match: '/agent/leads', title: 'Leads', sub: 'All leads in your scope', section: 'Leads' },
  { match: '/agent/appointments', title: 'Appointments & Viewings', sub: 'Schedule property viewings, track conflicts & record customer feedback', section: 'Operations' },
  { match: '/agent/deals', title: 'Deals, Offers & Negotiations', sub: 'Offers, counteroffers, UAE compliance checklist & closed transactions', section: 'Transactions' },
  { match: '/agent/properties', title: 'Property Inventory', sub: 'Search, publish & manage UAE real-estate listings', section: 'Inventory' },
  { match: '/agent/conversations', title: 'Conversations', sub: 'Customer ↔ LykAI threads', section: 'Concierge' },
  { match: '/agent/management', title: 'Sales-Agent Management', sub: 'Sales workforce, workloads & team distribution', section: 'Sales Operations' },
  { match: '/agent/workforce', title: 'Workforce & HR Oversight', sub: 'Enterprise headcount, daily attendance summary & HR governance', section: 'Administration' },
  { match: '/agent/users', title: 'User & Role Administration', sub: 'Account provisioning, credential security & access controls', section: 'Administration' },
  { match: '/agent/audit', title: 'System Audit Trail', sub: 'Immutable log of administrative, auth & HR operations', section: 'Administration' },
  { match: '/hr', title: 'HR & Personnel Management', sub: 'Employee master, attendance control & leave governance', section: 'Human Resources' },
]

/**
 * Enterprise Agent Application Shell:
 * - Luxury deep imperial plum sidebar with brushed gold accents
 * - Responsive mobile drawer toggle
 * - Breadcrumbs & live operational indicators
 * - Elevated sticky topbar
 */
export default function AgentShell() {
  const { agent, logout } = useAgent()
  const { roles, permissions } = useAuth()
  const location = useLocation()
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [currentAgent, setCurrentAgent] = useState(agent)
  const [leaveModalOpen, setLeaveModalOpen] = useState(false)

  useEffect(() => {
    setCurrentAgent(agent)
  }, [agent])

  const refreshAgent = async () => {
    try {
      const res = await api.me()
      if (res?.agent) setCurrentAgent(res.agent)
    } catch {}
  }

  // Close mobile nav on route change
  useEffect(() => {
    setMobileNavOpen(false)
  }, [location.pathname])

  // Quick attendance state for staff in sidebar
  const [todayAtt, setTodayAtt] = useState(null)
  const [attBusy, setAttBusy] = useState(false)

  const loadTodayAtt = () => {
    api.agentAttendanceToday()
      .then((data) => setTodayAtt(data))
      .catch(() => setTodayAtt(null))
  }

  useEffect(() => {
    loadTodayAtt()
  }, [])

  const handleSidebarCheckIn = async () => {
    setAttBusy(true)
    try {
      await api.agentCheckIn({ work_mode: 'OFFICE' })
      loadTodayAtt()
    } catch (e) {
      alert(e.message || 'Check-in failed')
    } finally {
      setAttBusy(false)
    }
  }

  const handleSidebarCheckOut = async () => {
    setAttBusy(true)
    try {
      await api.agentCheckOut()
      loadTodayAtt()
    } catch (e) {
      alert(e.message || 'Check-out failed')
    } finally {
      setAttBusy(false)
    }
  }

  const heading = TITLES.find((t) => location.pathname.startsWith(t.match)) || TITLES[0]

  // Only render nav items whose permission the session actually holds.
  const isSysAdmin =
    currentAgent?.role === 'admin' ||
    currentAgent?.role === 'superadmin' ||
    (roles && roles.some((r) => r.key === 'admin' || r.key === 'superadmin'))

  const canAccessHrms =
    isSysAdmin ||
    hasPerm({ permissions }, 'hr_reports.view') ||
    hasPerm({ permissions }, 'attendance.view') ||
    hasPerm({ permissions }, 'employees.view')

  const visibleNav = NAV.filter((n) => {
    if (n.adminOnly && !isSysAdmin) return false
    return !n.perm || hasPerm({ permissions }, n.perm) || isSysAdmin
  })

  const salesNav = visibleNav.filter((n) => !['/agent/workforce', '/agent/users', '/agent/audit'].includes(n.to))
  const adminNav = visibleNav.filter((n) => ['/agent/workforce', '/agent/users', '/agent/audit'].includes(n.to))

  // Human-readable role label(s) from the resolved session roles.
  const roleLabel =
    roles && roles.length
      ? roles.map((r) => r.display_name).join(' · ')
      : agent?.role === 'admin'
        ? 'Administrator'
        : 'Sales agent'

  return (
    <div className="ax">
      {/* Mandatory Password Change Policy Modal */}
      <MustChangePasswordModal agent={currentAgent} onPasswordChanged={refreshAgent} />

      {/* Self-Service Leave Modal */}
      <AgentLeaveModal isOpen={leaveModalOpen} onClose={() => setLeaveModalOpen(false)} />

      {/* ---------- Mobile Backdrop ---------- */}
      {mobileNavOpen && (
        <div
          className="ax-backdrop"
          onClick={() => setMobileNavOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* ---------- Sidebar ---------- */}
      <aside className={`ax-side ${mobileNavOpen ? 'open' : ''}`}>
        <div className="ax-brand">
          <img
            src="/lyka_logo.png"
            alt="Lyka Realty"
            className="ax-brand__logo"
            onError={(e) => { e.currentTarget.style.display = 'none' }}
          />
          <div>
            <b>Lyka Realty</b>
            <span>CRM Operations</span>
          </div>
          {/* Close button on mobile */}
          <button
            type="button"
            className="ax-side__close"
            onClick={() => setMobileNavOpen(false)}
            aria-label="Close navigation"
          >
            ✕
          </button>
        </div>

        <nav className="ax-nav" aria-label="CRM Navigation">
          <div className="ax-nav__section-label">Sales Operations</div>
          {salesNav.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) => `ax-nav__item${isActive ? ' on' : ''}`}
            >
              <i>{n.icon}</i>
              <span>{n.label}</span>
            </NavLink>
          ))}

          {isSysAdmin && adminNav.length > 0 && (
            <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid rgba(255,255,255,0.08)' }}>
              <div className="ax-nav__section-label admin">System Administration</div>
              {adminNav.map((n) => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  className={({ isActive }) => `ax-nav__item${isActive ? ' on' : ''}`}
                >
                  <i>{n.icon}</i>
                  <span>{n.label}</span>
                </NavLink>
              ))}
            </div>
          )}
        </nav>

        {/* ---------- Dedicated Workspace Switcher Section ---------- */}
        {canAccessHrms && (
          <div className="ax-workspace-switcher">
            <div className="ax-workspace-switcher__label">Workspace Switcher</div>
            <NavLink
              to="/hr"
              className="ax-workspace-card"
              title="Open HRMS Workspace"
              aria-label="Open HRMS Workspace - Human Resources & Workforce"
            >
              <span className="ax-workspace-card__icon" aria-hidden="true">🏛️</span>
              <div className="ax-workspace-card__meta">
                <b>Open HRMS Workspace</b>
                <span>Human Resources &amp; Workforce</span>
              </div>
              <span className="ax-workspace-card__arrow" aria-hidden="true">↗</span>
            </NavLink>
          </div>
        )}

        <div className="ax-side__foot">
          {/* Quick Attendance Widget */}
          <div className="ax-att-card">
            <div className="ax-att-card__top">
              <span className="ax-att-card__title">
                Dubai Attendance
              </span>
              <span className={`ax-att-card__badge ${todayAtt?.attendance?.status === 'Present' ? 'present' : todayAtt?.attendance?.status === 'Late' ? 'late' : 'off'}`}>
                {todayAtt?.attendance?.status || (todayAtt?.checked_in ? 'Clocked In' : 'Not Marked')}
              </span>
            </div>
            {todayAtt?.checked_in ? (
              <div className="ax-att-card__action">
                <span className="ax-att-card__time">
                  In: {todayAtt.attendance?.check_in_time ? new Date(todayAtt.attendance.check_in_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Today'}
                </span>
                <button
                  type="button"
                  disabled={attBusy || todayAtt?.attendance?.check_out_time != null}
                  onClick={handleSidebarCheckOut}
                  className={`ax-att-card__btn ${todayAtt?.attendance?.check_out_time ? 'done' : 'out'}`}
                >
                  {todayAtt?.attendance?.check_out_time ? 'Completed' : 'Check Out'}
                </button>
              </div>
            ) : (
              <div className="ax-att-card__action">
                <span className="ax-att-card__time">Ready to shift?</span>
                <button
                  type="button"
                  disabled={attBusy}
                  onClick={handleSidebarCheckIn}
                  className="ax-att-card__btn in"
                >
                  Check In
                </button>
              </div>
            )}
            <div className="ax-att-card__foot">
              <span style={{ fontSize: 11, color: '#9ca3af' }}>Leave Portal</span>
              <button
                type="button"
                onClick={() => setLeaveModalOpen(true)}
                className="ax-att-card__leave-btn"
              >
                🌴 My Leaves
              </button>
            </div>
          </div>

          <div className="ax-me">
            <div className="ax-me__avatar">
              {(agent?.full_name || 'A').slice(0, 1).toUpperCase()}
            </div>
            <div className="ax-me__meta">
              <b>{agent?.full_name || 'Staff User'}</b>
              <span>{roleLabel}</span>
              <span className="ax-me__email">{agent?.email}</span>
            </div>
          </div>
          <button className="ax-logout" onClick={logout} title="Sign out of CRM">
            <span>⇄</span>
            <span>Sign Out</span>
          </button>
        </div>
      </aside>

      {/* ---------- Main Content Area ---------- */}
      <div className="ax-main">
        <header className="ax-top">
          <div className="ax-top__left">
            {/* Hamburger button for mobile */}
            <button
              type="button"
              className="ax-menu-btn"
              onClick={() => setMobileNavOpen(true)}
              aria-label="Open navigation menu"
            >
              ☰
            </button>

            <div>
              {/* Breadcrumb trace */}
              <div className="ax-breadcrumbs">
                <span>Lyka CRM</span>
                <span className="ax-breadcrumbs__sep">/</span>
                <span>{heading.section || 'Overview'}</span>
                <span className="ax-breadcrumbs__sep">/</span>
                <span className="ax-breadcrumbs__current">{heading.title}</span>
              </div>
              <h1 className="ax-top__title">{heading.title}</h1>
              <p className="ax-top__sub">{heading.sub}</p>
            </div>
          </div>

          <div className="ax-top__right">
            {/* Operational status badge */}
            <span className="ax-live-pill" title="System connected">
              <span className="ax-live-pill__dot" />
              CRM UAE
            </span>

            {/* Role indicator */}
            <span className="ax-chip">
              {roles && roles.length ? roles[0].display_name : agent?.role === 'admin' ? 'Admin' : 'Agent'}
            </span>

            {/* Link to public website / concierge */}
            <NavLink to="/chat" className="ax-top__link" target="_blank" rel="noopener noreferrer">
              Public Concierge ↗
            </NavLink>
          </div>
        </header>

        <main className="ax-canvas">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
