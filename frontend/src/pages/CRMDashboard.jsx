import React from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api.js'

const STATUSES = [
  'all',
  'new',
  'qualified',
  'contacted',
  'viewing',
  'negotiation',
  'closed_won',
  'closed_lost',
]

const STATUS_LABEL = {
  all: 'All',
  new: 'New',
  qualified: 'Qualified',
  contacted: 'Contacted',
  viewing: 'Viewing',
  negotiation: 'Negotiation',
  closed_won: 'Won',
  closed_lost: 'Lost',
}

export default function CRMDashboard() {
  const navigate = useNavigate()
  const [leads, setLeads] = React.useState([])
  const [loading, setLoading] = React.useState(true)
  const [filter, setFilter] = React.useState('all')
  const [query, setQuery] = React.useState('')
  const [selected, setSelected] = React.useState(null) // lead object
  const [convForLead, setConvForLead] = React.useState(null)
  const [notesDraft, setNotesDraft] = React.useState('')
  const [saving, setSaving] = React.useState(false)

  const load = React.useCallback(() => {
    setLoading(true)
    api
      .listLeads()
      .then((data) => setLeads(data))
      .catch(() => setLeads([]))
      .finally(() => setLoading(false))
  }, [])

  React.useEffect(load, [load])

  // Escape closes the lead drawer — standard, expected modal behaviour
  React.useEffect(() => {
    if (!selected) return
    const onKey = (e) => {
      if (e.key === 'Escape') setSelected(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected])

  const counts = React.useMemo(() => {
    const c = { all: leads.length }
    for (const s of STATUSES.slice(1)) c[s] = 0
    for (const l of leads) c[l.status] = (c[l.status] || 0) + 1
    return c
  }, [leads])

  const visible = React.useMemo(() => {
    let rows = leads
    if (filter !== 'all') rows = rows.filter((l) => l.status === filter)
    if (query.trim()) {
      const q = query.toLowerCase()
      rows = rows.filter((l) =>
        [l.name, l.phone, l.email, l.location, l.property_type, l.notes]
          .filter(Boolean)
          .some((v) => String(v).toLowerCase().includes(q)),
      )
    }
    return rows
  }, [leads, filter, query])

  const openLead = async (lead) => {
    setSelected(lead)
    setNotesDraft(lead.notes || '')
    setConvForLead(null)
    try {
      const convs = await api.listConversations()
      const match = convs.find(
        (c) =>
          (lead.phone && c.customer_phone === lead.phone) ||
          (lead.email && c.customer_email === lead.email) ||
          c.lead_id === lead.id,
      )
      if (match) {
        const full = await api.getConversation(match.id)
        setConvForLead(full)
      }
    } catch {
      /* conversation link is optional */
    }
  }

  const saveLead = async () => {
    if (!selected) return
    setSaving(true)
    try {
      await api.updateLead(selected.id, {
        notes: notesDraft,
        status: selected.status,
      })
      setSelected({ ...selected, notes: notesDraft })
      load()
    } catch (e) {
      alert('Failed to save: ' + e.message)
    } finally {
      setSaving(false)
    }
  }

  const setStatus = async (lead, status) => {
    try {
      await api.updateLead(lead.id, { status })
      if (selected?.id === lead.id) setSelected({ ...selected, status })
      load()
    } catch (e) {
      alert('Failed to update status: ' + e.message)
    }
  }

  return (
    <div className="page">
      <div className="page-head">
        <div className="row">
          <div>
            <span className="eyebrow">Sales pipeline</span>
            <h1>CRM Dashboard</h1>
            <p>
              Leads captured automatically from AI conversations — move them through
              the pipeline as you work.
            </p>
          </div>
          <button className="btn ghost btn-sm" onClick={load}>↻ Refresh</button>
        </div>
      </div>

      {/* Metrics */}
      <div className="metrics">
        <div className="metric"><b>{counts.all}</b><span>Total leads</span></div>
        <div className="metric g"><b>{counts.new || 0}</b><span>New</span></div>
        <div className="metric b"><b>{counts.qualified || 0}</b><span>Qualified</span></div>
        <div className="metric o"><b>{counts.contacted || 0}</b><span>Contacted</span></div>
        <div className="metric p"><b>{counts.viewing || 0}</b><span>Viewings</span></div>
        <div className="metric"><b>{counts.negotiation || 0}</b><span>Negotiation</span></div>
        <div className="metric g"><b>{counts.closed_won || 0}</b><span>Won</span></div>
        <div className="metric r"><b>{counts.closed_lost || 0}</b><span>Lost</span></div>
      </div>

      <div className="panel">
        <h3>Pipeline</h3>
        <div className="toolbar">
          <input
            className="search-input"
            placeholder="Search name, phone, email, area…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="chip-row">
            {STATUSES.map((s) => (
              <button
                key={s}
                className={`chip ${filter === s ? 'on' : ''}`}
                onClick={() => setFilter(s)}
              >
                {STATUS_LABEL[s]} ({counts[s] || 0})
              </button>
            ))}
          </div>
        </div>

        {loading && <div className="empty">Loading leads…</div>}
        {!loading && visible.length === 0 && (
          <div className="empty">
            <div className="big">🗂️</div>
            No leads{filter !== 'all' ? ` with status “${STATUS_LABEL[filter]}”` : ''} yet.
            <br />
            <span style={{ fontSize: 13 }}>
              Leads appear here once a chat visitor shares their name + phone/email.
            </span>
            <div style={{ marginTop: 18 }}>
              <button className="btn btn-gold btn-sm" onClick={() => navigate('/chat')}>
                Open AI chat
              </button>
            </div>
          </div>
        )}

        {visible.map((l) => (
          <div className="lead-row" key={l.id}>
            <div>
              <b>{l.name || 'Unnamed lead'}</b>
              <div className="sub">
                {l.phone && <>📞 {l.phone} · </>}
                {l.email && <>✉️ {l.email}</>}
                {!l.phone && !l.email && 'No contact details yet'}
              </div>
            </div>
            <div className="lead-cell">
              <div className="k">Looking for</div>
              <div className="v">
                {l.buy_rent ? l.buy_rent.toUpperCase() : '—'}
                {l.property_type ? ` · ${l.property_type}` : ''}
                {l.bedrooms ? ` · ${l.bedrooms} bed` : ''}
              </div>
            </div>
            <div className="lead-cell">
              <div className="k">Area · Budget</div>
              <div className="v">{l.location || '—'} {l.budget ? `· ${l.budget}` : ''}</div>
            </div>
            <div>
              <span className={`badge ${l.status}`}>{STATUS_LABEL[l.status] || l.status}</span>
              <div className="sub" style={{ marginTop: 5 }}>
                {l.created_at ? new Date(l.created_at).toLocaleDateString() : ''}
              </div>
            </div>
            <div style={{ display: 'flex', gap: 7 }}>
              <button className="btn btn-ghost btn-sm" onClick={() => openLead(l)}>
                Open
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Lead detail drawer */}
      {selected && (
        <div className="drawer-bg" onClick={(e) => { if (e.target === e.currentTarget) setSelected(null) }}>
          <div className="drawer">
            <div className="drawer-head">
              <div>
                <h2>{selected.name || 'Lead #' + selected.id}</h2>
                <span className={`badge ${selected.status}`}>
                  {STATUS_LABEL[selected.status] || selected.status}
                </span>
              </div>
              <button className="icon-btn" onClick={() => setSelected(null)}>✕</button>
            </div>

            <div className="subhead">Contact</div>
            <dl className="kv">
              <dt>Phone</dt><dd>{selected.phone || '—'}</dd>
              <dt>Email</dt><dd>{selected.email || '—'}</dd>
              <dt>Created</dt><dd>{selected.created_at ? new Date(selected.created_at).toLocaleString() : '—'}</dd>
              <dt>Updated</dt><dd>{selected.updated_at ? new Date(selected.updated_at).toLocaleString() : '—'}</dd>
            </dl>

            <div className="subhead">Requirements</div>
            <dl className="kv">
              <dt>Buy / Rent</dt><dd>{selected.buy_rent || '—'}</dd>
              <dt>Location</dt><dd>{selected.location || '—'}</dd>
              <dt>Budget</dt><dd>{selected.budget || '—'}</dd>
              <dt>Property type</dt><dd>{selected.property_type || '—'}</dd>
              <dt>Bedrooms</dt><dd>{selected.bedrooms ?? '—'}</dd>
              <dt>Bathrooms</dt><dd>{selected.bathrooms ?? '—'}</dd>
              <dt>Purpose</dt><dd>{selected.investment_purpose || '—'}</dd>
              <dt>Timeline</dt><dd>{selected.timeline || '—'}</dd>
            </dl>

            <div className="subhead">Move through pipeline</div>
            <div className="status-row">
              {STATUSES.slice(1).map((s) => (
                <button
                  key={s}
                  className={`chip ${selected.status === s ? 'on' : ''}`}
                  onClick={() => setStatus(selected, s)}
                >
                  {STATUS_LABEL[s]}
                </button>
              ))}
            </div>

            <div className="subhead">Notes</div>
            <textarea
              className="notes"
              value={notesDraft}
              onChange={(e) => setNotesDraft(e.target.value)}
              placeholder="Add follow-up notes…"
            />
            <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
              <button className="btn btn-dark btn-sm" onClick={saveLead} disabled={saving}>
                {saving ? 'Saving…' : 'Save notes'}
              </button>
              <button className="btn btn-ghost btn-sm" onClick={() => setSelected(null)}>
                Close
              </button>
            </div>

            {convForLead && (
              <>
                <div className="subhead">Conversation ({convForLead.messages?.length || 0} messages)</div>
                {(convForLead.messages || []).slice(0, 12).map((m) => (
                  <div className="mini-msg" key={m.id}>
                    <b>{m.role === 'user' ? 'Customer' : 'AI'}</b>
                    <div>{m.content}</div>
                  </div>
                ))}
                <button
                  className="btn btn-ghost btn-sm"
                  style={{ marginTop: 8 }}
                  onClick={() => navigate(`/chat/${convForLead.id}`)}
                >
                  Reopen this conversation →
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
