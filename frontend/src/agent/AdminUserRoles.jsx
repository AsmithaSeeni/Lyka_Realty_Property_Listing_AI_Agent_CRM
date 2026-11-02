import React, { useState, useEffect, useCallback } from 'react'
import api from '../api.js'

export default function AdminUserRoles() {
  const [agents, setAgents] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState('')

  // Create modal
  const [showCreate, setShowCreate] = useState(false)
  const [createForm, setCreateForm] = useState({
    full_name: '',
    email: '',
    username: '',
    password: '',
    role: 'agent',
  })
  const [createBusy, setCreateBusy] = useState(false)

  // Reset password modal
  const [resetTarget, setResetTarget] = useState(null)
  const [customResetPw, setCustomResetPw] = useState('')
  const [resetBusy, setResetBusy] = useState(false)
  const [resetResult, setResetResult] = useState(null)

  const loadAccounts = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await api.adminAgents()
      setAgents(res.agents || [])
    } catch (err) {
      setError(err.message || 'Failed to load user accounts')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadAccounts()
  }, [loadAccounts])

  const handleToggleStatus = async (target) => {
    const action = target.is_active ? 'suspend' : 'activate'
    const confirmMsg = target.is_active
      ? `Are you sure you want to suspend login access for ${target.full_name}? All active sessions will be terminated immediately.`
      : `Activate login access for ${target.full_name}?`
    if (!window.confirm(confirmMsg)) return
    try {
      await api.adminUpdateAgentStatus(target.id, !target.is_active)
      setSuccess(`Account for ${target.full_name} has been ${action === 'suspend' ? 'suspended' : 'activated'}.`)
      loadAccounts()
    } catch (err) {
      setError(err.message || `Failed to ${action} account`)
    }
  }

  const handleCreateAccount = async (e) => {
    e.preventDefault()
    setCreateBusy(true)
    setError('')
    try {
      await api.adminCreateAgent({
        full_name: createForm.full_name,
        email: createForm.email,
        username: createForm.username || undefined,
        password: createForm.password || undefined,
        role: createForm.role,
      })
      setSuccess(`User account created successfully for ${createForm.full_name}.`)
      setShowCreate(false)
      setCreateForm({ full_name: '', email: '', username: '', password: '', role: 'agent' })
      loadAccounts()
    } catch (err) {
      setError(err.message || 'Failed to create user account')
    } finally {
      setCreateBusy(false)
    }
  }

  const handleResetPassword = async (e) => {
    e.preventDefault()
    if (!resetTarget) return
    setResetBusy(true)
    setError('')
    try {
      const res = await api.adminResetAgentPassword(resetTarget.id, {
        temporary_password: customResetPw.trim() || undefined,
      })
      setResetResult(res)
      setSuccess(`Temporary password generated and must_change_password policy enforced for ${resetTarget.full_name}.`)
    } catch (err) {
      setError(err.message || 'Failed to reset password')
    } finally {
      setResetBusy(false)
    }
  }

  const filtered = agents.filter((a) => {
    if (roleFilter && a.role !== roleFilter) return false
    if (search) {
      const q = search.toLowerCase()
      const matchName = (a.full_name || '').toLowerCase().includes(q)
      const matchEmail = (a.email || '').toLowerCase().includes(q)
      const matchUser = (a.username || '').toLowerCase().includes(q)
      if (!matchName && !matchEmail && !matchUser) return false
    }
    return true
  })

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
            <span style={{ fontSize: 13, color: '#64748b' }}>· IT Governance</span>
          </div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, color: '#0f172a' }}>
            User &amp; Role Administration
          </h1>
          <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: 14 }}>
            Enterprise credential provisioning, role authorizations, session revocations, and mandatory password policy enforcement.
          </p>
        </div>

        <button
          onClick={() => {
            setCreateForm({ full_name: '', email: '', username: '', password: '', role: 'agent' })
            setShowCreate(true)
          }}
          style={{
            padding: '8px 18px',
            borderRadius: 6,
            background: 'linear-gradient(135deg, #4a0e2e 0%, #701a45 100%)',
            color: '#fff',
            border: 'none',
            fontSize: 13,
            fontWeight: 700,
            cursor: 'pointer',
            boxShadow: '0 4px 6px -1px rgba(74, 14, 46, 0.25)',
          }}
        >
          ＋ Provision New Staff Account
        </button>
      </div>

      {error && (
        <div style={{ padding: '12px 16px', background: '#fef2f2', border: '1px solid #fecaca', color: '#dc2626', borderRadius: 8, marginBottom: 16, fontSize: 13 }}>
          ⚠️ {error}
        </div>
      )}

      {success && (
        <div style={{ padding: '12px 16px', background: '#ecfdf5', border: '1px solid #34d399', color: '#065f46', borderRadius: 8, marginBottom: 16, fontSize: 13 }}>
          ✓ {success}
        </div>
      )}

      {/* Filters */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap', alignItems: 'center' }}>
        <input
          className="ax-input"
          style={{ minWidth: 280, flex: 1 }}
          placeholder="Search by full name, email, or username…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select className="ax-input" value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
          <option value="">All Authorized Roles</option>
          <option value="admin">System Administrator (admin)</option>
          <option value="agent">Real Estate Agent (agent)</option>
          <option value="hr">HR Specialist / Manager (hr)</option>
          <option value="sales_manager">Sales Manager (sales_manager)</option>
        </select>
        <button
          onClick={loadAccounts}
          style={{ padding: '8px 14px', borderRadius: 6, background: '#fff', border: '1px solid #cbd5e1', cursor: 'pointer', fontSize: 13 }}
        >
          ↻ Refresh
        </button>
      </div>

      {/* Table */}
      <div className="ax-card" style={{ background: '#fff', borderRadius: 8, border: '1px solid #e2e8f0', overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, textAlign: 'left' }}>
          <thead>
            <tr style={{ background: '#f8fafc', borderBottom: '1px solid #e2e8f0', color: '#64748b' }}>
              <th style={{ padding: '12px 16px' }}>Staff Identity</th>
              <th style={{ padding: '12px 16px' }}>Authorized Username</th>
              <th style={{ padding: '12px 16px' }}>CRM Role</th>
              <th style={{ padding: '12px 16px' }}>Policy Status</th>
              <th style={{ padding: '12px 16px' }}>Account Status</th>
              <th style={{ padding: '12px 16px', textAlign: 'right' }}>Administrative Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} style={{ padding: 32, textAlign: 'center', color: '#64748b' }}>
                  Loading accounts…
                </td>
              </tr>
            ) : filtered.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ padding: 32, textAlign: 'center', color: '#64748b' }}>
                  No accounts found matching filter.
                </td>
              </tr>
            ) : (
              filtered.map((a) => (
                <tr key={a.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '12px 16px' }}>
                    <div style={{ fontWeight: 700, color: '#0f172a' }}>{a.full_name}</div>
                    <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{a.email}</div>
                  </td>
                  <td style={{ padding: '12px 16px', fontFamily: 'monospace', color: '#334155' }}>
                    {a.username}
                  </td>
                  <td style={{ padding: '12px 16px' }}>
                    <span
                      style={{
                        padding: '2px 8px',
                        borderRadius: 4,
                        fontSize: 11,
                        fontWeight: 700,
                        background:
                          a.role === 'admin' ? '#fef3c7' : a.role === 'hr' ? '#dcfce7' : '#e0f2fe',
                        color:
                          a.role === 'admin' ? '#92400e' : a.role === 'hr' ? '#166534' : '#0369a1',
                      }}
                    >
                      {a.role.toUpperCase()}
                    </span>
                  </td>
                  <td style={{ padding: '12px 16px' }}>
                    {a.must_change_password ? (
                      <span
                        style={{
                          fontSize: 11,
                          fontWeight: 700,
                          padding: '2px 6px',
                          borderRadius: 4,
                          background: '#fee2e2',
                          color: '#dc2626',
                        }}
                      >
                        PASSWORD RESET REQUIRED
                      </span>
                    ) : (
                      <span style={{ fontSize: 12, color: '#16a34a', fontWeight: 600 }}>✓ Verified</span>
                    )}
                  </td>
                  <td style={{ padding: '12px 16px' }}>
                    <span
                      style={{
                        fontSize: 11,
                        fontWeight: 700,
                        padding: '2px 8px',
                        borderRadius: 4,
                        background: a.is_active ? '#dcfce7' : '#fee2e2',
                        color: a.is_active ? '#166534' : '#991b1b',
                      }}
                    >
                      {a.is_active ? 'ACTIVE' : 'SUSPENDED'}
                    </span>
                  </td>
                  <td style={{ padding: '12px 16px', textAlign: 'right' }}>
                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                      <button
                        onClick={() => {
                          setResetTarget(a)
                          setCustomResetPw('')
                          setResetResult(null)
                        }}
                        style={{
                          padding: '4px 10px',
                          borderRadius: 6,
                          background: '#f8fafc',
                          border: '1px solid #cbd5e1',
                          fontSize: 12,
                          fontWeight: 600,
                          cursor: 'pointer',
                        }}
                      >
                        Reset PW
                      </button>
                      <button
                        onClick={() => handleToggleStatus(a)}
                        style={{
                          padding: '4px 10px',
                          borderRadius: 6,
                          background: a.is_active ? '#fef2f2' : '#ecfdf5',
                          border: a.is_active ? '1px solid #fecaca' : '1px solid #a7f3d0',
                          color: a.is_active ? '#dc2626' : '#166534',
                          fontSize: 12,
                          fontWeight: 600,
                          cursor: 'pointer',
                        }}
                        title={a.is_active ? 'Suspend system login and revoke active sessions' : 'Activate system login'}
                      >
                        {a.is_active ? 'Suspend Login' : 'Activate Login'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Reset Password Modal */}
      {resetTarget && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(15,23,42,0.7)',
            backdropFilter: 'blur(4px)',
            zIndex: 9999,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 20,
          }}
        >
          <div style={{ width: '100%', maxWidth: 460, background: '#fff', borderRadius: 12, overflow: 'hidden' }}>
            <div style={{ padding: '16px 20px', background: '#1e293b', color: '#fff', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ margin: 0, fontSize: 16 }}>Reset Password: {resetTarget.full_name}</h3>
              <button
                onClick={() => setResetTarget(null)}
                style={{ background: 'transparent', border: 'none', color: '#fff', cursor: 'pointer', fontSize: 18 }}
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleResetPassword} style={{ padding: 20 }}>
              <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 16px 0' }}>
                Generating a temporary password will immediately revoke all active sessions for this user and require a password change on next login.
              </p>
              {resetResult ? (
                <div style={{ padding: 14, background: '#ecfdf5', border: '1px solid #a7f3d0', borderRadius: 8, marginBottom: 16 }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: '#065f46' }}>Temporary Password Generated:</div>
                  <div style={{ fontSize: 16, fontWeight: 700, fontFamily: 'monospace', color: '#047857', marginTop: 4, letterSpacing: '0.05em' }}>
                    {resetResult.temporary_password}
                  </div>
                  <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>
                    Provide this temporary secret to the user securely.
                  </div>
                </div>
              ) : (
                <div style={{ marginBottom: 16 }}>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#334155', marginBottom: 4 }}>
                    Custom Temporary Password (Optional)
                  </label>
                  <input
                    type="text"
                    className="ax-input"
                    style={{ width: '100%' }}
                    placeholder="Leave blank to auto-generate"
                    value={customResetPw}
                    onChange={(e) => setCustomResetPw(e.target.value)}
                  />
                </div>
              )}
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
                <button
                  type="button"
                  onClick={() => setResetTarget(null)}
                  style={{ padding: '8px 14px', borderRadius: 6, background: '#f1f5f9', border: 'none', cursor: 'pointer' }}
                >
                  {resetResult ? 'Close' : 'Cancel'}
                </button>
                {!resetResult && (
                  <button
                    type="submit"
                    disabled={resetBusy}
                    style={{ padding: '8px 18px', borderRadius: 6, background: '#dc2626', color: '#fff', border: 'none', fontWeight: 600, cursor: 'pointer' }}
                  >
                    {resetBusy ? 'Resetting…' : 'Reset Credentials'}
                  </button>
                )}
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Create Account Modal */}
      {showCreate && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(15,23,42,0.7)',
            backdropFilter: 'blur(4px)',
            zIndex: 9999,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 20,
          }}
        >
          <div style={{ width: '100%', maxWidth: 480, background: '#fff', borderRadius: 12, overflow: 'hidden' }}>
            <div style={{ padding: '16px 20px', background: '#4a0e2e', color: '#fff', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ margin: 0, fontSize: 16 }}>Provision Staff Account</h3>
              <button
                onClick={() => setShowCreate(false)}
                style={{ background: 'transparent', border: 'none', color: '#fff', cursor: 'pointer', fontSize: 18 }}
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleCreateAccount} style={{ padding: 20 }}>
              <div style={{ marginBottom: 14 }}>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#334155', marginBottom: 4 }}>
                  Full Name *
                </label>
                <input
                  type="text"
                  className="ax-input"
                  style={{ width: '100%' }}
                  required
                  value={createForm.full_name}
                  onChange={(e) => setCreateForm({ ...createForm, full_name: e.target.value })}
                  placeholder="e.g. Tariq Al Nuaimi"
                />
              </div>
              <div style={{ marginBottom: 14 }}>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#334155', marginBottom: 4 }}>
                  Official Email *
                </label>
                <input
                  type="email"
                  className="ax-input"
                  style={{ width: '100%' }}
                  required
                  value={createForm.email}
                  onChange={(e) => setCreateForm({ ...createForm, email: e.target.value })}
                  placeholder="e.g. tariq@lykarealty.ae"
                />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#334155', marginBottom: 4 }}>
                    Username (Optional)
                  </label>
                  <input
                    type="text"
                    className="ax-input"
                    style={{ width: '100%' }}
                    value={createForm.username}
                    onChange={(e) => setCreateForm({ ...createForm, username: e.target.value })}
                    placeholder="tariq_nuaimi"
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#334155', marginBottom: 4 }}>
                    Authorized Role *
                  </label>
                  <select
                    className="ax-input"
                    style={{ width: '100%' }}
                    value={createForm.role}
                    onChange={(e) => setCreateForm({ ...createForm, role: e.target.value })}
                  >
                    <option value="agent">Real Estate Agent (agent)</option>
                    <option value="sales_manager">Sales Manager (sales_manager)</option>
                    <option value="hr">HR Specialist / Manager (hr)</option>
                    <option value="admin">System Administrator (admin)</option>
                  </select>
                </div>
              </div>
              <div style={{ marginBottom: 18 }}>
                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#334155', marginBottom: 4 }}>
                  Initial Password (Optional)
                </label>
                <input
                  type="password"
                  className="ax-input"
                  style={{ width: '100%' }}
                  placeholder="Leave blank to auto-generate"
                  value={createForm.password}
                  onChange={(e) => setCreateForm({ ...createForm, password: e.target.value })}
                />
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
                <button
                  type="button"
                  onClick={() => setShowCreate(false)}
                  style={{ padding: '8px 14px', borderRadius: 6, background: '#f1f5f9', border: 'none', cursor: 'pointer' }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createBusy}
                  style={{ padding: '8px 18px', borderRadius: 6, background: '#4a0e2e', color: '#fff', border: 'none', fontWeight: 600, cursor: 'pointer' }}
                >
                  {createBusy ? 'Provisioning…' : 'Create Staff Login'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

