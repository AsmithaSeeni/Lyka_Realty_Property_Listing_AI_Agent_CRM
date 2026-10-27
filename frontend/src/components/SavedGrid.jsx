import React from 'react'
import { useNavigate } from 'react-router-dom'
import { DemoBadge, PURPOSE_LABEL } from './PropBits.jsx'

/* Shared saved-property cards, used by /saved and the My Chats page.
   Real listings only — never invented listings.
   Each row carries `source` ('dataset' | 'record') so cards route to the
   matching detail URL: record listings live at /properties/:id, dataset
   listings at the legacy /property/:id. */
export default function SavedGrid({ items }) {
  const navigate = useNavigate()
  if (!items?.length) return null
  const open = (p) =>
    navigate(p.source === 'record' ? `/properties/${p.property_id}` : `/property/${p.property_id}`)
  const ask = (p) =>
    navigate(
      p.source === 'record'
        ? `/chat?ref=${p.property_id}&src=record`
        : `/chat?ref=${p.property_id}`,
    )
  return (
    <div className="browse-grid" style={{ marginBottom: 26 }}>
      {items.map((p) => (
        <article
          className="prop-card browse-card"
          key={`${p.source || 'dataset'}-${p.property_id}`}
        >
          <div className="prop-thumb">
            <span>{/villa/i.test(p.property_type || '') ? '🏡' : '🏢'}</span>
            <span className="loc">📍 {p.location || ''}</span>
          </div>
          <div className="prop-body">
            <div className="prop-badges">
              {p.purpose && PURPOSE_LABEL[p.purpose] && (
                <span className="purpose-tag">{PURPOSE_LABEL[p.purpose]}</span>
              )}
              <DemoBadge prop={p} />
            </div>
            <div className="prop-price">
              {p.source === 'record'
                ? p.price_period === 'per year'
                  ? `AED ${p.price?.toLocaleString?.() ?? p.price} / year`
                  : `AED ${p.price?.toLocaleString?.() ?? p.price}`
                : `AED ${p.price}`}
            </div>
            <div className="prop-title">{p.property_type || 'Property'} · {p.location}</div>
            <div className="browse-ctas">
              <button className="btn gold btn-sm" onClick={() => open(p)}>
                View Property
              </button>
              <button className="btn ghost btn-sm" onClick={() => ask(p)}>
                Ask LykAI
              </button>
            </div>
          </div>
        </article>
      ))}
    </div>
  )
}
