import React from 'react'

/**
 * Clean, restrained SearchBar component.
 */
export default function SearchBar({
  value,
  onChange,
  onClear = null,
  placeholder = 'Search records…',
  className = '',
}) {
  return (
    <div className={`relative flex items-center min-w-[220px] max-w-md ${className}`}>
      <span className="absolute left-3.5 text-sm text-[var(--muted)] pointer-events-none">
        🔍
      </span>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full pl-9 pr-9 py-2 bg-white border border-[var(--line)] rounded-xl text-sm text-[var(--ink)] placeholder-[var(--muted)] transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-[var(--maroon)]/20 focus:border-[var(--maroon)]"
      />
      {value && (
        <button
          type="button"
          onClick={() => {
            if (onClear) onClear()
            else onChange('')
          }}
          className="absolute right-2.5 w-5 h-5 flex items-center justify-center text-xs text-[var(--muted)] hover:text-[var(--ink)] rounded-full hover:bg-[var(--bone)] transition-colors"
          title="Clear search"
        >
          ✕
        </button>
      )}
    </div>
  )
}

