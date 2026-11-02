import React from 'react'

/**
 * Editorial EmptyState container with icon, message, and CTA.
 */
export default function EmptyState({
  icon = '📂',
  title = 'No items found',
  description = 'There are no records in this view.',
  action = null, // e.g. <button>New Record</button>
  className = '',
}) {
  return (
    <div className={`flex flex-col items-center justify-center p-8 sm:p-12 text-center bg-white border border-[var(--line)] rounded-2xl shadow-sm ${className}`}>
      <div className="w-12 h-12 rounded-full bg-[var(--bone)] flex items-center justify-center text-2xl mb-3 shadow-inner">
        {icon}
      </div>
      <h3 className="text-base font-serif font-bold text-[var(--ink)] m-0">
        {title}
      </h3>
      {description && (
        <p className="mt-1.5 text-xs sm:text-sm text-[var(--muted)] max-w-sm leading-relaxed m-0">
          {description}
        </p>
      )}
      {action && (
        <div className="mt-4">
          {action}
        </div>
      )}
    </div>
  )
}

