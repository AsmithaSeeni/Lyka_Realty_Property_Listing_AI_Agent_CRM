import React from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import api from '../api.js'
import { priceLabel, DemoBadge, PURPOSE_LABEL } from '../components/PropBits.jsx'

/* Phase 6 — the browse page now serves the DB-backed `properties` table
   (approved + available listings only) via GET /api/properties. Server-side
   filtering and pagination; the 25k-row UAE dataset is never shipped to the
   browser. Every listing card links back to LykAI for the enquiry path. */

const TYPES = [
  '', 'apartment', 'villa', 'townhouse', 'penthouse', 'studio',
  'hotel apartment', 'plot', 'compound',
]
const BEDS = ['', '1', '2', '3', '4', '5']
const PURPOSES = [
  { value: '', label: 'Buy or rent' },
  { value: 'sale', label: 'For sale' },
  { value: 'rent', label: 'For rent' },
  { value: 'lease', label: 'For lease' },
]

/* Manual browse is the secondary path — every card still leads back to LykAI. */
function BrowseCard({ prop, onOpen, onAsk }) {
  const beds = prop.bedrooms ?? '—'
  const baths = prop.bathrooms ?? '—'
  const type = prop.property_type || 'Property'
  const loc = prop.location || ''
  const emoji =
    /villa/i.test(type) ? '🏡' :
    /townhouse/i.test(type) ? '🏘️' :
    /penthouse/i.test(type) ? '🌆' :
    /studio/i.test(type) ? '🏠' :
    /plot|land/i.test(type) ? '🗺️' : '🏢'

  return (
    <article className="prop-card browse-card">
      {/* Branded placeholder — the database has no listing photos, and we
          never invent property photographs. */}
      <div className="prop-thumb">
        <span>{emoji}</span>
        <span className="loc">📍 {loc}</span>
      </div>
      <div className="prop-body">
        <div className="prop-badges">
          {PURPOSE_LABEL[prop.purpose] && (
            <span className="purpose-tag">{PURPOSE_LABEL[prop.purpose]}</span>
          )}
          <DemoBadge prop={prop} />
        </div>
        <div className="prop-price">{priceLabel(prop)}</div>
        <div className="prop-title">{prop.title || type}</div>
        <div className="prop-specs">
          <span>🛏 {beds}</span>
          <span>🛁 {baths}</span>
          <span>📐 {prop.area != null ? `${prop.area.toLocaleString()} ${prop.area_unit || 'sqft'}` : '—'}</span>
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

const EMPTY_FILTERS = { purpose: '', location: '', type: '', beds: '', minPrice: '', maxPrice: '' }

export default function PropertiesPage() {
  const navigate = useNavigate()
  // Filters live in the URL, so opening a property and coming back (browser
  // back) restores the exact result set ("preserve filters where practical").
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = {
    purpose: searchParams.get('purpose') || '',
    location: searchParams.get('location') || '',
    type: searchParams.get('type') || '',
    beds: searchParams.get('beds') || '',
    minPrice: searchParams.get('minPrice') || '',
    maxPrice: searchParams.get('maxPrice') || '',
  }
  const [items, setItems] = React.useState([])
  const [total, setTotal] = React.useState(0)
  const [loading, setLoading] = React.useState(true)
  const [loadingMore, setLoadingMore] = React.useState(false)
  const [error, setError] = React.useState(null)

  const PAGE = 24
  const [offset, setOffset] = React.useState(0)

  const setFilter = (key, value) => {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(key, value)
    else next.delete(key)
    setSearchParams(next, { replace: true })
  }

  const resetFilters = () => setSearchParams(new URLSearchParams(), { replace: true })

  // Free-text filters use local drafts so typing doesn't fire one request per
  // keystroke; drafts commit to the URL on Enter/blur (selects are immediate).
  const [locDraft, setLocDraft] = React.useState(filters.location)
  const [minDraft, setMinDraft] = React.useState(filters.minPrice)
  const [maxDraft, setMaxDraft] = React.useState(filters.maxPrice)
  React.useEffect(() => { setLocDraft(filters.location) }, [filters.location])
  React.useEffect(() => { setMinDraft(filters.minPrice) }, [filters.minPrice])
  React.useEffect(() => { setMaxDraft(filters.maxPrice) }, [filters.maxPrice])

  const commitTextFilters = () => {
    const next = new URLSearchParams(searchParams)
    const loc = locDraft.trim()
    if (loc) next.set('location', loc); else next.delete('location')
    if (minDraft) next.set('minPrice', minDraft); else next.delete('minPrice')
    if (maxDraft) next.set('maxPrice', maxDraft); else next.delete('maxPrice')
    setSearchParams(next, { replace: true })
  }

  const fetchPage = React.useCallback(
    async (append, off) => {
      if (append) setLoadingMore(true)
      else setLoading(true)
      setError(null)
      try {
        const res = await api.listRecords({
          purpose: filters.purpose,
          location: filters.location.trim(),
          property_type: filters.type,
          min_bedrooms: filters.beds,
          min_price: filters.minPrice,
          max_price: filters.maxPrice,
          limit: PAGE,
          offset: off,
        })
        setTotal(res.total ?? 0)
        setItems((prev) => (append ? [...prev, ...res.results] : res.results))
      } catch (e) {
        setError(e.message || 'Could not load properties.')
      } finally {
        setLoading(false)
        setLoadingMore(false)
      }
    },
    [filters.purpose, filters.location, filters.type, filters.beds,
     filters.minPrice, filters.maxPrice],
  )

  // Initial load + reload on filter change (reset paging)
  React.useEffect(() => {
    setOffset(0)
    fetchPage(false, 0)
  }, [fetchPage])

  const askLykAI = (prop) => navigate(`/chat?ref=${prop.id}&src=record`)
  const openProp = (prop) => navigate(`/properties/${prop.id}`)

  return (
    <div className="page" style={{ maxWidth: 1120 }}>
      <div className="page-head">
        <div className="row">
          <div>
            <span className="eyebrow">Browse</span>
            <h1>Properties</h1>
            <p>
              Browse Lyka Realty listings here — or tell LykAI what you want and
              let the concierge find matches for you.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <button className="btn gold btn-sm" onClick={() => navigate('/chat')}>
              <span className="ico">→</span> Talk to LykAI
            </button>
          </div>
        </div>
      </div>

      {/* Search & filters — backed by server-side query parameters */}
      <div className="browse-filters">
        <select
          aria-label="Purpose"
          value={filters.purpose}
          onChange={(e) => setFilter('purpose', e.target.value)}
        >
          {PURPOSES.map((p) => (
            <option key={p.value} value={p.value}>{p.label}</option>
          ))}
        </select>
        <input
          type="text"
          aria-label="Location"
          placeholder="Location (e.g. Dubai Marina)"
          value={locDraft}
          onChange={(e) => setLocDraft(e.target.value)}
          onBlur={commitTextFilters}
          onKeyDown={(e) => e.key === 'Enter' && commitTextFilters()}
        />
        <select aria-label="Property type" value={filters.type} onChange={(e) => setFilter('type', e.target.value)}>
          {TYPES.map((t) => (
            <option key={t} value={t}>{t ? t[0].toUpperCase() + t.slice(1) : 'Any type'}</option>
          ))}
        </select>
        <select aria-label="Bedrooms" value={filters.beds} onChange={(e) => setFilter('beds', e.target.value)}>
          {BEDS.map((b) => (
            <option key={b} value={b}>{b ? `${b}+ beds` : 'Any beds'}</option>
          ))}
        </select>
        <input
          type="number"
          min="0"
          aria-label="Minimum price"
          placeholder="Min price (AED)"
          value={minDraft}
          onChange={(e) => setMinDraft(e.target.value)}
          onBlur={commitTextFilters}
          onKeyDown={(e) => e.key === 'Enter' && commitTextFilters()}
        />
        <input
          type="number"
          min="0"
          aria-label="Maximum price"
          placeholder="Max price (AED)"
          value={maxDraft}
          onChange={(e) => setMaxDraft(e.target.value)}
          onBlur={commitTextFilters}
          onKeyDown={(e) => e.key === 'Enter' && commitTextFilters()}
        />
        <button className="btn dark btn-sm" onClick={resetFilters} disabled={!Object.values(filters).some(Boolean)}>
          Reset
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
            key={`${p.id}-${i}`}
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
          <div style={{ marginTop: 16, display: 'flex', gap: 10, justifyContent: 'center' }}>
            <button className="btn ghost btn-sm" onClick={resetFilters}>Reset filters</button>
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
            disabled={loading || loadingMore}
            onClick={() => {
              const next = offset + PAGE
              setOffset(next)
              fetchPage(true, next)
            }}
          >
            {loadingMore ? 'Loading…' : 'Load more'}
          </button>
        </div>
      )}
    </div>
  )
}
