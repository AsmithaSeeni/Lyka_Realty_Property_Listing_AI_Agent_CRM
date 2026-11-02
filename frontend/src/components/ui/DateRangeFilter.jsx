import React from 'react'

const DEFAULT_PERIODS = [
  { key: '7d', label: '7D' },
  { key: '30d', label: '30D' },
  { key: '90d', label: '90D' },
  { key: 'this_month', label: 'This Month' },
  { key: 'all', label: 'All' },
]

/**
 * DateRangeFilter with period presets and custom date modal/fields.
 */
export default function DateRangeFilter({
  period,
  onPeriodChange,
  customRange = { from: '', to: '' },
  onCustomChange = null,
  onApplyCustom = null,
  isCustom = false,
  className = '',
}) {
  return (
    <div className={`inline-flex flex-wrap items-center gap-2 bg-[var(--bone)] p-1 rounded-xl border border-[var(--line)] ${className}`}>
      <div className="flex items-center gap-1">
        {DEFAULT_PERIODS.map((p) => {
          const active = !isCustom && period === p.key
          return (
            <button
              key={p.key}
              type="button"
              onClick={() => onPeriodChange(p.key)}
              className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-all duration-150 ${
                active
                  ? 'bg-white text-[var(--maroon)] shadow-sm'
                  : 'text-[var(--ink-2)] hover:text-[var(--ink)]'
              }`}
            >
              {p.label}
            </button>
          )
        })}
      </div>

      {onCustomChange && (
        <div className="flex items-center gap-1.5 pl-2 border-l border-[var(--line)]">
          <input
            type="date"
            value={customRange.from || ''}
            onChange={(e) => onCustomChange({ ...customRange, from: e.target.value })}
            className="px-2 py-0.5 bg-white border border-[var(--line)] rounded text-xs text-[var(--ink-2)] focus:outline-none"
            aria-label="Start date"
          />
          <span className="text-xs text-[var(--muted)]">to</span>
          <input
            type="date"
            value={customRange.to || ''}
            onChange={(e) => onCustomChange({ ...customRange, to: e.target.value })}
            className="px-2 py-0.5 bg-white border border-[var(--line)] rounded text-xs text-[var(--ink-2)] focus:outline-none"
            aria-label="End date"
          />
          {onApplyCustom && (
            <button
              type="button"
              onClick={onApplyCustom}
              className="px-2 py-1 bg-[var(--maroon)] text-white rounded text-xs font-semibold hover:bg-[var(--maroon-deep)] transition-colors"
            >
              Apply
            </button>
          )}
        </div>
      )}
    </div>
  )
}

