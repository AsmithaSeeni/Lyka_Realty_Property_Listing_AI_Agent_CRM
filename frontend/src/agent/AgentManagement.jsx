import React from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../api.js'
import { useAuth, hasPerm } from '../auth/AuthContext.jsx'

export default function AgentManagement() {
  const navigate = useNavigate()
  const { permissions, agent: currentAgent } = useAuth()
  const canManageUsers = hasPerm({ permissions }, 'users.create') || currentAgent?.role === 'admin'

  const [agents, setAgents] = React.useState([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState('')
  const [searchQuery, setSearchQuery] = React.useState('')
  const [roleFilter, setRoleFilter] = React.useState('')
  const [statusFilter, setStatusFilter] = React.useState('')

  // Modals & Drawers
  const [createOpen, setCreateOpen] = React.useState(false)
  const [createForm, setCreateForm] = React.useState({
    full_name: '',
    email: '',
    username: '',
    password: '',
    role: 'agent',
  })
  const [createBusy, setCreateBusy] = React.useState(false)
  const [createResult, setCreateResult] = React.useState(null)

  const [inspectAgentId, setInspectAgentId] = React.useState(null)
  const [inspectData, setInspectData] = React.useState(null)
  const [inspectLoading, setInspectLoading] = React.useState(false)

  const fetchAgents = React.useCallback(async () => {
    try {
      setLoading(true)
      setError('')
      const res = await api.adminAgents()
      setAgents(res.agents || [])
    } catch (err) {
      setError(err.message || 'Failed to load agent accounts')
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    fetchAgents()
  }, [fetchAgents])

  // Open inspector drawer
  const openInspector = async (agentId) => {
    setInspectAgentId(agentId)
    setInspectLoading(true)
    try {
      const res = await api.adminAgentDetail(agentId)
      setInspectData(res.agent)
    } catch (err) {
      alert('Error fetching agent details: ' + err.message)
      setInspectAgentId(null)
    } finally {
      setInspectLoading(false)
    }
  }

  // Create new agent handler
  const handleCreateAgent = async (e) => {
    e.preventDefault()
    setCreateBusy(true)
    setError('')
    try {
      const res = await api.adminCreateAgent({
        full_name: createForm.full_name,
        email: createForm.email,
        username: createForm.username || undefined,
        password: createForm.password || undefined,
        role: createForm.role || 'agent',
      })
      setCreateResult(res)
      setCreateForm({ full_name: '', email: '', username: '', password: '', role: 'agent' })
      fetchAgents()
    } catch (err) {
      alert('Failed to create agent: ' + err.message)
    } finally {
      setCreateBusy(false)
    }
  }

  // Filtered agents
  const filteredAgents = agents.filter((a) => {
    if (roleFilter && a.role !== roleFilter) return false
    if (statusFilter === 'active' && !a.is_active) return false
    if (statusFilter === 'inactive' && a.is_active) return false
    if (searchQuery) {
      const q = searchQuery.toLowerCase()
      const matchName = (a.full_name || '').toLowerCase().includes(q)
      const matchEmail = (a.email || '').toLowerCase().includes(q)
      const matchUsername = (a.username || '').toLowerCase().includes(q)
      if (!matchName && !matchEmail && !matchUsername) return false
    }
    return true
  })

  // Summary Metrics
  const activeCount = agents.filter((a) => a.is_active).length
  const totalLeads = agents.reduce((sum, a) => sum + (a.workload?.assigned_leads || 0), 0)
  const totalHotLeads = agents.reduce((sum, a) => sum + (a.workload?.hot_leads || 0), 0)
  const totalOverdueFollowups = agents.reduce((sum, a) => sum + (a.workload?.overdue_followups || 0), 0)

  return (
    <div className="ax-page" style={{ padding: '24px 32px' }}>
      {/* Top Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24, flexWrap: 'wrap', gap: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, color: '#0f172a' }}>Sales-Agent & User Operations</h1>
          <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: 14 }}>
            Monitor agent workloads, manage credentials, reset passwords, and provision team members.
          </p>
        </div>
        {canManageUsers && (
          <button className="btn btn-primary" onClick={() => { setCreateResult(null); setCreateOpen(true) }}>
            ＋ Provision New Sales Agent
          </button>
        )}
      </div>

      {/* Summary KPI Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16, marginBottom: 24 }}>
        <div className="ax-card" style={{ padding: 16, background: '#fff', borderRadius: 8, border: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>Active Agents</div>
          <div style={{ fontSize: 26, fontWeight: 700, color: '#0f172a', marginTop: 4 }}>{activeCount}</div>
          <div style={{ fontSize: 12, color: '#16a34a', marginTop: 4 }}>{agents.length} Total accounts</div>
        </div>
        <div className="ax-card" style={{ padding: 16, background: '#fff', borderRadius: 8, border: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>Active Assigned Leads</div>
          <div style={{ fontSize: 26, fontWeight: 700, color: '#0284c7', marginTop: 4 }}>{totalLeads}</div>
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>Distributed across team</div>
        </div>
        <div className="ax-card" style={{ padding: 16, background: '#fff', borderRadius: 8, border: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>Hot Leads In Scope</div>
          <div style={{ fontSize: 26, fontWeight: 700, color: '#dc2626', marginTop: 4 }}>{totalHotLeads}</div>
          <div style={{ fontSize: 12, color: '#dc2626', marginTop: 4 }}>Requires immediate action</div>
        </div>
        <div className="ax-card" style={{ padding: 16, background: '#fff', borderRadius: 8, border: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>Overdue Follow-ups</div>
          <div style={{ fontSize: 26, fontWeight: 700, color: totalOverdueFollowups > 0 ? '#ea580c' : '#16a34a', marginTop: 4 }}>
            {totalOverdueFollowups}
          </div>
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>Past SLA schedule</div>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap', alignItems: 'center' }}>
        <input
          className="ax-input"
          style={{ minWidth: 260, flex: 1 }}
          placeholder="Search by name, email, or username…"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        <select className="ax-input" value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
          <option value="">All Roles</option>
          <option value="agent">Sales Agent</option>
          <option value="admin">System Admin</option>
          <option value="sales_manager">Sales Manager</option>
        </select>
        <select className="ax-input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All Statuses</option>
          <option value="active">Active Only</option>
          <option value="inactive">Deactivated Only</option>
        </select>
        <button className="btn btn-sm btn-ghost" onClick={fetchAgents} title="Refresh roster">
          ↻ Refresh
        </button>
      </div>

      {error && (
        <div style={{ padding: 12, background: '#fef2f2', color: '#dc2626', borderRadius: 8, marginBottom: 16, fontSize: 14 }}>
          ⚠ {error}
        </div>
      )}

      {/* Agents Roster Table */}
      <div className="ax-table" style={{ background: '#fff', borderRadius: 8, border: '1px solid #e2e8f0', overflow: 'hidden' }}>
        <div className="ax-table__head" style={{ gridTemplateColumns: '2fr 1.5fr 1fr 2.5fr 1.2fr 1.8fr' }}>
          <span>Agent / Staff Name</span>
          <span>Contact & Username</span>
          <span>Role & Status</span>
          <span>Workload & Temperature</span>
          <span>Last Sign-in</span>
          <span style={{ textAlign: 'right' }}>Actions</span>
        </div>

        {loading && (
          <div style={{ padding: 32, textAlign: 'center', color: '#64748b' }}>
            <div className="ax-spin" style={{ margin: '0 auto 8px' }} />
            Loading agents and workload analytics…
          </div>
        )}

        {!loading && filteredAgents.length === 0 && (
          <div style={{ padding: 32, textAlign: 'center', color: '#64748b' }}>
            No agents found matching your query.
          </div>
        )}

        {!loading && filteredAgents.map((a) => {
          const wl = a.workload || {}
          return (
            <div
              key={a.id}
              className="ax-table__row"
              style={{ gridTemplateColumns: '2fr 1.5fr 1fr 2.5fr 1.2fr 1.8fr', alignItems: 'center' }}
            >
              {/* Name & ID */}
              <div>
                <div style={{ fontWeight: 600, color: '#0f172a' }}>
                  {a.full_name}
                  {a.id === currentAgent?.id && (
                    <span style={{ marginLeft: 6, fontSize: 11, background: '#dbeafe', color: '#1d4ed8', padding: '2px 6px', borderRadius: 4 }}>
                      You
                    </span>
                  )}
                </div>
                <div style={{ fontSize: 12, color: '#64748b' }}>ID #{a.id}</div>
              </div>

              {/* Contact */}
              <div style={{ fontSize: 13 }}>
                <div style={{ color: '#0f172a' }}>{a.email}</div>
                <div style={{ color: '#64748b', fontSize: 12 }}>@{a.username}</div>
              </div>

              {/* Role & Status */}
              <div>
                <span style={{
                  display: 'inline-block',
                  fontSize: 11,
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  padding: '2px 8px',
                  borderRadius: 4,
                  background: a.role === 'admin' ? '#fef3c7' : '#f1f5f9',
                  color: a.role === 'admin' ? '#b45309' : '#334155',
                  marginBottom: 4,
                }}>
                  {a.role}
                </span>
                <br />
                <span style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: a.is_active ? '#16a34a' : '#94a3b8',
                }}>
                  {a.is_active ? '● Active' : '○ Deactivated'}
                </span>
              </div>

              {/* Workload Breakdown */}
              <div style={{ fontSize: 13 }}>
                <div style={{ marginBottom: 4 }}>
                  <b>{wl.assigned_leads || 0}</b> leads
                  <span style={{ marginLeft: 8, fontSize: 11 }}>
                    <span style={{ color: '#dc2626', fontWeight: 600 }}>🔥 {wl.hot_leads || 0}</span> ·{' '}
                    <span style={{ color: '#d97706', fontWeight: 600 }}>⚡ {wl.warm_leads || 0}</span> ·{' '}
                    <span style={{ color: '#0284c7' }}>❄️ {wl.cold_leads || 0}</span>
                  </span>
                </div>
                <div style={{ fontSize: 11, color: '#64748b' }}>
                  Follow-ups: {wl.pending_followups || 0} (
                  <span style={{ color: wl.overdue_followups > 0 ? '#dc2626' : '#64748b' }}>
                    {wl.overdue_followups || 0} overdue
                  </span>
                  ) · {wl.upcoming_appointments || 0} viewings
                </div>
              </div>

              {/* Last sign in */}
              <div style={{ fontSize: 12, color: '#64748b' }}>
                {a.last_login_at ? new Date(a.last_login_at).toLocaleDateString() : 'Never logged in'}
              </div>

              {/* Actions */}
              <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', flexWrap: 'wrap', alignItems: 'center' }}>
                <button
                  className="btn btn-sm btn-ghost"
                  onClick={() => openInspector(a.id)}
                  title="Inspect agent workload & leads"
                >
                  Inspect Leads
                </button>
                {canManageUsers && (
                  <button
                    className="btn btn-sm btn-ghost"
                    onClick={() => navigate('/agent/users')}
                    title="Manage user credentials, roles, and account suspension in User & Role Administration"
                    style={{ color: '#4f46e5', fontWeight: 600 }}
                  >
                    Manage Account →
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* --- CREATE AGENT MODAL --- */}
      {createOpen && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(15, 23, 42, 0.6)', display: 'flex', alignItems: 'center',
          justifyContent: 'center', zIndex: 1000, padding: 16
        }}>
          <div style={{ background: '#fff', borderRadius: 12, padding: 24, maxWidth: 480, width: '100%', boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)' }}>
            <h3 style={{ margin: '0 0 8px', fontSize: 18, color: '#0f172a' }}>Provision New Sales Agent</h3>
            <p style={{ margin: '0 0 16px', color: '#64748b', fontSize: 13 }}>
              Enter account details. A secure temporary password will be auto-generated if left blank.
            </p>

            {createResult ? (
              <div>
                <div style={{ padding: 14, background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8, color: '#166534', marginBottom: 16, fontSize: 14 }}>
                  <div style={{ fontWeight: 600 }}>✓ Sales Agent Provisioned Successfully</div>
                  <div style={{ marginTop: 6, fontSize: 13 }}>
                    <b>Email:</b> {createResult.agent?.email}
                    <br />
                    <b>Temporary Password:</b>{' '}
                    <code style={{ background: '#dcfce7', padding: '2px 6px', borderRadius: 4, fontWeight: 700 }}>
                      {createResult.temporary_password || '(Custom password entered)'}
                    </code>
                  </div>
                </div>
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                  <button className="btn btn-sm" onClick={() => setCreateOpen(false)}>
                    Close
                  </button>
                </div>
              </div>
            ) : (
              <form onSubmit={handleCreateAgent}>
                <div style={{ marginBottom: 12 }}>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 4 }}>Full Name *</label>
                  <input
                    className="ax-input"
                    style={{ width: '100%' }}
                    required
                    placeholder="e.g. Sales Agent Test 06"
                    value={createForm.full_name}
                    onChange={(e) => setCreateForm({ ...createForm, full_name: e.target.value })}
                  />
                </div>
                <div style={{ marginBottom: 12 }}>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 4 }}>Email Address *</label>
                  <input
                    type="email"
                    className="ax-input"
                    style={{ width: '100%' }}
                    required
                    placeholder="e.g. agent.test06@lykarealty.ae"
                    value={createForm.email}
                    onChange={(e) => setCreateForm({ ...createForm, email: e.target.value })}
                  />
                </div>
                <div style={{ marginBottom: 12 }}>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 4 }}>Username (optional)</label>
                  <input
                    className="ax-input"
                    style={{ width: '100%' }}
                    placeholder="e.g. agent.test06"
                    value={createForm.username}
                    onChange={(e) => setCreateForm({ ...createForm, username: e.target.value })}
                  />
                </div>
                <div style={{ marginBottom: 12 }}>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 4 }}>Role</label>
                  <select
                    className="ax-input"
                    style={{ width: '100%' }}
                    value={createForm.role}
                    onChange={(e) => setCreateForm({ ...createForm, role: e.target.value })}
                  >
                    <option value="agent">Sales Agent</option>
                    <option value="sales_manager">Sales Manager</option>
                    <option value="admin">System Administrator</option>
                  </select>
                </div>
                <div style={{ marginBottom: 20 }}>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 4 }}>Initial Password (optional)</label>
                  <input
                    type="password"
                    className="ax-input"
                    style={{ width: '100%' }}
                    placeholder="Leave blank to auto-generate secure password"
                    value={createForm.password}
                    onChange={(e) => setCreateForm({ ...createForm, password: e.target.value })}
                  />
                </div>
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                  <button type="button" className="btn btn-sm btn-ghost" onClick={() => setCreateOpen(false)}>
                    Cancel
                  </button>
                  <button type="submit" className="btn btn-sm btn-primary" disabled={createBusy}>
                    {createBusy ? 'Provisioning…' : 'Create Agent Account'}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {/* --- AGENT WORKLOAD INSPECTOR DRAWER --- */}
      {inspectAgentId && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(15, 23, 42, 0.4)', display: 'flex', justifyContent: 'flex-end',
          zIndex: 1000
        }}>
          <div style={{
            background: '#fff', width: 'min(500px, 100%)', height: '100%',
            overflowY: 'auto', padding: 24, boxShadow: '-10px 0 25px rgba(0,0,0,0.1)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
              <h2 style={{ margin: 0, fontSize: 18, color: '#0f172a' }}>Agent Profile & Workload</h2>
              <button className="btn btn-sm btn-ghost" onClick={() => setInspectAgentId(null)}>✕ Close</button>
            </div>

            {inspectLoading && (
              <div style={{ padding: 32, textAlign: 'center', color: '#64748b' }}>
                <div className="ax-spin" style={{ margin: '0 auto 8px' }} />
                Loading agent performance profile…
              </div>
            )}

            {!inspectLoading && inspectData && (
              <div>
                <div style={{ padding: 14, background: '#f8fafc', borderRadius: 8, border: '1px solid #e2e8f0', marginBottom: 20 }}>
                  <div style={{ fontSize: 16, fontWeight: 700, color: '#0f172a' }}>{inspectData.full_name}</div>
                  <div style={{ fontSize: 13, color: '#64748b', marginTop: 2 }}>
                    {inspectData.email} · @{inspectData.username}
                  </div>
                  <div style={{ marginTop: 8 }}>
                    <span style={{ fontSize: 11, background: '#e2e8f0', padding: '2px 8px', borderRadius: 4, fontWeight: 600, marginRight: 6 }}>
                      {inspectData.role.toUpperCase()}
                    </span>
                    <span style={{ fontSize: 12, color: inspectData.is_active ? '#16a34a' : '#dc2626', fontWeight: 600 }}>
                      {inspectData.is_active ? '● Active' : '○ Deactivated'}
                    </span>
                  </div>
                </div>

                {/* Workload Stats */}
                <h4 style={{ margin: '0 0 10px', fontSize: 13, textTransform: 'uppercase', color: '#64748b', letterSpacing: 0.5 }}>
                  Operational Workload
                </h4>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 20 }}>
                  <div style={{ padding: 12, background: '#f1f5f9', borderRadius: 6 }}>
                    <div style={{ fontSize: 11, color: '#64748b' }}>Total Assigned Leads</div>
                    <div style={{ fontSize: 20, fontWeight: 700, color: '#0f172a' }}>{inspectData.workload?.assigned_leads || 0}</div>
                  </div>
                  <div style={{ padding: 12, background: '#fef2f2', borderRadius: 6 }}>
                    <div style={{ fontSize: 11, color: '#dc2626' }}>🔥 Hot Leads</div>
                    <div style={{ fontSize: 20, fontWeight: 700, color: '#dc2626' }}>{inspectData.workload?.hot_leads || 0}</div>
                  </div>
                  <div style={{ padding: 12, background: '#fffbeb', borderRadius: 6 }}>
                    <div style={{ fontSize: 11, color: '#b45309' }}>⚡ Warm Leads</div>
                    <div style={{ fontSize: 20, fontWeight: 700, color: '#b45309' }}>{inspectData.workload?.warm_leads || 0}</div>
                  </div>
                  <div style={{ padding: 12, background: '#f0f9ff', borderRadius: 6 }}>
                    <div style={{ fontSize: 11, color: '#0369a1' }}>❄️ Cold Leads</div>
                    <div style={{ fontSize: 20, fontWeight: 700, color: '#0369a1' }}>{inspectData.workload?.cold_leads || 0}</div>
                  </div>
                </div>

                {/* Recent Leads */}
                <h4 style={{ margin: '0 0 10px', fontSize: 13, textTransform: 'uppercase', color: '#64748b', letterSpacing: 0.5 }}>
                  Recently Assigned Leads
                </h4>
                {(!inspectData.recent_leads || inspectData.recent_leads.length === 0) ? (
                  <div style={{ color: '#94a3b8', fontSize: 13, fontStyle: 'italic' }}>No leads currently assigned.</div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {inspectData.recent_leads.map((l) => (
                      <Link
                        key={l.id}
                        to={`/agent/leads/${l.id}`}
                        style={{
                          padding: 10,
                          borderRadius: 6,
                          border: '1px solid #e2e8f0',
                          textDecoration: 'none',
                          color: 'inherit',
                          display: 'block',
                          background: '#fff'
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ fontWeight: 600, fontSize: 13, color: '#0f172a' }}>#{l.id} {l.name}</span>
                          <span style={{
                            fontSize: 11,
                            fontWeight: 600,
                            padding: '1px 6px',
                            borderRadius: 4,
                            background: l.temperature === 'hot' ? '#fee2e2' : l.temperature === 'warm' ? '#fef3c7' : '#f1f5f9',
                            color: l.temperature === 'hot' ? '#b91c1c' : l.temperature === 'warm' ? '#92400e' : '#475569'
                          }}>
                            {l.temperature ? l.temperature.toUpperCase() : 'UNCLASSIFIED'}
                          </span>
                        </div>
                        <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>
                          {l.location} · {l.property_type} · Budget: {l.budget}
                        </div>
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

