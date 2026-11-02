import React from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import api from '../api.js'
import PropertyCard from '../components/ui/PropertyCard.jsx'

/**
 * Stage 6F — Public UAE Property Catalogue
 * 
 * Exclusively displays properties from the official UAErealestate.json dataset (25,082 listings).
 * Pure dataset truth: Zero leakage of internal demo seeds or unverified PostgreSQL records.
 */

/* Property types in the dataset */
const TYPES = [
  '', 'apartment', 'villa', 'townhouse', 'penthouse', 'hotel apartment',
  'villa compound', 'residential building', 'residential floor',
]

const BED_OPTIONS = [
  { value: '', label: 'Any beds' },
  { value: '0', label: 'Studio' },
  { value: '1', label: '1+ bed' },
  { value: '2', label: '2+ beds' },
  { value: '3', label: '3+ beds' },
  { value: '4', label: '4+ beds' },
  { value: '5', label: '5+ beds' },
]

function BrowseCard({ prop, onOpen, onAsk }) {
  return (
    <PropertyCard
      property={prop}
      variant="public"
      onSelect={() => onOpen(prop)}
      actions={
        <div style={{ display: 'flex', gap: 8, width: '100%', marginTop: 4 }}>
          <button
            className="btn btn-sm"
            style={{
              flex: 1,
              background: 'linear-gradient(135deg, #e8bd68 0%, #c0922f 100%)',
              color: '#3a0c26',
              border: 'none',
              fontWeight: 600,
              boxShadow: '0 2px 6px rgba(192, 146, 47, 0.25)',
            }}
            onClick={(e) => {
              e.stopPropagation()
              onOpen(prop)
            }}
          >
            View Property
          </button>
          <button
            className="btn btn-sm btn-ghost"
            style={{
              flex: 1,
              border: '1px solid #5a1645',
              color: '#5a1645',
              fontWeight: 600,
              background: 'transparent',
            }}
            onClick={(e) => {
              e.stopPropagation()
              onAsk(prop)
            }}
          >
            Ask LykAI
          </button>
        </div>
      }
    />
  )
}

export default function PropertiesPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

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

  const PAGE = 24
  const [offset, setOffset] = React.useState(0)

  const setFilter = (key, value) => {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(key, value)
    else next.delete(key)
    setSearchParams(next, { replace: true })
  }

  const resetFilters = () => setSearchParams(new URLSearchParams(), { replace: true })

  // Free-text filter drafts
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
    [filters.location, filters.type, filters.beds, filters.minPrice, filters.maxPrice],
  )

  // Ensure scroll is at the top when entering the catalogue
  React.useEffect(() => {
    window.scrollTo(0, 0)
  }, [])

  // Initial load + reload on filter change
  React.useEffect(() => {
    setOffset(0)
    fetchPage(false, 0)
  }, [fetchPage])

  // Routing dataset properties to /property/:id and /chat?ref=:id
  const askLykAI = (prop) => navigate(`/chat?ref=${prop.id}`)
  const openProp = (prop) => navigate(`/property/${prop.id}`)

  return (
    <div className="page" style={{ maxWidth: 1280, margin: '0 auto', padding: '112px 24px 60px 24px' }}>
      {/* Page Header */}
      <div className="page-head" style={{ marginBottom: 28 }}>
        <div className="row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 16 }}>
          <div style={{ maxWidth: 760 }}>
            <span className="eyebrow" style={{ color: '#a27419', fontWeight: 700, textTransform: 'uppercase', fontSize: 12, letterSpacing: '0.08em' }}>
              Public Catalogue
            </span>
            <h1 style={{ fontSize: 34, fontWeight: 700, color: '#3a0c26', margin: '6px 0 10px 0', fontFamily: 'var(--display, "Playfair Display", serif)' }}>
              Explore UAE Properties
            </h1>
            <p style={{ color: '#334155', fontSize: 15, lineHeight: 1.6, margin: 0 }}>
              Explore property information from our UAE market reference dataset (25,082 verified listings across Dubai and the UAE). Availability and listing authority must be confirmed independently.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10, alignSelf: 'center' }}>
            <button
              className="btn btn-sm"
              onClick={() => navigate('/chat')}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                background: 'linear-gradient(135deg, #e8bd68 0%, #c0922f 100%)',
                color: '#3a0c26',
                fontWeight: 600,
                border: 'none',
                boxShadow: '0 2px 8px rgba(192, 146, 47, 0.3)',
                padding: '9px 18px',
              }}
            >
              <span className="ico">💬</span> Talk to LykAI
            </button>
          </div>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="browse-filters" style={{ marginBottom: 20 }}>
        <input
          type="text"
          aria-label="Location"
          placeholder="Location (e.g. Dubai Marina, Palm Jumeirah)"
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
          {BED_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
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

      {/* Results Meta & Transparency Disclaimer */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <div className="browse-meta" style={{ margin: 0, fontWeight: 600, color: '#334155' }}>
          {loading && !items.length
            ? 'Loading properties…'
            : `${total.toLocaleString()} propert${total === 1 ? 'y' : 'ies'} found${items.length < total ? ` (Showing 1–${items.length})` : ''}`}
        </div>
      </div>

      {error && <div className="notice" style={{ marginBottom: 16 }}>⚠️ {error}</div>}

      <div
        className="notice"
        style={{
          background: '#f8fafc',
          border: '1px solid #e2e8f0',
          borderRadius: 12,
          padding: '12px 16px',
          color: '#475569',
          fontSize: 13.5,
          marginBottom: 24,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
        }}
      >
        <span>ℹ️</span>
        <span>
          <strong>Market Reference Dataset:</strong> Displaying properties from our official UAE market reference database. Live availability and developer authorization are verified by Lyka Realty consultants upon request.
        </span>
      </div>

      {/* 3-Column Luxury Property Grid */}
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

      {/* Empty State */}
      {!loading && items.length === 0 && !error && (
        <div className="empty" style={{ padding: '64px 20px', textAlign: 'center' }}>
          <div className="big" style={{ fontSize: 48, marginBottom: 16 }}>🔍</div>
          <h3 style={{ fontSize: 18, color: '#0f172a', marginBottom: 8 }}>No properties match these filters</h3>
          <p style={{ color: '#64748b', marginBottom: 20 }}>Try clearing filters or search for another location.</p>
          <div style={{ display: 'flex', gap: 10, justifyContent: 'center' }}>
            <button className="btn ghost btn-sm" onClick={resetFilters}>Reset filters</button>
            <button className="btn gold btn-sm" onClick={() => navigate('/chat')}>
              <span className="ico">💬</span> Ask LykAI instead
            </button>
          </div>
        </div>
      )}

      {/* Pagination / Load More */}
      {items.length < total && (
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: 36 }}>
          <button
            className="btn ghost"
            style={{ minWidth: 160 }}
            disabled={loading || loadingMore}
            onClick={() => {
              const next = offset + PAGE
              setOffset(next)
              fetchPage(true, next)
            }}
          >
            {loadingMore ? 'Loading…' : `Load more (${items.length} of ${total.toLocaleString()})`}
          </button>
        </div>
      )}
    </div>
  )
}
