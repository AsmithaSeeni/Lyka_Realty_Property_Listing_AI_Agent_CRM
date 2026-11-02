import React, { useEffect } from 'react'

/**
 * Accessible ConfirmationDialog with soft plum backdrop blur.
 */
export default function ConfirmationDialog({
  isOpen,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  isDanger = false,
  onConfirm,
  onCancel,
  loading = false,
}) {
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && isOpen) {
        onCancel()
      }
    }
    if (isOpen) {
      document.body.style.overflow = 'hidden'
      window.addEventListener('keydown', handleKeyDown)
    }
    return () => {
      document.body.style.overflow = ''
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen, onCancel])

  if (!isOpen) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="dialog-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[rgba(68,16,47,0.45)] backdrop-blur-sm animate-in fade-in duration-150"
    >
      <div
        className="w-full max-w-md bg-white border border-[var(--line)] rounded-2xl shadow-xl overflow-hidden p-6 animate-in zoom-in-95 duration-150"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 mb-2">
          <h3 id="dialog-title" className="text-lg font-serif font-bold text-[var(--ink)] m-0">
            {title}
          </h3>
          <button
            type="button"
            onClick={onCancel}
            className="text-[var(--muted)] hover:text-[var(--ink)] text-lg leading-none p-1 rounded hover:bg-[var(--bone)] transition-colors"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <p className="text-sm text-[var(--ink-2)] leading-relaxed m-0 mt-2 mb-6">
          {message}
        </p>

        <div className="flex items-center justify-end gap-2.5">
          <button
            type="button"
            onClick={onCancel}
            disabled={loading}
            className="px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold text-[var(--ink-2)] bg-[var(--bone)] hover:bg-[#e8dfcf] transition-colors disabled:opacity-50"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={loading}
            className={`px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold text-white transition-colors disabled:opacity-50 ${
              isDanger
                ? 'bg-rose-700 hover:bg-rose-800'
                : 'bg-[var(--maroon)] hover:bg-[var(--maroon-deep)]'
            }`}
          >
            {loading ? 'Processing…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

