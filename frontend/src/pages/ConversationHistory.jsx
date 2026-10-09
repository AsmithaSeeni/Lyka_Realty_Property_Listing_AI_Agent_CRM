import React from 'react'
import { useNavigate, Link } from 'react-router-dom'
import api from '../api.js'

export default function ConversationHistory() {
  const navigate = useNavigate()
  const [customer, setCustomer] = React.useState(null) // null = still checking
  const [guestViewed, setGuestViewed] = React.useState(false)
  const [conversations, setConversations] = React.useState([])
  const [savedProps, setSavedProps] = React.useState([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState(null)
  const [preview, setPreview] = React.useState(null) // conversation detail

  // Who is here? Guests see the (non-blocking) sign-in explanation first —
  // history is an optional, signed-in feature, never the main experience.
  React.useEffect(() => {
    api.customerMe().then(setCustomer).catch(() => setCustomer(null))
  }, [])

  const load = React.useCallback(() => {
    setLoading(true)
    api
      .listConversations()
      .then(setConversations)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  React.useEffect(load, [load])

  // Saved properties (signed-in customers only)
  React.useEffect(() => {
    if (customer?.authenticated) {
      api.savedProperties().then((r) => setSavedProps(r.results || [])).catch(() => {})
    }
  }, [customer?.authenticated])

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

  const signOut = async () => {
    try {
      await api.customerLogout()
    } catch { /* cookie is gone either way */ }
    window.dispatchEvent(new Event('lyka:customer'))
    navigate('/chat', { replace: true })
  }

  /* -------- still checking identity -------- */
  if (customer === null) {
    return (
      <div className="page">
        <div className="empty">Loading…</div>
      </div>
    )
  }

  /* -------- guest: the optional-sign-in explanation first -------- */
  if (!customer.authenticated && !guestViewed) {
    return (
      <div className="page">
        <div className="keep-prompt keep-prompt--page">
          <span className="eyebrow">Your conversations</span>
          <h2>Want to keep your LykAI conversations and saved properties?</h2>
          <p>
            Your chats with LykAI are saved on this device for now. Sign in (it’s
            free and optional) to keep them, reopen them anywhere and save
            properties you like.
          </p>
          <div className="keep-prompt__btns">
            <Link className="btn gold" to="/signin?mode=login&next=/history">
              Sign In
            </Link>
            <Link className="btn dark" to="/signin?mode=register&next=/history">
              Create Account
            </Link>
            <button className="btn ghost" onClick={() => setGuestViewed(true)}>
              Continue as Guest
            </button>
          </div>
          <Link className="keep-prompt__chat" to="/chat">
            ← Back to LykAI
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <div className="page-head">
        <div className="row">
          <div>
            <span className="eyebrow">{customer.authenticated ? 'Your account' : 'This device'}</span>
            <h1>Your conversations</h1>
            <p>
              {customer.authenticated
                ? `Signed in as ${customer.email}. Reopen any chat with LykAI and continue with full context.`
                : 'Chats saved on this device only — sign in anytime to keep them forever.'}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button className="btn ghost btn-sm" onClick={load}>↻ Refresh</button>
            <button className="btn gold btn-sm" onClick={() => navigate('/chat')}>
              <span className="ico">→</span> Talk to LykAI
            </button>
            {customer.authenticated && (
              <button className="btn dark btn-sm" onClick={signOut}>Sign out</button>
            )}
          </div>
        </div>
      </div>

      {error && <div className="notice">⚠️ {error}</div>}

      {/* Guest banner: one quiet reminder, dismissible by signing in later */}
      {!customer.authenticated && (
        <div className="keep-banner">
          💬 Want to keep these chats?{' '}
          <Link to="/signin?next=/history">Sign in</Link> or{' '}
          <Link to="/signin?mode=register&next=/history">create a free account</Link>.
        </div>
      )}

      {/* Saved properties (signed-in) */}
      {customer.authenticated && savedProps.length > 0 && (
        <>
          <div className="subhead">Saved properties</div>
          <div className="browse-grid" style={{ marginBottom: 26 }}>
            {savedProps.map((p) => (
              <article className="prop-card browse-card" key={p.property_id}>
                <div className="prop-thumb">
                  <span>{/villa/i.test(p.property_type || '') ? '🏡' : '🏢'}</span>
                  <span className="loc">📍 {p.location || ''}</span>
                </div>
                <div className="prop-body">
                  <div className="prop-price">AED {p.price}</div>
                  <div className="prop-title">{p.property_type || 'Property'} · {p.location}</div>
                  <div className="browse-ctas">
                    <button
                      className="btn gold btn-sm"
                      onClick={() => navigate(`/property/${p.property_id}`)}
                    >
                      View Property
                    </button>
                    <button
                      className="btn ghost btn-sm"
                      onClick={() => navigate(`/chat?ref=${p.property_id}`)}
                    >
                      Ask LykAI
                    </button>
                  </div>
                </div>
              </article>
            ))}
          </div>
        </>
      )}

      <div className="subhead">Chats</div>

      {loading && <div className="empty">Loading conversations…</div>}

      {!loading && conversations.length === 0 && !error && (
        <div className="empty">
          <div className="big">💬</div>
          No conversations yet — start one with LykAI.
          <div style={{ marginTop: 18 }}>
            <button className="btn btn-gold btn-sm" onClick={() => navigate('/chat')}>
              Talk to LykAI
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
                  {m.role === 'user' ? 'You' : 'LykAI'}
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
                Reopen with LykAI →
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
