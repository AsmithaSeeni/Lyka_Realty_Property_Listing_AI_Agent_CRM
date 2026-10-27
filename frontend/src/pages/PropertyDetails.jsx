import React from 'react'
import { useNavigate, useParams, Link, useLocation } from 'react-router-dom'
import api from '../api.js'
import { hasInAppHistory } from '../nav.js'
import { priceLabel, DemoBadge, PURPOSE_LABEL } from '../components/PropBits.jsx'

/* Phase 6 — one detail component for the two established URL aliases:
   - /properties/:id  → DB-backed Lyka listing (approved + available only,
     loaded via GET /api/properties/record/{id}); used by the browse page
     and the CRM's "Open listing" links.
   - /property/:id    → legacy UAE dataset listing (unchanged behavior).
   The id spaces genuinely collide (dataset ids 1..25,082 vs record ids
   1..23), so the URL alias is what selects the space. */
export default function PropertyDetails() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const isRecord = pathname.startsWith('/properties/')
  const space = isRecord ? 'record' : 'dataset'
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
  // the browse page (record listings) or the chat (dataset listings).
  const goBack = React.useCallback(() => {
    if (hasInAppHistory()) navigate(-1)
    else navigate(isRecord ? '/properties' : '/chat')
  }, [navigate, isRecord])

  React.useEffect(() => {
    setLoading(true)
    setError(null)
    const req = isRecord ? api.getPropertyRecord(id) : api.getProperty(id)
    req
      .then(setProp)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [id, isRecord])

  // Signed-in? (save is an account feature; guests get a gentle nudge)
  React.useEffect(() => {
    api
      .customerMe()
      .then((me) => {
        setCustomer(me)
        if (me.authenticated) {
          api
            .savedProperties()
            .then((r) =>
              setSaved(
                r.results.some(
                  (p) =>
                    (p.source || 'dataset') === space &&
                    String(p.property_id) === String(id),
                ),
              ),
            )
            .catch(() => {})
        }
      })
      .catch(() => {})
  }, [id, space])

  const toggleSave = async () => {
    if (!customer) return
    if (!customer.authenticated) {
      // Non-blocking prompt — never a forced login wall
      setKeepPrompt(true)
      return
    }
    try {
      if (saved) {
        await api.unsaveProperty(Number(id), space)
        setSaved(false)
      } else {
        await api.saveProperty(Number(id), space)
        setSaved(true)
      }
    } catch {
      /* keep UI unchanged on failure */
    }
  }

  const askLykAI = () =>
    navigate(isRecord ? `/chat?ref=${id}&src=record` : `/chat?ref=${id}`)

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
        {isRecord ? (
          <>
            <span className="eyebrow">Listing</span>
            <h1>Listing not available</h1>
            <div className="notice">
              This listing doesn’t exist or is no longer publicly available.
              Browse the current listings instead, or ask LykAI to find
              alternatives.
            </div>
            <div style={{ display: 'flex', gap: 10, marginTop: 14 }}>
              <button className="btn gold btn-sm" onClick={() => navigate('/properties')}>
                Browse properties
              </button>
              <button className="btn ghost btn-sm" onClick={() => navigate('/chat')}>
                <span className="ico">→</span> Ask LykAI
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="notice">⚠️ {error || 'Property not found'}</div>
            <button className="btn btn-ghost btn-sm" onClick={goBack}>
              ← Go back
            </button>
          </>
        )}
      </div>
    )
  }

  /* ---------------------------------------------------------------
     Guest nudge after tapping Save — dismissible, never blocking.
     The `next` path keeps the visitor in the same id space.
  --------------------------------------------------------------- */
  const nudge = keepPrompt && !customer?.authenticated && (
    <div className="keep-prompt">
      <b>Want to keep your LykAI conversations and saved properties?</b>
      <div className="keep-prompt__btns">
        <Link className="btn gold btn-sm" to={`/login?next=${pathname}`}>
          Sign In
        </Link>
        <Link className="btn dark btn-sm" to={`/register?next=${pathname}`}>
          Create Account
        </Link>
        <button className="btn ghost btn-sm" onClick={() => setKeepPrompt(false)}>
          Continue as Guest
        </button>
      </div>
    </div>
  )

  const askBar = (
    <div className="ask-lykai-bar">
      <button className="btn gold btn-block" onClick={askLykAI}>
        <span className="ico">→</span> Ask LykAI about this property
      </button>
    </div>
  )

  /* ================= DB-backed record listing (Phase 6) ================= */
  if (isRecord) {
    const type = prop.property_type || 'Property'
    const emoji =
      /villa/i.test(type) ? '🏡' :
      /townhouse/i.test(type) ? '🏘️' :
      /penthouse/i.test(type) ? '🌆' :
      /plot|land/i.test(type) ? '🗺️' : '🏢'
    const amenities = Array.isArray(prop.amenities) ? prop.amenities : []
    const highlights = String(prop.highlights || '')
      .split(/[;,]|\n/)
      .map((h) => h.trim())
      .filter((h) => h.length > 2)

    return (
      <div className="page" style={{ maxWidth: 960 }}>
        <button className="btn ghost btn-sm" onClick={goBack} style={{ marginBottom: 18 }}>
          ← Back to listings
        </button>

        {/* Branded placeholder — the database has no listing photos, and we
            never invent property photographs. */}
        <div className="prop-detail-hero">
          <span>{emoji}</span>
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 14 }}>
          <div>
            <span className="eyebrow">📍 {prop.location || 'UAE'}</span>
            <div className="prop-badges" style={{ marginTop: 8 }}>
              {PURPOSE_LABEL[prop.purpose] && (
                <span className="purpose-tag">{PURPOSE_LABEL[prop.purpose]}</span>
              )}
              <DemoBadge prop={prop} />
            </div>
            <h1 style={{ fontSize: 'clamp(1.6rem, 4vw, 2.2rem)', margin: '12px 0 8px' }}>
              {prop.title || type}
            </h1>
            <div style={{ fontSize: 30, fontWeight: 700, color: 'var(--maroon)' }}>
              {priceLabel(prop)}
            </div>
            <div className="pd-meta">
              Listing #{prop.id} · {prop.availability === 'available' ? 'Available' : prop.availability || 'Availability not specified'}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            {/* The conversation-first way back: returns to LykAI with this
                listing already in context (no id, no new search) */}
            <button className="btn gold btn-sm" onClick={askLykAI}>
              <span className="ico">→</span> Ask LykAI about this property
            </button>
            <button className="btn ghost btn-sm" onClick={toggleSave}>
              {saved ? '♥ Saved' : '♡ Save'}
            </button>
          </div>
        </div>

        {nudge}

        <div className="spec-grid" style={{ marginTop: 26 }}>
          <div className="spec">
            <div className="k">Bedrooms</div>
            <div className="v">🛏 {prop.bedrooms ?? 'Not provided'}</div>
          </div>
          <div className="spec">
            <div className="k">Bathrooms</div>
            <div className="v">🛁 {prop.bathrooms ?? 'Not provided'}</div>
          </div>
          <div className="spec">
            <div className="k">Area</div>
            <div className="v">📐 {prop.area != null ? `${prop.area.toLocaleString()} ${prop.area_unit || 'sqft'}` : 'Not provided'}</div>
          </div>
          <div className="spec">
            <div className="k">Type</div>
            <div className="v">{type}</div>
          </div>
          <div className="spec">
            <div className="k">Purpose</div>
            <div className="v">{PURPOSE_LABEL[prop.purpose] || 'Not specified'}</div>
          </div>
          <div className="spec">
            <div className="k">Listing ID</div>
            <div className="v">#{prop.id}</div>
          </div>
        </div>

        {prop.description && (
          <>
            <div className="subhead">About this property</div>
            <p style={{ lineHeight: 1.8, color: 'var(--ink)' }}>{prop.description}</p>
          </>
        )}

        {amenities.length > 0 && (
          <>
            <div className="subhead">Amenities</div>
            <div className="amen-row">
              {amenities.map((a, i) => (
                <span className="amen-chip" key={i}>{a}</span>
              ))}
            </div>
          </>
        )}

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

        {askBar}

        <div className="notice" style={{ background: 'var(--paper)', borderColor: 'var(--line)', color: 'var(--muted)' }}>
          ℹ️ {prop.is_demo
            ? 'This is a Fictional Demo Listing — synthetic demo data, NOT a real or currently available Lyka Realty property. '
            : ''}Availability and pricing are subject to confirmation by a Lyka Realty consultant.
        </div>
      </div>
    )
  }

  /* ================= Legacy dataset listing (unchanged) ================= */
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
          <button className="btn gold btn-sm" onClick={askLykAI}>
            <span className="ico">→</span> Ask LykAI about this property
          </button>
          <button className="btn ghost btn-sm" onClick={toggleSave}>
            {saved ? '♥ Saved' : '♡ Save'}
          </button>
        </div>
      </div>

      {nudge}

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
      {askBar}

      <div className="notice" style={{ background: 'var(--paper)', borderColor: 'var(--line)', color: 'var(--muted)' }}>
        ℹ️ Details shown above come directly from the UAE property dataset. Availability
        and pricing are subject to confirmation by a Lyka Realty consultant.
      </div>
    </div>
  )
}
