import React from 'react'

/**
 * PropertyStatusBadge for Lyka Realty CRM.
 * Renders availability and review state (Available, Reserved, Sold, Rented, Off-Market).
 */
export default function PropertyStatusBadge({ availability = 'available', verificationStatus, size = 'sm', className = '' }) {
  const avail = String(availability || 'available').toLowerCase().trim()

  const config = {
    available: { label: 'Available', bg: 'bg-emerald-50', text: 'text-emerald-700', border: 'border-emerald-200', dot: 'bg-emerald-500' },
    reserved: { label: 'Reserved', bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200', dot: 'bg-amber-500' },
    sold: { label: 'Sold', bg: 'bg-slate-100', text: 'text-slate-600', border: 'border-slate-300', dot: 'bg-slate-400' },
    rented: { label: 'Rented', bg: 'bg-blue-50', text: 'text-blue-700', border: 'border-blue-200', dot: 'bg-blue-500' },
    off_market: { label: 'Off Market', bg: 'bg-rose-50', text: 'text-rose-700', border: 'border-rose-200', dot: 'bg-rose-400' },
  }[avail] || { label: avail, bg: 'bg-slate-100', text: 'text-slate-600', border: 'border-slate-300', dot: 'bg-slate-400' }

  return (
    <span className={`inline-flex items-center gap-1.5 font-semibold rounded-full uppercase tracking-wider text-[10px] px-2.5 py-0.5 ${config.bg} ${config.text} border ${config.border} ${className}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${config.dot}`} />
      {config.label}
    </span>
  )
}

