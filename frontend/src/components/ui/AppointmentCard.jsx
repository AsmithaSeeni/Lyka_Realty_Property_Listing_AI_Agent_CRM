import React from 'react'
import StatusBadge from './StatusBadge.jsx'

/**
 * Clean AppointmentCard for viewings and customer meetings.
 */
export default function AppointmentCard({
  appointment,
  onSelect = null,
  actions = null,
  className = '',
}) {
  if (!appointment) return null

  const {
    id,
    scheduled_at,
    client_name = 'Customer',
    client_phone,
    property_title = 'Property Viewing',
    property_location,
    status = 'scheduled',
    notes,
  } = appointment

  const dateObj = scheduled_at ? new Date(scheduled_at) : null
  const dateStr = dateObj ? dateObj.toLocaleDateString('en-AE', { month: 'short', day: 'numeric', weekday: 'short' }) : '—'
  const timeStr = dateObj ? dateObj.toLocaleTimeString('en-AE', { hour: '2-digit', minute: '2-digit' }) : '—'

  return (
    <div
      onClick={() => onSelect && onSelect(appointment)}
      className={`p-4 bg-white border border-[var(--line)] rounded-xl shadow-sm hover:shadow-md transition-all duration-150 flex flex-col justify-between ${
        onSelect ? 'cursor-pointer hover:-translate-y-0.5' : ''
      } ${className}`}
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono font-bold bg-[var(--bone)] px-2.5 py-1 rounded-md text-[var(--ink-2)]">
            📅 {dateStr} · {timeStr}
          </span>
        </div>
        <StatusBadge status={status} size="sm" />
      </div>

      <div className="my-1.5">
        <h4 className="text-sm font-bold text-[var(--ink)] m-0 line-clamp-1">
          {client_name}
        </h4>
        <p className="text-xs text-[var(--muted)] m-0 mt-0.5 line-clamp-1">
          🏢 {property_title} {property_location ? `· ${property_location}` : ''}
        </p>
        {notes && (
          <p className="text-xs text-[var(--ink-2)] bg-[var(--soft)] p-2 rounded-lg mt-2 m-0 italic line-clamp-2">
            “{notes}”
          </p>
        )}
      </div>

      {actions && (
        <div className="mt-3 pt-2.5 border-t border-[var(--line)] flex items-center justify-end gap-2">
          {actions}
        </div>
      )}
    </div>
  )
}

