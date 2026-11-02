import React from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api.js'
import { statusLabel, fmtDate } from './AgentLeads.jsx'
import ErrorBoundary from '../components/ui/ErrorBoundary.jsx'
import { adaptProperty } from '../utils/propertyAdapter.js'

/**
 * /agent/conversations — business review of ALL customer↔AI threads in this
 * agent's scope. Search by customer name / phone / email / lead ID /
 * conversation ID, or filter by date range. Click a row to read the full
 * thread in a drawer. Includes real-time 3-second incremental synchronization.
 */
function AgentConversationsView() {
  const navigate = useNavigate()
  const [rows, setRows] = React.useState([])
  const [total, setTotal] = React.useState(0)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState(null)
  const [reload, setReload] = React.useState(0) // bump to retry after an error
  const [lastSyncTime, setLastSyncTime] = React.useState(null)

  const [q, setQ] = React.useState('')
  const [dateFrom, setDateFrom] = React.useState('')
  const [dateTo, setDateTo] = React.useState('')

  const [thread, setThread] = React.useState(null) // full conversation payload
  const [threadLoading, setThreadLoading] = React.useState(false)

  const hasFilters = Boolean(q || dateFrom || dateTo)
  const inFlightRef = React.useRef(false)
  const threadRef = React.useRef(thread)

  React.useEffect(() => {
    threadRef.current = thread
  }, [thread])

  // Initial and query-driven fetch
  React.useEffect(() => {
    const t = setTimeout(() => {
      let cancelled = false
      setLoading(true)
      setError(null)
      api
        .agentConversations({ q, date_from: dateFrom, date_to: dateTo, limit: 200 })
        .then((r) => {
          if (cancelled) return
          setRows(Array.isArray(r.results) ? r.results : [])
          setTotal(r.total || 0)
          setLastSyncTime(new Date())
          setError(null)
        })
        .catch((e) => {
          if (cancelled) return
          setRows([])
          setTotal(0)
          setError(e.message || 'Could not load conversations.')
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
      return () => {
        cancelled = true
      }
    }, 250)
    return () => clearTimeout(t)
  }, [q, dateFrom, dateTo, reload])

  // Real-time incremental synchronization: polls every 3 seconds when document is visible
  React.useEffect(() => {
    const interval = setInterval(async () => {
      if (document.hidden || inFlightRef.current) return
      inFlightRef.current = true
      try {
        const r = await api.agentConversations({
          q: q || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          limit: 200,
        })
        if (r && Array.isArray(r.results)) {
          setRows((prev) => {
            const prevSignature = prev.map((x) => `${x.id}:${x.updated_at}:${x.message_count}`).join('|')
            const nextSignature = r.results.map((x) => `${x.id}:${x.updated_at}:${x.message_count}`).join('|')
            if (prevSignature !== nextSignature) {
              return r.results
            }
            return prev
          })
          setTotal(r.total || 0)
          setLastSyncTime(new Date())
        }

        // If a thread drawer is currently open, silently synchronize its messages too
        const activeId = threadRef.current?.row?.id || threadRef.current?.conversation?.id
        if (activeId) {
          try {
            const data = await api.agentConversation(activeId)
            if (data && Array.isArray(data.messages)) {
              setThread((curr) => {
                if (!curr || (curr.row?.id !== activeId && curr.conversation?.id !== activeId)) return curr
                const currCount = curr.messages?.length || 0
                if (currCount !== data.messages.length) {
                  return {
                    ...curr,
                    messages: data.messages,
                    conversation: data.conversation || curr.conversation,
                    row: data.conversation || curr.row,
                    lead: data.lead !== undefined ? data.lead : curr.lead,
                    property_recommendations: Array.isArray(data.property_recommendations)
                      ? data.property_recommendations
                      : curr.property_recommendations,
                  }
                }
                return curr
              })
            }
          } catch {
            // Non-blocking for background sync
          }
        }
      } catch {
        // Non-blocking on transient background errors
      } finally {
        inFlightRef.current = false
      }
    }, 3000)

    return () => clearInterval(interval)
  }, [q, dateFrom, dateTo])

  // Escape closes the thread drawer
  React.useEffect(() => {
    if (!thread) return
    const onKey = (e) => e.key === 'Escape' && setThread(null)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [thread])

  const openThread = async (row) => {
    if (!row || !row.id) return
    setThreadLoading(true)
    setThread({ loading: true, row, conversation: row })
    try {
      const data = await api.agentConversation(row.id)
      setThread({
        ...data,
        row: data.conversation || row,
        conversation: data.conversation || row,
        messages: Array.isArray(data.messages) ? data.messages : [],
        lead: data.lead || null,
        property_recommendations: Array.isArray(data.property_recommendations)
          ? data.property_recommendations
          : [],
      })
    } catch (e) {
      setThread({
        error: e.message || 'Failed to load conversation details.',
        row,
        conversation: row,
      })
    } finally {
      setThreadLoading(false)
    }
  }

  const activeConv = thread?.conversation || thread?.row || {}

  return (
    <div>
      <div className="ax-toolbar" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
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
          <span className="ax-count">
            {error ? '—' : `${total} conversation${total === 1 ? '' : 's'}`}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div className="ax-live-badge" title="Real-time incremental synchronization active (3s heartbeat)">
            <span className="ax-live-pulse-dot" />
            <span>Live Syncing</span>
          </div>
          <button
            className="btn btn-sm btn-ghost"
            style={{ fontSize: 12, padding: '4px 8px' }}
            onClick={() => setReload((n) => n + 1)}
            title="Force reload list"
          >
            ↻ Refresh
          </button>
        </div>
      </div>

      {/* Errors are loud and retryable — never masquerade as an empty list */}
      {error && (
        <div className="ax-empty ax-error" role="alert" style={{ textAlign: 'left', padding: '1.25rem' }}>
          <div style={{ fontWeight: 600, color: 'var(--crm-text-danger, #b91c1c)', marginBottom: 6 }}>
            ⚠ Could not load conversations: {error}
          </div>
          <div style={{ fontSize: '0.85rem', color: 'var(--crm-text-secondary, #64748b)', marginBottom: 12 }}>
            Please ensure you are signed in with an authorized staff account (holding <code>conversations.read_authorized</code> or <code>conversations.read_all</code>) and your backend server is active.
          </div>
          <button className="btn btn-sm btn-primary" onClick={() => setReload((n) => n + 1)}>
            Retry loading
          </button>
        </div>
      )}

      <div className="ax-table ax-table--conv">
        <div className="ax-table__head">
          <span>Conv.</span>
          <span>Customer</span>
          <span>Last message</span>
          <span>Lead status</span>
          <span>Last interaction</span>
          <span></span>
        </div>

        {loading && rows.length === 0 && !error && (
          <div className="ax-empty sm"><div className="ax-spin" /> Loading conversations…</div>
        )}
        {!loading && rows.length === 0 && !error && !hasFilters && (
          <div className="ax-empty sm">
            No conversations yet — they will appear here automatically once
            customers start chatting with LykAI.
          </div>
        )}
        {!loading && rows.length === 0 && !error && hasFilters && (
          <div className="ax-empty sm">
            No conversations match your search.
            <button
              className="ax-link"
              style={{ marginLeft: 10 }}
              onClick={() => { setQ(''); setDateFrom(''); setDateTo('') }}
            >
              Clear filters
            </button>
          </div>
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
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <h2 style={{ margin: 0 }}>Conversation #{activeConv.id ?? '—'}</h2>
                  <span className="ax-live-badge" style={{ fontSize: 11, padding: '2px 8px' }}>
                    <span className="ax-live-pulse-dot" />
                    <span>Live</span>
                  </span>
                </div>
                <p style={{ margin: '4px 0 0 0' }}>
                  {activeConv.customer_name || 'Anonymous visitor'}
                  {activeConv.customer_phone ? ` · ${activeConv.customer_phone}` : ''}
                  {activeConv.lead_id ? ` · Lead #${activeConv.lead_id}` : ' · No linked lead'}
                </p>
              </div>
              <button className="ax-close" onClick={() => setThread(null)} aria-label="Close">✕</button>
            </div>

            <div className="ax-drawer__body">
              {thread.loading && <div className="ax-empty sm"><div className="ax-spin" /> Loading thread…</div>}
              {thread.error && (
                <div className="ax-empty sm" style={{ color: 'var(--crm-text-danger, #b91c1c)' }}>
                  <div>⚠ {thread.error}</div>
                  <div style={{ marginTop: 10, display: 'flex', gap: 8 }}>
                    <button className="btn btn-sm" onClick={() => openThread(activeConv)}>Retry</button>
                    <button className="btn btn-sm btn-ghost" onClick={() => setThread(null)}>Close</button>
                  </div>
                </div>
              )}

              {thread.messages && !thread.loading && (
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
                        {thread.property_recommendations.map((r, i) => {
                          const ap = adaptProperty(r)
                          return (
                          <div className="ax-prop" key={`${r.property_id}-${i}`}>
                            <div className="ax-prop__top">
                              <span className="ax-prop__emoji">{ap.fallbackEmoji}</span>
                              <span className="ax-prop__price">{ap.formattedPrice}</span>
                            </div>
                            <b className="ax-prop__type">{ap.propertyType} <i className="ax-id">#{r.property_id}</i></b>
                            <div className="ax-prop__loc">📍 {ap.location}</div>
                            <div className="ax-prop__specs">
                              <span>🛏 {ap.bedroomLabel}</span>
                              <span>🛁 {ap.bathroomLabel}</span>
                              <span>📐 {ap.formattedArea}</span>
                            </div>
                          </div>
                        )}) }
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

export default function AgentConversations() {
  return (
    <ErrorBoundary title="Conversations Module">
      <AgentConversationsView />
    </ErrorBoundary>
  )
}
