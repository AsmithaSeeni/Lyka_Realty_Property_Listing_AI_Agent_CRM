import React, { useState, useEffect, useCallback } from 'react'
import api from '../api.js'

export default function AdminAuditLogs() {
  const [logs, setLogs] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [category, setCategory] = useState('')
  const [limit, setLimit] = useState(50)

  const loadLogs = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await api.auditLog({
        limit,
        event: category || undefined,
      })
      setLogs(res.results || [])
      setTotal(res.total || 0)
    } catch (err) {
      setError(err.message || 'Failed to load audit logs')
    } finally {
      setLoading(false)
    }
  }, [category, limit])

  useEffect(() => {
    loadLogs()
  }, [loadLogs])

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
            <span style={{ fontSize: 13, color: '#64748b' }}>· Compliance &amp; Security</span>
          </div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, color: '#0f172a' }}>
            System Audit Trail
          </h1>
          <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: 14 }}>
            Immutable forensic record of all administrative, authentication, authorization, property, and HR operational events.
          </p>
        </div>

        <button
          onClick={loadLogs}
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
          ↻ Refresh Audit Trail
        </button>
      </div>

      {error && (
        <div style={{ padding: '12px 16px', background: '#fef2f2', border: '1px solid #fecaca', color: '#dc2626', borderRadius: 8, marginBottom: 16, fontSize: 13 }}>
          ⚠️ {error}
        </div>
      )}

      {/* Filter Bar */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap', alignItems: 'center' }}>
        <select
          className="ax-input"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          style={{ minWidth: 220 }}
        >
          <option value="">All Event Categories</option>
          <option value="auth.">Authentication &amp; Security (auth.*)</option>
          <option value="user.">User Administration (user.*)</option>
          <option value="hr.">Human Resources &amp; Attendance (hr.*)</option>
          <option value="lead.">Leads &amp; Assignment (lead.*)</option>
          <option value="property.">Property Lifecycle (property.*)</option>
          <option value="deal.">Deals &amp; Compliance (deal.*)</option>
        </select>

        <select
          className="ax-input"
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
          style={{ width: 140 }}
        >
          <option value={25}>25 events</option>
          <option value={50}>50 events</option>
          <option value={100}>100 events</option>
          <option value={200}>200 events</option>
        </select>

        <span style={{ fontSize: 13, color: '#64748b', marginLeft: 'auto' }}>
          Showing {logs.length} of {total} recorded events
        </span>
      </div>

      {/* Audit Log Table */}
      <div className="ax-card" style={{ background: '#fff', borderRadius: 8, border: '1px solid #e2e8f0', overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, textAlign: 'left' }}>
          <thead>
            <tr style={{ background: '#f8fafc', borderBottom: '1px solid #e2e8f0', color: '#64748b' }}>
              <th style={{ padding: '12px 16px' }}>Timestamp</th>
              <th style={{ padding: '12px 16px' }}>Event Key</th>
              <th style={{ padding: '12px 16px' }}>Actor</th>
              <th style={{ padding: '12px 16px' }}>Subject</th>
              <th style={{ padding: '12px 16px' }}>Channel / IP</th>
              <th style={{ padding: '12px 16px' }}>Event Payload / Detail</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} style={{ padding: 32, textAlign: 'center', color: '#64748b' }}>
                  Loading audit logs…
                </td>
              </tr>
            ) : logs.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ padding: 32, textAlign: 'center', color: '#64748b' }}>
                  No audit log entries match the selected criteria.
                </td>
              </tr>
            ) : (
              logs.map((l) => (
                <tr key={l.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '12px 16px', whiteSpace: 'nowrap', color: '#64748b', fontSize: 12 }}>
                    {l.created_at ? new Date(l.created_at).toLocaleString() : '—'}
                  </td>
                  <td style={{ padding: '12px 16px' }}>
                    <span
                      style={{
                        padding: '2px 6px',
                        borderRadius: 4,
                        fontSize: 11,
                        fontFamily: 'monospace',
                        fontWeight: 600,
                        background: l.event?.startsWith('auth.')
                          ? '#fef3c7'
                          : l.event?.startsWith('hr.')
                          ? '#dcfce7'
                          : l.event?.startsWith('user.')
                          ? '#e0f2fe'
                          : '#f1f5f9',
                        color: l.event?.startsWith('auth.')
                          ? '#92400e'
                          : l.event?.startsWith('hr.')
                          ? '#166534'
                          : l.event?.startsWith('user.')
                          ? '#0369a1'
                          : '#334155',
                      }}
                    >
                      {l.event}
                    </span>
                  </td>
                  <td style={{ padding: '12px 16px', color: '#0f172a', fontWeight: 600 }}>
                    {l.actor_label || 'System'}
                  </td>
                  <td style={{ padding: '12px 16px', color: '#334155' }}>
                    {l.subject_label || '—'}
                  </td>
                  <td style={{ padding: '12px 16px', color: '#64748b', fontSize: 12 }}>
                    {l.ip_address || l.channel || 'web'}
                  </td>
                  <td style={{ padding: '12px 16px', color: '#475569', fontSize: 12 }}>
                    {l.detail || (l.changes ? JSON.stringify(l.changes) : '—')}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

