import React from 'react'

import { useNavigate } from 'react-router-dom'

import { useAuth, hasPerm } from '../auth/AuthContext.jsx'

import api from '../api.js'

export const STATUSES = [

  ['new', 'New'],

  ['contact_pending', 'Contact pending'],

  ['contacted', 'Contacted'],

  ['qualified', 'Qualified'],

  ['viewing', 'Viewing scheduled'],

  ['negotiation', 'Negotiation / Offer'],

  ['nurturing', 'Nurturing / On hold'],

  ['closed_won', 'Won'],

  ['closed_lost', 'Lost'],

]

const PRIORITIES = [

  ['', 'Any priority'],

  ['high', 'High'],

  ['medium', 'Medium'],

  ['low', 'Low'],

  ['unscored', 'Unscored'],

]

const INTENTS = [

  ['', 'Any intent'],

  ['buy', 'Buy'],

  ['rent', 'Rent'],

  ['lease', 'Lease'],

  ['unknown', 'Unknown'],

]

// Follow-up state buckets (UTC day boundaries, computed server-side)

const FOLLOWUPS = [

  ['', 'Any follow-up'],

  ['overdue', 'Overdue'],

  ['due_today', 'Due today'],

  ['upcoming', 'Upcoming'],

  ['pending', 'Pending'],

  ['completed', 'Completed'],

  ['cancelled', 'Cancelled'],

]

const PAGE = 50

export function statusLabel(v) {

  const hit = STATUSES.find(([k]) => k === v)

  return hit ? hit[1] : v

}

export const TEMPERATURES = [
  ['', 'All Temperatures'],
  ['hot', '🔥 HOT'],
  ['warm', '⚡ WARM'],
  ['cold', '❄️ COLD'],
  ['unclassified', '— Unclassified'],
]

export function temperatureLabel(v) {
  return ({ hot: '🔥 HOT', warm: '⚡ WARM', cold: '❄️ COLD' })[v] || '— Unclassified'
}

export function priorityLabel(v) {

  return ({ high: 'High', medium: 'Medium', low: 'Low' })[v] || '—'

}

export function fmtDate(iso) {

  if (!iso) return '—'

  return new Date(iso).toLocaleString([], {

    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',

  })

}

/**

 * /agent/leads — searchable, filterable, paginated lead list & sales pipeline.

 * Server-side filtering on purpose: the backend re-applies the agent's data

 * scope to every query (never trusts the frontend).

 */

