import React, { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import api from '../api.js'

export default function AdminWorkforceOversight() {
  const [stats, setStats] = useState(null)
  const [hrUsers, setHrUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadData = async () => {
    setLoading(true)
    setError('')
    try {
      const [statsRes, agentsRes] = await Promise.all([
        api.hrDashboard(),
        api.adminAgents(),
      ])
      setStats(statsRes)
      const hrs = (agentsRes.agents || []).filter(
        (a) => a.role === 'hr' || (a.email && a.email.includes('hr@'))
      )
      setHrUsers(hrs)
    } catch (err) {
      setError(err.message || 'Failed to load workforce oversight data.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  if (loading) {
    return (
      <div style={{ padding: 32, textAlign: 'center', color: '#64748b' }}>
        <div className="ax-boot__spin" style={{ margin: '0 auto 16px' }} />
        <p>Loading enterprise workforce oversight…</p>
      </div>
    )
  }

  return (
    <div className="ax-page" style={{ padding: '24px 32px' }}>
      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 24,
          flexWrap: 'wrap',
          gap: 16,
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <span
              style={{
                fontSize: 11,
                fontWeight: 700,
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                color: '#b45309',
                background: '#fef3c7',
                padding: '2px 8px',
                borderRadius: 4,
              }}
            >
              System Administration
            </span>
            <span style={{ fontSize: 13, color: '#64748b' }}>· Executive Oversight</span>
          </div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, color: '#0f172a' }}>
            Workforce &amp; HR Oversight
          </h1>
          <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: 14 }}>
            High-level executive metrics, organizational headcount, attendance summaries, and HR operational audit log.
          </p>
        </div>

        <div style={{ display: 'flex', gap: 12 }}>
          <button
            onClick={loadData}
            style={{
              padding: '8px 14px',
              borderRadius: 6,
              background: '#fff',
              border: '1px solid #cbd5e1',
              color: '#334155',
              fontSize: 13,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            ↻ Refresh Metrics
          </button>
          <Link
            to="/hr"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
              padding: '8px 18px',
              borderRadius: 6,
              background: 'linear-gradient(135deg, #064e3b 0%, #047857 100%)',
              color: '#fff',
              textDecoration: 'none',
              fontSize: 13,
              fontWeight: 700,
              boxShadow: '0 4px 6px -1px rgba(6, 78, 59, 0.25)',
            }}
          >
            <span>🏛️</span> Open Full HRMS Workspace ↗
          </Link>
        </div>
      </div>

      {error && (
        <div
          style={{
            padding: '12px 16px',
            background: '#fef2f2',
            border: '1px solid #fecaca',
            color: '#dc2626',
            borderRadius: 8,
            marginBottom: 20,
            fontSize: 13,
          }}
        >
          ⚠️ {error}
        </div>
      )}

      {/* KPI Cards */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: 16,
          marginBottom: 24,
        }}
      >
        <div className="ax-card" style={{ padding: 16, background: '#fff', borderRadius: 8, border: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>
            Total Employees
          </div>
          <div style={{ fontSize: 26, fontWeight: 700, color: '#0f172a', marginTop: 4 }}>
            {stats?.total_employees ?? '—'}
          </div>
          <div style={{ fontSize: 12, color: '#16a34a', marginTop: 4 }}>
            {stats?.active_employees ?? 0} Active records
          </div>
        </div>

        <div className="ax-card" style={{ padding: 16, background: '#fff', borderRadius: 8, border: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>
            Present Today
          </div>
          <div style={{ fontSize: 26, fontWeight: 700, color: '#059669', marginTop: 4 }}>
            {stats?.present_today ?? 0}
          </div>
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
            {stats?.late_today ?? 0} Late check-ins
          </div>
        </div>

        <div className="ax-card" style={{ padding: 16, background: '#fff', borderRadius: 8, border: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>
            Employees on Leave
          </div>
          <div style={{ fontSize: 26, fontWeight: 700, color: '#0284c7', marginTop: 4 }}>
            {stats?.on_leave_today ?? 0}
          </div>
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
            Approved leave today
          </div>
        </div>

        <div className="ax-card" style={{ padding: 16, background: '#fff', borderRadius: 8, border: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>
            Field Duty / WFH
          </div>
          <div style={{ fontSize: 26, fontWeight: 700, color: '#7c3aed', marginTop: 4 }}>
            {stats?.field_duty_today ?? 0}
          </div>
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
            Off-site active personnel
          </div>
        </div>

        <div className="ax-card" style={{ padding: 16, background: '#fff', borderRadius: 8, border: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>
            Pending Leave Requests
          </div>
          <div
            style={{
              fontSize: 26,
              fontWeight: 700,
              color: (stats?.pending_leave_requests ?? 0) > 0 ? '#ea580c' : '#0f172a',
              marginTop: 4,
            }}
          >
            {stats?.pending_leave_requests ?? 0}
          </div>
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
            Awaiting HR manager action
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, marginBottom: 24 }}>
        {/* HR User Access Status */}
        <div className="ax-card" style={{ padding: 20, background: '#fff', borderRadius: 8, border: '1px solid #e2e8f0' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: '#0f172a' }}>
              HR User Access &amp; Governance
            </h3>
            <span style={{ fontSize: 11, fontWeight: 600, color: '#64748b' }}>
              Individual Credentials
            </span>
          </div>

          <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 16px 0' }}>
            Verified accounts holding Human Resources governance roles. System Administration manages account creation, role bounds, and credential security.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {hrUsers.length === 0 ? (
              <div style={{ padding: 12, background: '#f8fafc', borderRadius: 6, fontSize: 13, color: '#64748b' }}>
                No dedicated HR accounts found.
              </div>
            ) : (
              hrUsers.map((u) => (
                <div
                  key={u.id}
                  style={{
                    padding: 12,
                    background: '#f8fafc',
                    borderRadius: 8,
                    border: '1px solid #e2e8f0',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 700, fontSize: 14, color: '#0f172a' }}>
                      {u.full_name}
                    </div>
                    <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
                      {u.email} · Username: <span style={{ fontFamily: 'monospace' }}>{u.username}</span>
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <span
                      style={{
                        fontSize: 11,
                        fontWeight: 700,
                        padding: '2px 8px',
                        borderRadius: 4,
                        background: u.is_active ? '#dcfce7' : '#fee2e2',
                        color: u.is_active ? '#166534' : '#991b1b',
                      }}
                    >
                      {u.is_active ? 'ACTIVE' : 'DEACTIVATED'}
                    </span>
                    <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>
                      Role: {u.role.toUpperCase()}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Headcount by Department */}
        <div className="ax-card" style={{ padding: 20, background: '#fff', borderRadius: 8, border: '1px solid #e2e8f0' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: '#0f172a' }}>
              Headcount by Department
            </h3>
            <span style={{ fontSize: 11, fontWeight: 600, color: '#64748b' }}>
              Active Workforce
            </span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {(stats?.departments || []).map((d) => (
              <div
                key={d.department}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '8px 12px',
                  background: '#f8fafc',
                  borderRadius: 6,
                  border: '1px solid #e2e8f0',
                }}
              >
                <span style={{ fontSize: 13, fontWeight: 600, color: '#334155' }}>
                  {d.department}
                </span>
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 700,
                    padding: '2px 8px',
                    borderRadius: 12,
                    background: '#e0f2fe',
                    color: '#0369a1',
                  }}
                >
                  {d.count} staff
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Recent HR Audit Events */}
      <div className="ax-card" style={{ padding: 20, background: '#fff', borderRadius: 8, border: '1px solid #e2e8f0' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: '#0f172a' }}>
              Recent HR Operational Audit Trail
            </h3>
            <p style={{ margin: '2px 0 0', fontSize: 13, color: '#64748b' }}>
              System audit logs for personnel lifecycle modifications, attendance overrides, and leave governance.
            </p>
          </div>
          <Link
            to="/agent/audit"
            style={{ fontSize: 12, fontWeight: 600, color: '#0284c7', textDecoration: 'none' }}
          >
            View Full System Audit Trail →
          </Link>
        </div>

        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, textAlign: 'left' }}>
            <thead>
              <tr style={{ borderBottom: '2px solid #e2e8f0', color: '#64748b' }}>
                <th style={{ padding: '8px 12px' }}>Timestamp</th>
                <th style={{ padding: '8px 12px' }}>Event</th>
                <th style={{ padding: '8px 12px' }}>Actor</th>
                <th style={{ padding: '8px 12px' }}>Subject</th>
                <th style={{ padding: '8px 12px' }}>Business Justification / Detail</th>
              </tr>
            </thead>
            <tbody>
              {(stats?.recent_activities || []).length === 0 ? (
                <tr>
                  <td colSpan={5} style={{ padding: 24, textAlign: 'center', color: '#64748b' }}>
                    No recent HR audit activity recorded.
                  </td>
                </tr>
              ) : (
                stats.recent_activities.map((a) => (
                  <tr key={a.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                    <td style={{ padding: '10px 12px', whiteSpace: 'nowrap', color: '#64748b', fontSize: 12 }}>
                      {a.created_at ? new Date(a.created_at).toLocaleString() : '—'}
                    </td>
                    <td style={{ padding: '10px 12px', fontWeight: 600, color: '#0f172a' }}>
                      <span
                        style={{
                          background: '#f1f5f9',
                          padding: '2px 6px',
                          borderRadius: 4,
                          fontSize: 11,
                          fontFamily: 'monospace',
                        }}
                      >
                        {a.event}
                      </span>
                    </td>
                    <td style={{ padding: '10px 12px', color: '#334155' }}>
                      {a.actor_label || 'System'}
                    </td>
                    <td style={{ padding: '10px 12px', color: '#334155' }}>
                      {a.subject_label || '—'}
                    </td>
                    <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12 }}>
                      {a.detail || '—'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

