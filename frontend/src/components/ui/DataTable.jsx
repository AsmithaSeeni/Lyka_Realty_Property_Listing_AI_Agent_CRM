import React from 'react'

/**
 * Enterprise DataTable for Lyka Realty CRM.
 * Scannable, dense, with sticky header and row hover states.
 */
export default function DataTable({
  columns = [], // [{ key, title, width, align, render }]
  data = [],
  keyField = 'id',
  onRowClick = null,
  emptyMessage = 'No records found matching criteria.',
  loading = false,
  className = '',
}) {
  return (
    <div className={`w-full overflow-hidden border border-[var(--line)] rounded-2xl bg-white shadow-sm ${className}`}>
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse text-sm">
          <thead>
            <tr className="bg-[var(--bone)] border-b border-[var(--line)]">
              {columns.map((col, idx) => (
                <th
                  key={col.key || idx}
                  className={`px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-[var(--muted)] ${
                    col.align === 'right' ? 'text-right' : col.align === 'center' ? 'text-center' : 'text-left'
                  }`}
                  style={{ width: col.width || 'auto' }}
                >
                  {col.title}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--line)]">
            {loading ? (
              <tr>
                <td colSpan={columns.length} className="px-6 py-12 text-center text-[var(--muted)]">
                  <div className="inline-flex items-center gap-2">
                    <span className="w-4 h-4 border-2 border-[var(--maroon)] border-t-transparent rounded-full animate-spin" />
                    <span>Loading records…</span>
                  </div>
                </td>
              </tr>
            ) : data.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-6 py-12 text-center text-[var(--muted)]">
                  <div className="flex flex-col items-center justify-center gap-1">
                    <span className="text-2xl">📋</span>
                    <span className="font-medium text-[var(--ink-2)] mt-1">{emptyMessage}</span>
                  </div>
                </td>
              </tr>
            ) : (
              data.map((row, rIdx) => (
                <tr
                  key={row[keyField] ?? rIdx}
                  onClick={() => onRowClick && onRowClick(row)}
                  className={`transition-colors duration-150 ${
                    onRowClick ? 'cursor-pointer hover:bg-[var(--soft)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gold)]' : 'hover:bg-[#faf8f5]'
                  }`}
                  tabIndex={onRowClick ? 0 : undefined}
                  onKeyDown={(e) => {
                    if (onRowClick && (e.key === 'Enter' || e.key === ' ')) {
                      e.preventDefault()
                      onRowClick(row)
                    }
                  }}
                >
                  {columns.map((col, cIdx) => (
                    <td
                      key={col.key || cIdx}
                      className={`px-4 py-3.5 text-sm text-[var(--ink-2)] ${
                        col.align === 'right' ? 'text-right' : col.align === 'center' ? 'text-center' : 'text-left'
                      }`}
                    >
                      {col.render ? col.render(row[col.key], row, rIdx) : (row[col.key] ?? '—')}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

