import React from 'react'

/**
 * FilterBar component for tabbed views or status filters.
 */
export default function FilterBar({
  options = [], // [{ key, label, count }]
  selected,
  onSelect,
  className = '',
}) {
  return (
    <div className={`flex items-center gap-1.5 overflow-x-auto py-1 scrollbar-none ${className}`}>
      {options.map((opt) => {
        const isSelected = selected === opt.key
        return (
          <button
            key={opt.key}
            type="button"
            onClick={() => onSelect(opt.key)}
            className={`inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full text-xs font-semibold whitespace-nowrap transition-all duration-150 ${
              isSelected
                ? 'bg-[var(--maroon)] text-[var(--cream)] shadow-sm'
                : 'bg-[var(--bone)] text-[var(--ink-2)] hover:bg-[#e8dfcf]'
            }`}
          >
            <span>{opt.label}</span>
            {opt.count !== undefined && opt.count !== null && (
              <span
                className={`text-[10.5px] px-1.5 py-0.2 rounded-full font-mono ${
                  isSelected
                    ? 'bg-white/20 text-white'
                    : 'bg-black/10 text-[var(--ink)]'
                }`}
              >
                {opt.count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

