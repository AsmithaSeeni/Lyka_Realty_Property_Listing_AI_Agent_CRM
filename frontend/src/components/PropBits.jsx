import React from 'react'

/* Shared, honest listing formatting (Phase 6).
   Price periods are never invented: sale = one-time, rent/lease = the
   project convention (yearly). Unknown periods are stated, not guessed. */

export const PURPOSE_LABEL = { sale: 'For sale', rent: 'For rent', lease: 'For lease' }

export function priceLabel(p) {
  const cur = p.currency || 'AED'
  const amount = typeof p.price === 'number' ? p.price.toLocaleString() : (p.price || '')
  if (p.price_period === 'per year') return `${cur} ${amount} / year`
  if (p.price_period === 'per month') return `${cur} ${amount} / month`
  if (p.price_period === 'one-time') return `${cur} ${amount}`
  return `${cur} ${amount}`.trim()
}

/* Fictional demo listings must always say so (Phase 2 safeguard) — this
   badge appears wherever demo listings are shown to customers. */
export function DemoBadge({ prop }) {
  if (!prop.is_demo) return null
  return (
    <span
      className="demo-tag"
      title="Synthetic demo data — not a real Lyka Realty property"
    >
      Fictional Demo Listing
    </span>
  )
}
