import React, { useState, useEffect } from 'react'
import { Outlet, Link, useSearchParams } from 'react-router-dom'
import { useAgent } from '../agent/AgentAuth.jsx'
import { useAuth } from '../auth/AuthContext.jsx'
import api from '../api.js'
import MustChangePasswordModal from '../components/MustChangePasswordModal.jsx'

const HR_NAV = [
  { tab: 'overview', icon: '📊', label: 'HR Dashboard' },
  { tab: 'employees', icon: '👥', label: 'Employee Directory' },
  { tab: 'onboarding', icon: '➕', label: 'Onboarding' },
  { tab: 'attendance', icon: '🕒', label: 'Daily Attendance' },
  { tab: 'leaves', icon: '🌴', label: 'Leave Requests' },
  { tab: 'shifts', icon: '⏱️', label: 'Shifts & Holidays' },
  { tab: 'documents', icon: '📁', label: 'Employee Documents' },
  { tab: 'reports', icon: '📈', label: 'HR Reports' },
  { tab: 'offboarding', icon: '🚪', label: 'Offboarding' },
]

export default function HrShell() {
  const { agent, logout } = useAgent()
  const { roles } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const activeTab = searchParams.get('tab') || 'overview'

  const [mobileOpen, setMobileOpen] = useState(false)
  const [currentAgent, setCurrentAgent] = useState(agent)

  useEffect(() => {
    setCurrentAgent(agent)
  }, [agent])

  const refreshAgent = async () => {
    try {
      const res = await api.me()
      if (res?.agent) {
        setCurrentAgent(res.agent)
      }
    } catch {}
  }

  const canReturnToCrmAdmin =
    currentAgent?.role === 'admin' ||
    currentAgent?.role === 'superadmin' ||
    (roles && roles.some((r) => r.key === 'admin' || r.key === 'superadmin'))

  const roleLabel =
    roles && roles.length
      ? roles.map((r) => r.display_name).join(' · ')
      : currentAgent?.role === 'admin'
        ? 'System Administrator (HR Oversight)'
        : 'HR Specialist'

  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: '#f8fafc', color: '#1e293b', fontFamily: 'var(--sans, system-ui, sans-serif)' }}>
      {/* Mandatory Password Change Policy Modal */}
      <MustChangePasswordModal agent={currentAgent} onPasswordChanged={refreshAgent} />

      {/* Mobile Drawer Backdrop */}
      {mobileOpen && (
        <div
          onClick={() => setMobileOpen(false)}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.5)',
            zIndex: 40,
          }}
        />
      )}

      {/* HRMS Dedicated Luxury Sidebar */}
      <aside
        style={{
          width: 270,
          height: '100vh',
          maxHeight: '100vh',
          position: 'sticky',
          top: 0,
          background: 'linear-gradient(180deg, #064e3b 0%, #022c22 100%)',
          color: '#ecfdf5',
          display: 'flex',
          flexDirection: 'column',
          borderRight: '1px solid rgba(255,255,255,0.08)',
          boxShadow: '4px 0 24px rgba(0,0,0,0.15)',
          zIndex: 50,
          flexShrink: 0,
          overflow: 'hidden',
          boxSizing: 'border-box',
        }}
      >
        {/* Brand Header */}
        <div style={{ padding: '18px 16px', borderBottom: '1px solid rgba(255,255,255,0.1)', display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
          <div
            style={{
              width: 36,
              height: 36,
              borderRadius: 9,
              background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 18,
              boxShadow: '0 4px 12px rgba(16, 185, 129, 0.3)',
              flexShrink: 0,
            }}
          >
            👥
          </div>
          <div>
            <div style={{ fontWeight: 800, fontSize: 15, letterSpacing: '-0.02em', color: '#fff' }}>
              Lyka HRMS
            </div>
            <div style={{ fontSize: 10.5, color: '#a7f3d0', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>
              Workforce &amp; Personnel
            </div>
          </div>
        </div>

        {/* Scrollable Navigation Links */}
        <nav
          style={{
            padding: '12px 10px',
            flex: 1,
            minHeight: 0,
            overflowY: 'auto',
            overflowX: 'hidden',
          }}
        >
          <div style={{ fontSize: 10, fontWeight: 700, color: '#6ee7b7', textTransform: 'uppercase', letterSpacing: '0.1em', padding: '0 10px 8px' }}>
            HR Operational Modules
          </div>
          {HR_NAV.map((n) => {
            const isActive = activeTab === n.tab
            return (
              <Link
                key={n.tab}
                to={`/hr?tab=${n.tab}`}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '9px 12px',
                  borderRadius: 8,
                  fontSize: 13,
                  fontWeight: 600,
                  color: isActive ? '#fff' : '#d1fae5',
                  background: isActive ? 'rgba(16, 185, 129, 0.28)' : 'transparent',
                  textDecoration: 'none',
                  marginBottom: 3,
                  borderLeft: isActive ? '4px solid #10b981' : '4px solid transparent',
                  transition: 'all 0.15s ease',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                <span style={{ fontSize: 15, width: 20, textAlign: 'center', flexShrink: 0 }}>{n.icon}</span>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{n.label}</span>
              </Link>
            )
          })}
        </nav>

        {/* System Administrator Switcher (Return to CRM) */}
        {canReturnToCrmAdmin && (
          <div style={{ padding: '8px 12px 10px', flexShrink: 0, borderTop: '1px solid rgba(255,255,255,0.08)' }}>
            <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#fbbf24', padding: '0 4px 6px' }}>
              Workspace Switcher
            </div>
            <Link
              to="/agent/dashboard"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '8px 10px',
                borderRadius: 9,
                background: 'rgba(251, 191, 36, 0.12)',
                border: '1px solid rgba(251, 191, 36, 0.3)',
                color: '#fbbf24',
                textDecoration: 'none',
                transition: 'all 0.15s ease',
              }}
              title="Return to CRM Administration"
              aria-label="Return to CRM Administration - Real-Estate Sales & IT Governance"
            >
              <span
                style={{
                  width: 28,
                  height: 28,
                  borderRadius: 7,
                  background: 'rgba(251, 191, 36, 0.22)',
                  display: 'grid',
                  placeItems: 'center',
                  fontSize: 15,
                  flexShrink: 0,
                }}
                aria-hidden="true"
              >
                🏢
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <b style={{ display: 'block', fontSize: 12, fontWeight: 700, color: '#fef3c7', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  Return to CRM
                </b>
                <span style={{ display: 'block', fontSize: 10, color: '#fbbf24', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  Sales Operations &amp; IT
                </span>
              </div>
              <span style={{ fontSize: 13, fontWeight: 700, color: '#fbbf24', flexShrink: 0 }} aria-hidden="true">
                ↖
              </span>
            </Link>
          </div>
        )}

        {/* User Profile & Sign Out */}
        <div style={{ padding: 16, borderTop: '1px solid rgba(255,255,255,0.1)', background: 'rgba(0,0,0,0.2)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: '50%',
                background: '#10b981',
                color: '#fff',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontWeight: 700,
                fontSize: 14,
              }}
            >
              {(currentAgent?.full_name || 'H').slice(0, 1).toUpperCase()}
            </div>
            <div style={{ overflow: 'hidden' }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: '#fff', whiteSpace: 'nowrap', textOverflow: 'ellipsis', overflow: 'hidden' }}>
                {currentAgent?.full_name || 'HR Staff'}
              </div>
              <div style={{ fontSize: 11, color: '#a7f3d0' }}>{roleLabel}</div>
            </div>
          </div>
          <button
            onClick={logout}
            style={{
              width: '100%',
              padding: '8px 12px',
              borderRadius: 6,
              background: 'rgba(239, 68, 68, 0.2)',
              border: '1px solid rgba(239, 68, 68, 0.4)',
              color: '#fca5a5',
              fontSize: 12,
              fontWeight: 600,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 6,
            }}
          >
            <span>⇄</span> Sign Out of HRMS
          </button>
        </div>
      </aside>

      {/* Main HR Canvas */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflow: 'auto' }}>
        <header
          style={{
            height: 60,
            background: '#ffffff',
            borderBottom: '1px solid #e2e8f0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0 32px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span
              style={{
                background: '#ecfdf5',
                color: '#065f46',
                border: '1px solid #a7f3d0',
                padding: '4px 10px',
                borderRadius: 20,
                fontSize: 12,
                fontWeight: 700,
                letterSpacing: '0.04em',
              }}
            >
              ● HRMS WORKSPACE · DUBAI HEADQUARTERS
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <span style={{ fontSize: 13, color: '#64748b' }}>
              UAE Real Estate Personnel &amp; Attendance Operations
            </span>
          </div>
        </header>

        <main style={{ flex: 1, overflow: 'auto' }}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
