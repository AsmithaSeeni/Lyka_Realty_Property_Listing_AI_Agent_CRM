import React from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import api from '../api.js'
import { priceLabel, DemoBadge, PURPOSE_LABEL } from '../components/PropBits.jsx'

/* Phase 6.1 — two clearly separated sources on one page, never mixed:

   1. "Verified Lyka Realty listings" strip — GET /api/properties (approved
      + available DB inventory only). Rendered only when such rows exist, so
      genuine Lyka stock stays visible without ever seeding fiction.
   2. Main grid — GET /api/properties/dataset: the 25k-row UAE market
      dataset, normalized server-side. The dataset has no purpose, price
      period, images or availability columns; those come back null and are
      rendered as "not specified" rather than guessed.

   The id spaces genuinely differ (dataset property_id 1..25082 vs DB
   properties.id), so every card routes detail and enquiry links by
   prop.source: /property/:id (dataset) vs /properties/:id (record), and
   ?ref= vs ?ref=&src=record in chat. */

/* Types that actually exist in the dataset (substring match server-side).
   'studio' and 'plot' were removed — the dataset has no such rows, so those
   options could only ever produce an empty result set. */
const TYPES = [
  '', 'apartment', 'villa', 'townhouse', 'penthouse', 'hotel apartment',
  'villa compound', 'residential building', 'residential floor',
]
const BEDS = ['', '1', '2', '3', '4', '5']

/* Manual browse is the secondary path — every card still leads back to LykAI.
   Serves both sources: DB rows (purpose tag, demo badge, price period) and
   dataset rows (null purpose/period → those bits simply don't render). */
function BrowseCard({ prop, onOpen, onAsk }) {
  // Dataset Studio rows carry bedrooms=0 (the server's parse_beds
  // convention); DB rows keep their plain integer display.
  const beds = prop.source === 'dataset'
    ? (prop.bedrooms === 0 ? 'Studio' : (prop.bedrooms ?? '—'))
    : (prop.bedrooms ?? '—')
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

export default function PropertiesPage() {
  const navigate = useNavigate()
  // Filters live in the URL, so opening a property and coming back (browser
  // back) restores the exact result set ("preserve filters where practical").
  const [searchParams, setSearchParams] = useSearchParams()
  // No `purpose` filter on this page: the dataset has no sale/rent column,
  // and the server rejects purpose= on /api/properties/dataset with a 422
  // instead of silently ignoring it. Purpose filtering stays on the
  // DB-backed GET /api/properties endpoint.
  const filters = {
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
  // Optional strip of approved Lyka inventory — separate section, cards
  // source-tagged as 'record' so dataset and DB ids can never mix.
  const [verified, setVerified] = React.useState({ items: [], total: 0 })

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
        const res = await api.listDataset({
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
    [filters.location, filters.type, filters.beds,
     filters.minPrice, filters.maxPrice],
  )

  // Initial load + reload on filter change (reset paging)
  React.useEffect(() => {
    setOffset(0)
    fetchPage(false, 0)
  }, [fetchPage])

  // One cheap fetch for the verified strip. It's optional, so failures are
  // swallowed — the dataset grid below carries the page either way.
  React.useEffect(() => {
    let alive = true
    api.listRecords({ limit: 12, offset: 0 })
      .then((res) => {
        if (!alive) return
        const rows = (res.results || []).map((p) => ({ ...p, source: 'record' }))
        setVerified({ items: rows, total: res.total || 0 })
      })
      .catch(() => {})
    return () => { alive = false }
  }, [])

  // Each card routes by its own id space — dataset and DB ids never mix.
  const askLykAI = (prop) =>
    navigate(prop.source === 'dataset'
      ? `/chat?ref=${prop.id}`
      : `/chat?ref=${prop.id}&src=record`)
  const openProp = (prop) =>
    navigate(prop.source === 'dataset' ? `/property/${prop.id}` : `/properties/${prop.id}`)

  return (
    <div className="page" style={{ maxWidth: 1120 }}>
      <div className="page-head">
        <div className="row">
          <div>
            <span className="eyebrow">Browse</span>
            <h1>Properties</h1>
            <p>
              Browse UAE property listings below — or tell LykAI what you want
              and let the concierge find matches for you.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <button className="btn gold btn-sm" onClick={() => navigate('/chat')}>
              <span className="ico">→</span> Talk to LykAI
            </button>
          </div>
        </div>
      </div>

      {/* Verified Lyka inventory — only renders when genuine approved +
          available rows exist (none in production today: no listing has
          been entered and approved yet; nothing is ever seeded to fake it). */}
      {verified.total > 0 && (
        <section aria-label="Verified Lyka Realty listings">
          <div className="subhead">Verified Lyka Realty listings</div>
          <p className="browse-meta">
            {verified.total.toLocaleString()} approved and available listing
            {verified.total === 1 ? '' : 's'} from Lyka Realty's own database.
          </p>
          <div className="browse-grid" style={{ marginBottom: 30 }}>
            {verified.items.map((p) => (
              <BrowseCard key={`rec-${p.id}`} prop={p} onOpen={openProp} onAsk={askLykAI} />
            ))}
          </div>
        </section>
      )}

      <div className="subhead">UAE market dataset</div>
      <p className="browse-meta">
        External market listings — not Lyka-approved inventory.
      </p>

      {/* Search & filters — backed by server-side query parameters */}
      <div className="browse-filters">
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

      <div
        className="notice"
        style={{
          background: 'var(--paper)',
          borderColor: 'var(--line)',
          color: 'var(--muted)',
          marginBottom: 16,
        }}
      >
        ℹ️ Results below come from the external UAE property dataset.
        Sale/rent purpose and live availability are not recorded in that
        dataset, so they are shown as not specified — confirm details with a
        Lyka Realty consultant.
      </div>

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
