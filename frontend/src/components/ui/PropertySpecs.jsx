import React from 'react'

export default function PropertySpecs({
  bedroomLabel = '—',
  bathroomLabel = '—',
  formattedArea = '—',
  className = '',
}) {
  return (
    <div
      className={`flex items-center justify-between text-xs text-slate-600 font-medium ${className}`}
    >
      <span className="flex items-center gap-1">
        <span>🛏</span>
        <b>{bedroomLabel}</b>
      </span>
      <span className="flex items-center gap-1">
        <span>🛁</span>
        <b>{bathroomLabel}</b>
      </span>
      <span className="flex items-center gap-1">
        <span>📐</span>
        <b>{formattedArea}</b>
      </span>
    </div>
  )
}

