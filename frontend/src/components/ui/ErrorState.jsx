import React from 'react'

/**
 * Dignified ErrorState banner or card with retry CTA.
 */
export default function ErrorState({
  title = 'Something went wrong',
  message = 'Failed to load information. Please verify your connection.',
  onRetry = null,
  className = '',
}) {
  return (
    <div className={`p-4 sm:p-5 bg-rose-50 border border-rose-200 rounded-xl text-rose-900 ${className}`}>
      <div className="flex items-start gap-3">
        <span className="text-lg leading-none shrink-0 text-rose-600">⚠</span>
        <div className="flex-1 min-w-0">
          <h4 className="text-sm font-bold text-rose-950 m-0">{title}</h4>
          <p className="mt-1 text-xs sm:text-sm text-rose-800 leading-relaxed m-0">
            {message}
          </p>
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="mt-3 px-3 py-1 bg-rose-600 text-white rounded-lg text-xs font-semibold hover:bg-rose-700 transition-colors"
            >
              Retry
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

