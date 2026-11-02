import React from 'react'

/**
 * Kanban/Pipeline column component for Lyka Realty deals.
 */
export default function PipelineStage({
  title,
  count = 0,
  totalAmount = null,
  color = 'var(--maroon)',
  children,
  className = '',
}) {
  const formattedAmount = totalAmount !== null && totalAmount !== undefined
    ? new Intl.NumberFormat('en-AE', { style: 'currency', currency: 'AED', maximumFractionDigits: 0 }).format(totalAmount)
    : null

  return (
    <div className={`flex flex-col min-w-[280px] sm:min-w-[320px] max-w-sm bg-[var(--soft)] border border-[var(--line)] rounded-2xl p-3 sm:p-4 shadow-sm ${className}`}>
      {/* Column Header */}
      <div className="flex items-center justify-between gap-2 pb-3 mb-3 border-b border-[var(--line)]">
        <div className="flex items-center gap-2">
          <span
            className="w-2.5 h-2.5 rounded-full"
            style={{ background: color }}
          />
          <h4 className="text-xs sm:text-sm font-bold uppercase tracking-wider text-[var(--ink)] m-0">
            {title}
          </h4>
          <span className="text-xs px-2 py-0.5 rounded-full bg-white border border-[var(--line)] font-mono font-bold text-[var(--muted)]">
            {count}
          </span>
        </div>

        {formattedAmount && (
          <span className="text-xs font-mono font-semibold text-[var(--maroon)]" style={{ fontVariantNumeric: 'tabular-nums' }}>
            {formattedAmount}
          </span>
        )}
      </div>

      {/* Cards container */}
      <div className="flex-1 space-y-3 overflow-y-auto max-h-[70vh] pr-1">
        {children}
      </div>
    </div>
  )
}

