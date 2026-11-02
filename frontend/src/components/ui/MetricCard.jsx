import React from 'react'

/**
 * Premium MetricCard for Lyka Realty CRM.
 * Displays large tabular numbers, serif values, and semantic trend indicators.
 */
export default function MetricCard({
  title,
  value,
  prefix = '',
  suffix = '',
  trend = null, // e.g. "+12.4%" or -5%
  trendLabel = 'vs last period',
  accent = 'gold', // 'gold' | 'maroon' | 'won' | 'hot' | 'blue'
  icon = null,
  onClick = null,
  className = '',
}) {
  const accentColors = {
    gold: 'var(--lyk-gold, #e8bd68)',
    maroon: 'var(--lyk-maroon, #5a1645)',
    won: 'var(--lyk-status-won-text, #185736)',
    hot: 'var(--lyk-status-hot-text, #8b1e3f)',
    blue: '#34548f',
  }

  const borderAccent = accentColors[accent] || accentColors.gold
  const isPositive = trend && String(trend).startsWith('+')
  const isNegative = trend && String(trend).startsWith('-')

  return (
    <div
      onClick={onClick}
      className={`relative bg-white border border-[var(--line)] rounded-2xl p-4 sm:p-5 shadow-sm transition-all duration-200 hover:shadow-md hover:-translate-y-0.5 overflow-hidden ${onClick ? 'cursor-pointer' : ''} ${className}`}
    >
      {/* 4px Left Border Indicator */}
      <div
        className="absolute left-0 top-0 bottom-0 w-1 sm:w-1.5"
        style={{ background: borderAccent }}
      />

      <div className="flex items-start justify-between gap-3 mb-2">
        <span className="text-[11.5px] uppercase tracking-wider font-semibold text-[var(--muted)]">
          {title}
        </span>
        {icon && (
          <span className="text-base sm:text-lg opacity-80 shrink-0">
            {icon}
          </span>
        )}
      </div>

      <div className="flex items-baseline gap-1.5 my-1">
        {prefix && (
          <span className="text-xs sm:text-sm font-sans font-medium text-[var(--muted)]">
            {prefix}
          </span>
        )}
        <b
          className="text-2xl sm:text-3xl font-serif font-bold text-[var(--ink)] tracking-tight"
          style={{ fontVariantNumeric: 'tabular-nums' }}
        >
          {value !== null && value !== undefined ? value : '—'}
        </b>
        {suffix && (
          <span className="text-xs sm:text-sm font-sans text-[var(--muted)]">
            {suffix}
          </span>
        )}
      </div>

      {trend && (
        <div className="flex items-center gap-1.5 mt-2 text-xs">
          <span
            className={`font-semibold px-1.5 py-0.5 rounded ${
              isPositive
                ? 'bg-emerald-50 text-emerald-700'
                : isNegative
                ? 'bg-rose-50 text-rose-700'
                : 'bg-stone-100 text-stone-600'
            }`}
          >
            {trend}
          </span>
          {trendLabel && (
            <span className="text-[var(--muted)] text-[11px] truncate">
              {trendLabel}
            </span>
          )}
        </div>
      )}
    </div>
  )
}