export default function AgentLeads() {

  const navigate = useNavigate()

  const { permissions } = useAuth()

  const canManageAll = hasPerm({ permissions }, 'leads.read_all')

  const [rows, setRows] = React.useState([])

  const [total, setTotal] = React.useState(0)

  const [loading, setLoading] = React.useState(true)

  const [error, setError] = React.useState(null)

  const [salesAgents, setSalesAgents] = React.useState([])

  const [q, setQ] = React.useState('')

  const [status, setStatus] = React.useState('')

  const [priority, setPriority] = React.useState('')

  const [temperature, setTemperature] = React.useState('')

  const [intent, setIntent] = React.useState('')

  const [followUp, setFollowUp] = React.useState('')

  const [location, setLocation] = React.useState('')

  const [agentFilter, setAgentFilter] = React.useState('')

  const [sort, setSort] = React.useState('newest')

  React.useEffect(() => {

    api.agentSalesAgents().then((r) => setSalesAgents(r.results || [])).catch(() => {})

  }, [])

  const buildFilters = () => {

    const out = { q, status, priority, temperature, intent, follow_up: followUp, location, sort }

    if (agentFilter === 'unassigned') {

      out.unassigned = true

    } else if (agentFilter) {

      out.assigned_agent_id = Number(agentFilter)

    }

    return out

  }

  // Debounced fetch whenever a filter changes (always resets to page 1)

  React.useEffect(() => {

    const t = setTimeout(() => {

      setLoading(true)

      api

        .agentLeads({ ...buildFilters(), limit: PAGE, offset: 0 })

        .then((r) => {

          setRows(r.results)

          setTotal(r.total)

          setError(null)

        })

        .catch((e) => setError(e.message))

        .finally(() => setLoading(false))

    }, 250)

    return () => clearTimeout(t)

    // eslint-disable-next-line react-hooks/exhaustive-deps

  }, [q, status, priority, temperature, intent, followUp, location, agentFilter, sort])

  const loadMore = () => {

    setLoading(true)

    api

      .agentLeads({ ...buildFilters(), limit: PAGE, offset: rows.length })

      .then((r) => {

        setRows((prev) => [...prev, ...r.results])

        setTotal(r.total)

      })

      .catch((e) => setError(e.message))

      .finally(() => setLoading(false))

  }

  const changeStatus = async (e, lead) => {

    e.stopPropagation()

    const next = e.target.value

    const prev = lead.status

    const isReopen = (prev === 'closed_won' || prev === 'closed_lost') && next !== prev

    let reason = null

    if (isReopen) {

      reason = window.prompt(`Reopening closed lead #${lead.id} from ${statusLabel(prev)} to ${statusLabel(next)}. Optional reason:`, 'Customer re-engaged')

      if (reason === null) return

    }

    setRows((rs) => rs.map((r) => (r.id === lead.id ? { ...r, status: next } : r)))

    try {

      await api.updateAgentLead(lead.id, {

        status: next,

        ...(isReopen ? { reopen: true, status_reason: reason } : {}),

      })

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

        <select className="ax-input" value={priority} onChange={(e) => setPriority(e.target.value)}>

          {PRIORITIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}

        </select>

        <select className="ax-input" value={temperature} onChange={(e) => setTemperature(e.target.value)}>

          {TEMPERATURES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}

        </select>

        <select className="ax-input" value={intent} onChange={(e) => setIntent(e.target.value)}>

          {INTENTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}

        </select>

        <select className="ax-input" value={followUp} onChange={(e) => setFollowUp(e.target.value)}>

          {FOLLOWUPS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}

        </select>

        {canManageAll ? (

          <select className="ax-input" value={agentFilter} onChange={(e) => setAgentFilter(e.target.value)}>

            <option value="">All owners</option>

            <option value="unassigned">Unassigned pool</option>

            {salesAgents.map((a) => (

              <option key={a.id} value={String(a.id)}>

                {a.full_name} ({a.active_lead_count ?? 0})

              </option>

            ))}

          </select>

        ) : (

          <span className="ax-pill" style={{ background: 'var(--crm-bg-surface-elevated, #f1f5f9)', color: 'var(--crm-text-primary, #0f172a)', fontWeight: 500, padding: '0.4rem 0.75rem', borderRadius: 6, fontSize: '0.85rem' }}>

            My Assigned Leads

          </span>

        )}

        <input

          className="ax-input"

          placeholder="Filter location…"

          value={location}

          onChange={(e) => setLocation(e.target.value)}

        />

        <select className="ax-input" value={sort} onChange={(e) => setSort(e.target.value)}>

          <option value="newest">Newest first</option>

          <option value="interaction">Recent interaction</option>

          <option value="score">Highest score</option>

        </select>

        <span className="ax-count">{total} lead{total === 1 ? '' : 's'}</span>

        <button className="btn btn-sm" onClick={() => navigate('/agent/leads/new')}>

          ＋ New lead

        </button>

      </div>

      {error && <div className="ax-empty">⚠ {error}</div>}

      {/* Table */}

      <div className="ax-table">

        <div className="ax-table__head">

          <span>Lead &amp; Owner</span>

          <span>Contact</span>

          <span>Requirement</span>

          <span>Budget</span>

          <span>Score &amp; Qual.</span>

          <span>Status</span>

          <span>Next Action / Touch</span>

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

              <br />

              <small className="ax-muted">

                {l.assigned_agent_name ? `👤 ${l.assigned_agent_name}` : '🏊 Shared pool'}

              </small>

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

            <span>

              {l.lead_score == null ? (

                <span className="ax-muted">Unscored</span>

              ) : (

                <span className={`ax-prio ${l.priority}`}>

                  {priorityLabel(l.priority)} · {Math.round(l.lead_score)}

                </span>

              )}

              {l.qualification_completeness != null && (

                <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>

                  Qual: {l.qualification_completeness}%

                </div>

              )}

            </span>

            <span onClick={(e) => e.stopPropagation()} style={{ minWidth: 0, overflow: 'hidden' }}>
              <select
                className={`ax-status-select ${l.status}`}
                value={l.status}
                onChange={(e) => changeStatus(e, l)}
              >
                {STATUSES.map(([k, lbl]) => <option key={k} value={k}>{lbl}</option>)}
              </select>
            </span>

            <span className="ax-cell-sub" style={{ minWidth: 0, wordBreak: 'break-word', overflowWrap: 'break-word' }}>
              {l.next_follow_up ? (
                <>
                  <span className={`ax-bucket ${l.next_follow_up.bucket || ''}`} style={{ marginRight: 4 }}>
                    {l.next_follow_up.type}
                  </span>
                  {fmtDate(l.next_follow_up.due_at)}
                </>
              ) : l.next_action ? (
                <span>{l.next_action}</span>
              ) : (
                <span>{fmtDate(l.last_interaction_at)}</span>
              )}
            </span>

            <span>{fmtDate(l.created_at)}</span>

          </div>

        ))}

      </div>

      {rows.length > 0 && rows.length < total && (

        <div style={{ marginTop: 14, textAlign: 'center' }}>

          <button className="btn btn-sm btn-ghost" disabled={loading} onClick={loadMore}>

            {loading ? 'Loading…' : `Load more (${rows.length} of ${total})`}

          </button>

        </div>

      )}

    </div>

  )

}
