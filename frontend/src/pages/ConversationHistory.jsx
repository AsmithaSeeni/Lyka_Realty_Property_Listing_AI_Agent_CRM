import React from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api.js'

export default function ConversationHistory() {
  const navigate = useNavigate()
  const [conversations, setConversations] = React.useState([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState(null)
  const [preview, setPreview] = React.useState(null) // conversation detail

  const load = React.useCallback(() => {
    setLoading(true)
    api
      .listConversations()
      .then(setConversations)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  React.useEffect(load, [load])

  // Escape closes the conversation preview drawer
  React.useEffect(() => {
    if (!preview) return
    const onKey = (e) => {
      if (e.key === 'Escape') setPreview(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [preview])

  const openPreview = async (c) => {
    try {
      const full = await api.getConversation(c.id)
      setPreview(full)
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <div className="page">
      <div className="page-head">
        <div className="row">
          <div>
            <span className="eyebrow">Memory</span>
            <h1>Conversation History</h1>
            <p>
              Every chat is stored with timestamps and detected language. Reopen one
              to continue with full context.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <button className="btn ghost btn-sm" onClick={load}>↻ Refresh</button>
            <button className="btn gold btn-sm" onClick={() => navigate('/chat')}>
              <span className="ico">+</span> New chat
            </button>
          </div>
        </div>
      </div>

      {error && <div className="notice">⚠️ {error}</div>}

      {loading && <div className="empty">Loading conversations…</div>}

      {!loading && conversations.length === 0 && !error && (
        <div className="empty">
          <div className="big">💬</div>
          No conversations yet — start one with the AI agent.
          <div style={{ marginTop: 18 }}>
            <button className="btn btn-gold btn-sm" onClick={() => navigate('/chat')}>
              Start chatting
            </button>
          </div>
        </div>
      )}

      {conversations.map((c) => (
        <div
          className="history-item"
          key={c.id}
          role="button"
          tabIndex={0}
          onClick={() => openPreview(c)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              openPreview(c)
            }
          }}
        >
          <div>
            <b>
              {c.customer_name || `Conversation #${c.id}`}
              {'  '}
              <span className={`badge ${c.status}`}>{c.status}</span>
            </b>
            <div className="sub">
              {c.message_count ?? 0} messages
              {c.customer_phone ? ` · 📞 ${c.customer_phone}` : ''}
              {c.customer_email ? ` · ✉️ ${c.customer_email}` : ''}
              {' · '}started {c.created_at ? new Date(c.created_at).toLocaleString() : '—'}
              {' · '}last active {c.updated_at ? new Date(c.updated_at).toLocaleString() : '—'}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 9, flexShrink: 0 }}>
            <button
              className="btn btn-ghost btn-sm"
              onClick={(e) => { e.stopPropagation(); navigate(`/chat/${c.id}`) }}
            >
              Continue →
            </button>
          </div>
        </div>
      ))}

      {/* Preview drawer */}
      {preview && (
        <div className="drawer-bg" onClick={(e) => { if (e.target === e.currentTarget) setPreview(null) }}>
          <div className="drawer">
            <div className="drawer-head">
              <div>
                <h2>Conversation #{preview.id}</h2>
                <span style={{ fontSize: 13, color: 'var(--muted)' }}>
                  {preview.messages?.length || 0} messages ·{' '}
                  {preview.property_recommendations?.length || 0} properties recommended
                </span>
              </div>
              <button className="icon-btn" onClick={() => setPreview(null)}>✕</button>
            </div>

            {preview.customer_name && (
              <dl className="kv">
                <dt>Customer</dt><dd>{preview.customer_name}</dd>
                <dt>Phone</dt><dd>{preview.customer_phone || '—'}</dd>
                <dt>Email</dt><dd>{preview.customer_email || '—'}</dd>
                <dt>Started</dt>
                <dd>{preview.created_at ? new Date(preview.created_at).toLocaleString() : '—'}</dd>
              </dl>
            )}

            <div className="subhead">Messages</div>
            {(preview.messages || []).map((m) => (
              <div className="mini-msg" key={m.id}>
                <b>
                  {m.role === 'user' ? 'Customer' : 'AI'}
                  {m.detected_language && m.detected_language !== 'en'
                    ? ` · ${m.detected_language}`
                    : ''}
                  {' · '}
                  {m.created_at ? new Date(m.created_at).toLocaleTimeString() : ''}
                </b>
                <div>{m.content}</div>
              </div>
            ))}

            {preview.property_recommendations?.length > 0 && (
              <>
                <div className="subhead">Properties shared</div>
                {preview.property_recommendations.map((p, i) => (
                  <div
                    className="mini-msg"
                    key={i}
                    style={{ cursor: 'pointer' }}
                    onClick={() => {
                      setPreview(null)
                      navigate(`/property/${p.property_id}`)
                    }}
                  >
                    <b>AED {p.price} · {p.property_type}</b>
                    <div>
                      {p.location} · 🛏 {p.bedrooms} · 🛁 {p.bathrooms} · 📐 {p.area}
                    </div>
                  </div>
                ))}
              </>
            )}

            <div style={{ display: 'flex', gap: 10, marginTop: 18 }}>
              <button
                className="btn btn-dark btn-sm"
                onClick={() => navigate(`/chat/${preview.id}`)}
              >
                Reopen with full context →
              </button>
              <button className="btn btn-ghost btn-sm" onClick={() => setPreview(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
