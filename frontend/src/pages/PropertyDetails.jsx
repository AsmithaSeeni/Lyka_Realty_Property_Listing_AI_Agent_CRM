import React from 'react'
import { useNavigate, useParams, Link } from 'react-router-dom'
import api from '../api.js'
import { hasInAppHistory } from '../nav.js'

export default function PropertyDetails() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [prop, setProp] = React.useState(null)
  const [error, setError] = React.useState(null)
  const [loading, setLoading] = React.useState(true)
  const [customer, setCustomer] = React.useState(null)
  const [saved, setSaved] = React.useState(false)
  const [keepPrompt, setKeepPrompt] = React.useState(false) // guest save nudge

  // True browser "back" only works when this tab actually navigated here from
  // another page of the app. Property pages are also reached from the agent
  // CRM ("Open listing ↗" opens a new tab), hard refreshes, or typed URLs —
  // in those cases navigate(-1) would silently do nothing, so fall back to
  // the chat (LykAI resumes the active conversation from there).
  const goBack = React.useCallback(() => {
    if (hasInAppHistory()) navigate(-1)
    else navigate('/chat')
  }, [navigate])

  React.useEffect(() => {
    setLoading(true)
    setError(null)
    api
      .getProperty(id)
      .then(setProp)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [id])

  // Signed-in? (save is an account feature; guests get a gentle nudge)
  React.useEffect(() => {
    api
      .customerMe()
      .then((me) => {
        setCustomer(me)
        if (me.authenticated) {
          api
            .savedProperties()
            .then((r) => setSaved(r.results.some((p) => String(p.property_id) === String(id))))
            .catch(() => {})
        }
      })
      .catch(() => {})
  }, [id])

  const toggleSave = async () => {
    if (!customer) return
    if (!customer.authenticated) {
      // Non-blocking prompt — never a forced login wall
      setKeepPrompt(true)
      return
    }
    try {
      if (saved) {
        await api.unsaveProperty(Number(id))
        setSaved(false)
      } else {
        await api.saveProperty(Number(id))
        setSaved(true)
      }
    } catch {
      /* keep UI unchanged on failure */
    }
  }

  if (loading) {
    return (
      <div className="page">
        <div className="empty">Loading property…</div>
      </div>
    )
  }

  if (error || !prop) {
    return (
      <div className="page">
        <div className="notice">⚠️ {error || 'Property not found'}</div>
        <button className="btn btn-ghost btn-sm" onClick={goBack}>
          ← Go back
        </button>
      </div>
    )
  }

  const beds = prop.no__of__beds ?? '—'
  const baths = prop.no_of_baths ?? '—'
  const type = prop.property_type || 'Property'
  const emoji =
    /villa/i.test(type) ? '🏡' :
    /townhouse/i.test(type) ? '🏘️' :
    /penthouse/i.test(type) ? '🌆' :
    /plot|land/i.test(type) ? '🗺️' : '🏢'

  const highlights = String(prop.highlights || '')
    .split(/[;,]|\n/)
    .map((h) => h.trim())
    .filter((h) => h.length > 2)

  return (
    <div className="page" style={{ maxWidth: 960 }}>
      <button className="btn ghost btn-sm" onClick={goBack} style={{ marginBottom: 18 }}>
        ← Back
      </button>

      <div className="prop-detail-hero">
        <span>{emoji}</span>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 14 }}>
        <div>
          <span className="eyebrow">📍 {prop.location || 'UAE'}</span>
          <h1 style={{ fontSize: 'clamp(1.8rem, 4vw, 2.4rem)', margin: '14px 0 8px' }}>
            {type} — Listing #{prop.property_id}
          </h1>
          <div style={{ fontSize: 30, fontWeight: 700, color: 'var(--maroon)' }}>
            AED {prop.price}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {/* The conversation-first way back: returns to LykAI with this
              listing already in context (no id, no new search) */}
          <button
            className="btn gold btn-sm"
            onClick={() => navigate(`/chat?ref=${prop.property_id}`)}
          >
            <span className="ico">→</span> Ask LykAI about this property
          </button>
          <button className="btn ghost btn-sm" onClick={toggleSave}>
            {saved ? '♥ Saved' : '♡ Save'}
          </button>
        </div>
      </div>

      {/* Guest nudge after tapping Save — dismissible, never blocking */}
      {keepPrompt && !customer?.authenticated && (
        <div className="keep-prompt">
          <b>Want to keep your LykAI conversations and saved properties?</b>
          <div className="keep-prompt__btns">
            <Link className="btn gold btn-sm" to={`/signin?mode=login&next=/property/${prop.property_id}`}>
              Sign In
            </Link>
            <Link className="btn dark btn-sm" to={`/signin?mode=register&next=/property/${prop.property_id}`}>
              Create Account
            </Link>
            <button className="btn ghost btn-sm" onClick={() => setKeepPrompt(false)}>
              Continue as Guest
            </button>
          </div>
        </div>
      )}

      <div className="spec-grid" style={{ marginTop: 26 }}>
        <div className="spec">
          <div className="k">Bedrooms</div>
          <div className="v">🛏 {beds}</div>
        </div>
        <div className="spec">
          <div className="k">Bathrooms</div>
          <div className="v">🛁 {baths}</div>
        </div>
        <div className="spec">
          <div className="k">Area</div>
          <div className="v">📐 {prop.area || 'Not provided'}</div>
        </div>
        <div className="spec">
          <div className="k">Type</div>
          <div className="v">{type}</div>
        </div>
        <div className="spec">
          <div className="k">Listing ID</div>
          <div className="v">#{prop.property_id}</div>
        </div>
      </div>

      {highlights.length > 0 && (
        <>
          <div className="subhead">Highlights</div>
          <div className="highlight-box">
            <ul style={{ margin: 0, paddingLeft: 20, lineHeight: 1.9 }}>
              {highlights.map((h, i) => (
                <li key={i}>{h}</li>
              ))}
            </ul>
          </div>
        </>
      )}

      {/* Sticky, always-reachable path back into the conversation (mobile too) */}
      <div className="ask-lykai-bar">
        <button
          className="btn gold btn-block"
          onClick={() => navigate(`/chat?ref=${prop.property_id}`)}
        >
          <span className="ico">→</span> Ask LykAI about this property
        </button>
      </div>

      <div className="notice" style={{ background: 'var(--paper)', borderColor: 'var(--line)', color: 'var(--muted)' }}>
        ℹ️ Details shown above come directly from the UAE property dataset. Availability
        and pricing are subject to confirmation by a Lyka Realty consultant.
      </div>
    </div>
  )
}
