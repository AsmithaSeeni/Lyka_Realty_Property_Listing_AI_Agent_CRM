import React from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api.js'
import { statusLabel, fmtDate } from './AgentLeads.jsx'

/**
 * /agent/conversations — business review of ALL customer↔AI threads in this
 * agent's scope. Search by customer name / phone / email / lead ID /
 * conversation ID, or filter by date range. Click a row to read the full
 * thread in a drawer.
 */
export default function AgentConversations() {
  const navigate = useNavigate()
  const [rows, setRows] = React.useState([])
  const [total, setTotal] = React.useState(0)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState(null)

  const [q, setQ] = React.useState('')
  const [dateFrom, setDateFrom] = React.useState('')
  const [dateTo, setDateTo] = React.useState('')

  const [thread, setThread] = React.useState(null) // full conversation payload
  const [threadLoading, setThreadLoading] = React.useState(false)

  React.useEffect(() => {
    const t = setTimeout(() => {
      setLoading(true)
      api
        .agentConversations({ q, date_from: dateFrom, date_to: dateTo })
        .then((r) => {
          setRows(r.results)
          setTotal(r.total)
          setError(null)
        })
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false))
    }, 250)
    return () => clearTimeout(t)
  }, [q, dateFrom, dateTo])

  // Escape closes the thread drawer
  React.useEffect(() => {
    if (!thread) return
    const onKey = (e) => e.key === 'Escape' && setThread(null)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [thread])

  const openThread = async (row) => {
    setThreadLoading(true)
    setThread({ loading: true, row })
    try {
      const data = await api.agentConversation(row.id)
      setThread(data)
    } catch (e) {
      setThread({ error: e.message, row })
    } finally {
      setThreadLoading(false)
    }
  }

  return (
    <div>
      <div className="ax-toolbar">
        <input
          className="ax-input ax-input--search"
          placeholder="Search customer, phone, email, lead # or conversation #…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <label className="ax-inline-label">
          From
          <input className="ax-input" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </label>
        <label className="ax-inline-label">
          To
          <input className="ax-input" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </label>
        <span className="ax-count">{total} conversation{total === 1 ? '' : 's'}</span>
      </div>

      {error && <div className="ax-empty">⚠ {error}</div>}

      <div className="ax-table ax-table--conv">
        <div className="ax-table__head">
          <span>Conv.</span>
          <span>Customer</span>
          <span>Last message</span>
          <span>Lead status</span>
          <span>Last interaction</span>
          <span></span>
        </div>

        {loading && rows.length === 0 && (
          <div className="ax-empty sm"><div className="ax-spin" /> Loading conversations…</div>
        )}
        {!loading && rows.length === 0 && (
          <div className="ax-empty sm">No conversations match your search.</div>
        )}

        {rows.map((c) => (
          <div
            className="ax-table__row"
            key={c.id}
            role="button"
            tabIndex={0}
            onClick={() => openThread(c)}
            onKeyDown={(e) => e.key === 'Enter' && openThread(c)}
          >
            <span className="ax-cell-strong"><i className="ax-id">#{c.id}</i></span>
            <span className="ax-cell-strong">
              {c.customer_name || 'Anonymous visitor'}
              <br />
              <small>{c.customer_phone || '—'} · {c.customer_email || '—'}</small>
            </span>
            <span className="ax-cell-sub ax-ellipsis">{c.last_message_preview || '—'}</span>
            <span>
              {c.lead_status
                ? <em className={`ax-badge ${c.lead_status}`}>{statusLabel(c.lead_status)}</em>
                : <span className="ax-muted">no lead</span>}
            </span>
            <span>{fmtDate(c.updated_at)}</span>
            <span className="ax-link">Open →</span>
          </div>
        ))}
      </div>

      {/* ---------------- Thread drawer ---------------- */}
      {thread && (
        <div className="ax-drawer-bg" onClick={(e) => e.target === e.currentTarget && setThread(null)}>
          <div className="ax-drawer">
            <div className="ax-drawer__head">
              <div>
                <h2>Conversation #{thread.row.id}</h2>
                <p>
                  {thread.row.customer_name || 'Anonymous visitor'}
                  {thread.row.lead_id ? ` · Lead #${thread.row.lead_id}` : ' · No linked lead'}
                </p>
              </div>
              <button className="ax-close" onClick={() => setThread(null)} aria-label="Close">✕</button>
            </div>

            <div className="ax-drawer__body">
              {thread.loading && <div className="ax-empty sm"><div className="ax-spin" /> Loading thread…</div>}
              {thread.error && <div className="ax-empty sm">⚠ {thread.error}</div>}

              {thread.messages && (
                <>
                  <div className="ax-thread">
                    {thread.messages.length === 0 && <div className="ax-empty sm">Empty conversation.</div>}
                    {thread.messages.map((m) => (
                      <div className={`ax-msg ${m.role}`} key={m.id}>
                        <div className="ax-msg__who">
                          <b>{m.role === 'user' ? 'Customer' : 'LykAI'}</b>
                          <span>
                            {m.created_at ? new Date(m.created_at).toLocaleString([], {
                              day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
                            }) : ''}
                            {m.message_type === 'voice' ? ' · 🎙 voice' : ' · 💬 text'}
                            {m.detected_language && m.detected_language !== 'en' ? ` · ${m.detected_language}` : ''}
                          </span>
                        </div>
                        <div className="ax-msg__bubble">{m.content}</div>
                      </div>
                    ))}
                  </div>

                  {thread.lead && (
                    <div className="ax-drawer__lead">
                      <b>Lead #{thread.lead.id} · {statusLabel(thread.lead.status)}</b>
                      <span>{thread.lead.location} · {thread.lead.budget} · {thread.lead.phone}</span>
                      <button
                        className="ax-link"
                        onClick={() => navigate(`/agent/leads/${thread.lead.id}`)}
                      >
                        Open lead →
                      </button>
                    </div>
                  )}

                  {thread.property_recommendations?.length > 0 && (
                    <>
                      <div className="ax-subhead">Properties recommended in this thread</div>
                      <div className="ax-props">
                        {thread.property_recommendations.map((r, i) => (
                          <div className="ax-prop" key={`${r.property_id}-${i}`}>
                            <div className="ax-prop__top">
                              <span className="ax-prop__emoji">🏢</span>
                              <span className="ax-prop__price">AED {r.price}</span>
                            </div>
                            <b className="ax-prop__type">{r.property_type || 'Property'} <i className="ax-id">#{r.property_id}</i></b>
                            <div className="ax-prop__loc">📍 {r.location || 'UAE'}</div>
                            <div className="ax-prop__specs">
                              <span>🛏 {r.bedrooms ?? '—'}</span>
                              <span>🛁 {r.bathrooms ?? '—'}</span>
                              <span>📐 {r.area || '—'}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
