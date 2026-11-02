import React from 'react'

/**
 * Standard FormField wrapper with accessible label, error message, and hint.
 */
export default function FormField({
  label,
  error = null,
  hint = null,
  required = false,
  children,
  className = '',
}) {
  return (
    <div className={`flex flex-col gap-1.5 mb-3.5 ${className}`}>
      {label && (
        <label className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-2)] flex items-center justify-between">
          <span>
            {label}
            {required && <span className="text-rose-600 ml-1 font-bold">*</span>}
          </span>
          {hint && <span className="text-[11px] font-normal text-[var(--muted)] lowercase">{hint}</span>}
        </label>
      )}

      {children}

      {error && (
        <span className="text-xs text-rose-700 font-medium flex items-center gap-1 mt-0.5" role="alert">
          <span>⚠</span> {error}
        </span>
      )}
    </div>
  )
}

