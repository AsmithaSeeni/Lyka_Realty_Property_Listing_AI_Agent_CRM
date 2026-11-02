import React from 'react'

/**
 * Tasteful LoadingState to avoid layout jumps.
 */
export default function LoadingState({
  message = 'Loading data…',
  compact = false,
  className = '',
}) {
  if (compact) {
    return (
      <div className={`inline-flex items-center gap-2 text-xs text-[var(--muted)] ${className}`}>
        <span className="w-3.5 h-3.5 border-2 border-[var(--maroon)] border-t-transparent rounded-full animate-spin" />
        <span>{message}</span>
      </div>
    )
  }

  return (
    <div className={`flex flex-col items-center justify-center p-12 text-center ${className}`}>
      <div className="w-8 h-8 border-3 border-[var(--maroon)] border-t-transparent rounded-full animate-spin mb-3" />
      <span className="text-sm font-medium text-[var(--ink-2)]">{message}</span>
    </div>
  )
}

