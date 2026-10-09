import React from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api.js'

export const STATUSES = [
  ['new', 'New'],
  ['contacted', 'Contacted'],
  ['qualified', 'Qualified'],
  ['viewing', 'Viewing'],
  ['negotiation', 'Negotiation'],
  ['closed_won', 'Closed'],
  ['closed_lost', 'Lost'],
]

export function statusLabel(v) {
  const hit = STATUSES.find(([k]) => k === v)
  return hit ? hit[1] : v
}

export function fmtDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString([], {
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

/**
 * /agent/leads — searchable, filterable, sortable lead list.
 * Server-side filtering on purpose: the backend re-applies the agent's data
 * scope to every query (never trusts the frontend).
 */
export default function AgentLeads() {
  const navigate = useNavigate()
  const [rows, setRows] = React.useState([])
  const [total, setTotal] = React.useState(0)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState(null)

  const [q, setQ] = React.useState('')
  const [status, setStatus] = React.useState('')
  const [location, setLocation] = React.useState('')
  const [sort, setSort] = React.useState('newest')

  // Debounced fetch whenever a filter changes
  React.useEffect(() => {
    const t = setTimeout(() => {
      setLoading(true)
      api
        .agentLeads({ q, status, location, sort })
        .then((r) => {
          setRows(r.results)
          setTotal(r.total)
          setError(null)
        })
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false))
    }, 250)
    return () => clearTimeout(t)
  }, [q, status, location, sort])

  const changeStatus = async (e, lead) => {
    e.stopPropagation()
    const next = e.target.value
    const prev = lead.status
    setRows((rs) => rs.map((r) => (r.id === lead.id ? { ...r, status: next } : r)))
    try {
      await api.updateAgentLead(lead.id, { status: next })
    } catch (err) {
      setRows((rs) => rs.map((r) => (r.id === lead.id ? { ...r, status: prev } : r)))
      alert('Could not update status: ' + err.message)
    }
  }

  const open = (id) => navigate(`/agent/leads/${id}`)

  return (
    <div>
      {/* Toolbar */}
      <div className="ax-toolbar">
        <input
          className="ax-input ax-input--search"
          placeholder="Search name, phone, email or lead ID…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select className="ax-input" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          {STATUSES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <input
          className="ax-input"
          placeholder="Filter location…"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
        />
        <select className="ax-input" value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="newest">Newest first</option>
          <option value="interaction">Recent interaction</option>
        </select>
        <span className="ax-count">{total} lead{total === 1 ? '' : 's'}</span>
      </div>

      {error && <div className="ax-empty">⚠ {error}</div>}

      {/* Table */}
      <div className="ax-table">
        <div className="ax-table__head">
          <span>Lead</span>
          <span>Contact</span>
          <span>Requirement</span>
          <span>Budget</span>
          <span>Status</span>
          <span>Last interaction</span>
          <span>Created</span>
        </div>

        {loading && rows.length === 0 && (
          <div className="ax-empty sm"><div className="ax-spin" /> Loading leads…</div>
        )}
        {!loading && rows.length === 0 && (
          <div className="ax-empty sm">No leads match your filters.</div>
        )}

        {rows.map((l) => (
          <div
            className="ax-table__row"
            key={l.id}
            role="button"
            tabIndex={0}
            onClick={() => open(l.id)}
            onKeyDown={(e) => e.key === 'Enter' && open(l.id)}
          >
            <span className="ax-cell-strong">
              <i className="ax-id">#{l.id}</i> {l.name}
            </span>
            <span className="ax-cell-sub">
              {l.phone}
              <br />
              {l.email}
            </span>
            <span className="ax-cell-sub">
              {l.location} · {l.property_type}
              <br />
              {l.bedrooms != null ? `${l.bedrooms} bed` : 'Studio/unknown'} · {l.buy_rent}
            </span>
            <span className="ax-cell-strong">{l.budget}</span>
            <span onClick={(e) => e.stopPropagation()}>
              <select
                className={`ax-status-select ${l.status}`}
                value={l.status}
                onChange={(e) => changeStatus(e, l)}
              >
                {STATUSES.map(([k, lbl]) => <option key={k} value={k}>{lbl}</option>)}
              </select>
            </span>
            <span>{fmtDate(l.last_interaction_at)}</span>
            <span>{fmtDate(l.created_at)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
