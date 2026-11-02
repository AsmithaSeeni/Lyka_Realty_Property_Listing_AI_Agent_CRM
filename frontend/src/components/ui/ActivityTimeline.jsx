import React from 'react'

/**
 * Chronological ActivityTimeline for audit logs, lead notes, and deal events.
 */
export default function ActivityTimeline({
  items = [], // [{ id, title, description, timestamp, actor, icon, badge }]
  className = '',
}) {
  if (!items || items.length === 0) {
    return (
      <div className="text-center py-6 text-xs text-[var(--muted)]">
        No recorded activity yet.
      </div>
    )
  }

  return (
    <div className={`relative pl-4 space-y-4 border-l border-[var(--line)] ${className}`}>
      {items.map((item, idx) => (
        <div key={item.id || idx} className="relative group">
          {/* Timeline bullet dot */}
          <div className="absolute -left-[21px] top-1.5 w-2.5 h-2.5 rounded-full bg-[var(--maroon)] ring-4 ring-white" />

          <div className="bg-white border border-[var(--line)] rounded-xl p-3 shadow-sm hover:shadow-md transition-shadow duration-150">
            <div className="flex items-center justify-between gap-2 mb-1">
              <span className="text-xs font-bold text-[var(--ink)]">
                {item.title}
              </span>
              <span className="text-[11px] text-[var(--muted)] font-mono whitespace-nowrap">
                {item.timestamp}
              </span>
            </div>

            {item.description && (
              <p className="text-xs text-[var(--ink-2)] m-0 leading-relaxed">
                {item.description}
              </p>
            )}

            {(item.actor || item.badge) && (
              <div className="flex items-center justify-between gap-2 mt-2 pt-2 border-t border-[var(--line)] text-[11px] text-[var(--muted)]">
                {item.actor && <span>by {item.actor}</span>}
                {item.badge}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

