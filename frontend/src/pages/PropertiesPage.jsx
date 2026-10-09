import React from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api.js'

const TYPES = [
  '', 'apartment', 'villa', 'townhouse', 'penthouse', 'studio',
  'hotel apartment', 'plot', 'compound',
]
const BEDS = ['', '1', '2', '3', '4', '5']

/* Manual browse is the secondary path — every card still leads back to LykAI. */
function BrowseCard({ prop, onOpen, onAsk }) {
  const beds = prop.no__of__beds ?? '—'
  const baths = prop.no_of_baths ?? '—'
  const type = prop.property_type || 'Property'
  const loc = prop.location || ''
  const emoji =
    /villa/i.test(type) ? '🏡' :
    /townhouse/i.test(type) ? '🏘️' :
    /penthouse/i.test(type) ? '🌆' :
    /studio/i.test(String(beds)) ? '🏠' :
    /plot|land/i.test(type) ? '🗺️' : '🏢'

  return (
    <article className="prop-card browse-card">
      <div className="prop-thumb">
        <span>{emoji}</span>
        <span className="loc">📍 {loc}</span>
      </div>
      <div className="prop-body">
        <div className="prop-price">AED {prop.price}</div>
        <div className="prop-title">{type} · {loc}</div>
        <div className="prop-specs">
          <span>🛏 {beds}</span>
          <span>🛁 {baths}</span>
          <span>📐 {prop.area || '—'}</span>
        </div>
        <div className="browse-ctas">
          <button className="btn gold btn-sm" onClick={() => onOpen(prop)}>
            View Property
          </button>
          <button className="btn ghost btn-sm" onClick={() => onAsk(prop)}>
            Ask LykAI
          </button>
        </div>
      </div>
    </article>
  )
}

export default function PropertiesPage() {
  const navigate = useNavigate()
  const [location, setLocation] = React.useState('')
  const [type, setType] = React.useState('')
  const [beds, setBeds] = React.useState('')
  const [items, setItems] = React.useState([])
  const [total, setTotal] = React.useState(0)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState(null)

  const PAGE = 24
  const [offset, setOffset] = React.useState(0)

  const fetchPage = React.useCallback(
    async (append, off) => {
      setLoading(true)
      setError(null)
      try {
        const res = await api.searchProperties({
          location: location.trim(),
          property_type: type,
          min_bedrooms: beds,
          limit: PAGE,
          offset: off,
        })
        setTotal(res.total ?? 0)
        setItems((prev) => (append ? [...prev, ...res.results] : res.results))
      } catch (e) {
        setError(e.message || 'Could not load properties.')
      } finally {
        setLoading(false)
      }
    },
    [location, type, beds],
  )

  // Initial load + reload on filter change (reset paging)
  React.useEffect(() => {
    setOffset(0)
    fetchPage(false, 0)
  }, [fetchPage])

  const askLykAI = (prop) => navigate(`/chat?ref=${prop.property_id}`)
  const openProp = (prop) => navigate(`/property/${prop.property_id}`)

  return (
    <div className="page" style={{ maxWidth: 1120 }}>
      <div className="page-head">
        <div className="row">
          <div>
            <span className="eyebrow">Browse</span>
            <h1>Properties</h1>
            <p>
              Prefer to look around yourself? Browse UAE listings here — or tell
              LykAI what you want and let the concierge find matches for you.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <button className="btn gold btn-sm" onClick={() => navigate('/chat')}>
              <span className="ico">→</span> Talk to LykAI
            </button>
          </div>
        </div>
      </div>

      {/* Light filters — browsing, not a separate search workflow */}
      <div className="browse-filters">
        <input
          type="text"
          placeholder="Location (e.g. Dubai Marina)"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && fetchPage(false, 0)}
        />
        <select value={type} onChange={(e) => setType(e.target.value)}>
          {TYPES.map((t) => (
            <option key={t} value={t}>{t ? t[0].toUpperCase() + t.slice(1) : 'Any type'}</option>
          ))}
        </select>
        <select value={beds} onChange={(e) => setBeds(e.target.value)}>
          {BEDS.map((b) => (
            <option key={b} value={b}>{b ? `${b}+ beds` : 'Any beds'}</option>
          ))}
        </select>
        <button className="btn dark btn-sm" onClick={() => fetchPage(false, 0)}>
          Apply
        </button>
      </div>

      <div className="browse-meta">
        {loading && !items.length
          ? 'Loading properties…'
          : `${total.toLocaleString()} propert${total === 1 ? 'y' : 'ies'} found`}
      </div>

      {error && <div className="notice">⚠️ {error}</div>}

      <div className="browse-grid">
        {items.map((p, i) => (
          <BrowseCard
            key={`${p.property_id}-${i}`}
            prop={p}
            onOpen={openProp}
            onAsk={askLykAI}
          />
        ))}
      </div>

      {!loading && items.length === 0 && !error && (
        <div className="empty">
          <div className="big">🔍</div>
          No properties match these filters.
          <div style={{ marginTop: 16 }}>
            <button className="btn gold btn-sm" onClick={() => navigate('/chat')}>
              <span className="ico">→</span> Ask LykAI instead
            </button>
          </div>
        </div>
      )}

      {items.length < total && (
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: 26 }}>
          <button
            className="btn ghost"
            disabled={loading}
            onClick={() => {
              const next = offset + PAGE
              setOffset(next)
              fetchPage(true, next)
            }}
          >
            {loading ? 'Loading…' : 'Show more properties'}
          </button>
        </div>
      )}
    </div>
  )
}
