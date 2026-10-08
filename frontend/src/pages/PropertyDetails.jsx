import React from 'react'
import { useNavigate, useParams, Link } from 'react-router-dom'
import api from '../api.js'

export default function PropertyDetails() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [prop, setProp] = React.useState(null)
  const [error, setError] = React.useState(null)
  const [loading, setLoading] = React.useState(true)

  React.useEffect(() => {
    setLoading(true)
    setError(null)
    api
      .getProperty(id)
      .then(setProp)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [id])

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
        <button className="btn btn-ghost btn-sm" onClick={() => navigate(-1)}>
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
      <button className="btn ghost btn-sm" onClick={() => navigate(-1)} style={{ marginBottom: 18 }}>
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
        <div style={{ display: 'flex', gap: 10 }}>
          <Link to="/chat" className="btn gold btn-sm">
            <span className="ico">→</span> Ask the AI about this
          </Link>
        </div>
      </div>

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
          <div className="v">📐 {prop.area || '—'}</div>
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

      <div className="notice" style={{ background: 'var(--paper)', borderColor: 'var(--line)', color: 'var(--muted)' }}>
        ℹ️ Details shown above come directly from the UAE property dataset. Availability
        and pricing are subject to confirmation by a Lyka Realty consultant.
      </div>
    </div>
  )
}
