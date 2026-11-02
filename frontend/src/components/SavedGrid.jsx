import React from 'react'
import { useNavigate } from 'react-router-dom'
import PropertyCard from './ui/PropertyCard.jsx'

/* Shared saved-property cards, used by /saved and the My Chats page.
   Real listings only — never invented listings.
   Each row carries `source` ('dataset' | 'record') so cards route to the
   matching detail URL: record listings live at /properties/:id, dataset
   listings at the legacy /property/:id. */
export default function SavedGrid({ items }) {
  const navigate = useNavigate()
  if (!items?.length) return null

  const open = (p) => {
    const pid = p.property_id || p.id
    navigate(p.source === 'record' ? `/properties/${pid}` : `/property/${pid}`)
  }

  const ask = (p) => {
    const pid = p.property_id || p.id
    navigate(
      p.source === 'record'
        ? `/chat?ref=${pid}&src=record`
        : `/chat?ref=${pid}`,
    )
  }

  return (
    <div className="browse-grid" style={{ marginBottom: 26 }}>
      {items.map((p) => {
        const pid = p.property_id || p.id
        return (
          <PropertyCard
            key={`${p.source || 'dataset'}-${pid}`}
            property={p}
            variant="public"
            onSelect={() => open(p)}
            actions={
              <div style={{ display: 'flex', gap: 8, width: '100%', marginTop: 4 }}>
                <button
                  className="btn gold btn-sm"
                  style={{ flex: 1 }}
                  onClick={(e) => {
                    e.stopPropagation()
                    open(p)
                  }}
                >
                  View Property
                </button>
                <button
                  className="btn ghost btn-sm"
                  style={{ flex: 1 }}
                  onClick={(e) => {
                    e.stopPropagation()
                    ask(p)
                  }}
                >
                  Ask LykAI
                </button>
              </div>
            }
          />
        )
      })}
    </div>
  )
}
