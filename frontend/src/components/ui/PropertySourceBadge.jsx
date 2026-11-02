import React from 'react'

/**
 * PropertySourceBadge for Lyka Realty CRM.
 * Displays authoritative source provenance:
 * - Category A: 'record' / 'manual' -> "Verified Lyka" (Navy/Gold)
 * - Category B: 'staged' / 'import' -> "Internal Staged" (Amber/Slate)
 * - Category C: 'dataset' / 'uae_dataset' -> "Market Dataset" (Slate/Neutral)
 */
export default function PropertySourceBadge({ source, isApproved = false, isDemo = false, size = 'sm', className = '' }) {
  if (isDemo) {
    return (
      <span className={`inline-flex items-center gap-1 font-semibold rounded-full uppercase tracking-wider text-[10px] px-2 py-0.5 bg-amber-950/80 text-amber-300 border border-amber-800/50 ${className}`}>
        <span>⚠️</span> Demo
      </span>
    )
  }

  const s = String(source || '').toLowerCase().trim()
  const isVerified = isApproved || s === 'record' || s === 'manual'

  if (isVerified) {
    return (
      <span className={`inline-flex items-center gap-1 font-semibold rounded-full uppercase tracking-wider text-[10px] px-2.5 py-0.5 bg-[#0A192F] text-[#C5A880] border border-[#C5A880]/30 shadow-xs ${className}`}>
        <span className="w-1.5 h-1.5 rounded-full bg-[#C5A880]"></span>
        Verified Lyka
      </span>
    )
  }

  if (s === 'uae_dataset' || s === 'dataset') {
    return (
      <span className={`inline-flex items-center gap-1 font-semibold rounded-full uppercase tracking-wider text-[10px] px-2 py-0.5 bg-slate-100 text-slate-700 border border-slate-300 ${className}`}>
        Market Dataset
      </span>
    )
  }

  return (
    <span className={`inline-flex items-center gap-1 font-semibold rounded-full uppercase tracking-wider text-[10px] px-2 py-0.5 bg-amber-50 text-amber-800 border border-amber-200 ${className}`}>
      Internal Staged
    </span>
  )
}

