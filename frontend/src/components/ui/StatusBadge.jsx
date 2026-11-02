import React from 'react'

/**
 * Unified StatusBadge component for Lyka Realty CRM.
 * Adheres to dignified, accessible semantic color tokens (no neon).
 */
export default function StatusBadge({ status, size = 'md', className = '' }) {
  if (!status) return null

  const s = String(status).toLowerCase().trim()

  // Map known statuses to semantic variants
  let variant = 'cold' // default
  let label = status

  // 1. Hot / Urgent / Danger
  if (['hot', 'urgent', 'cancelled', 'rejected', 'lost', 'overdue', 'closed lost'].includes(s)) {
    variant = 'hot'
  }
  // 2. Warm / In progress / Pending
  else if ([
    'warm', 'in_progress', 'pending', 'under_offer', 'under offer',
    'negotiation', 'counteroffer', 'feedback_pending', 'contract_drafted'
  ].includes(s)) {
    variant = 'warm'
  }
  // 3. Won / Verified / Available / Completed / Active
  else if ([
    'won', 'closed won', 'available', 'active', 'completed', 'scheduled',
    'confirmed', 'approved', 'verified', 'passed', 'deal_closed'
  ].includes(s)) {
    variant = 'won'
  }
  // 4. Neutral / Cold / Draft / Archived / Reserved
  else if (['cold', 'draft', 'archived', 'reserved', 'inactive', 'new'].includes(s)) {
    variant = 'cold'
  }

  // Format label for display
  if (s === 'in_progress') label = 'In Progress'
  else if (s === 'under_offer') label = 'Under Offer'
  else if (s === 'closed won') label = 'Closed Won'
  else if (s === 'closed lost') label = 'Closed Lost'
  else if (s === 'feedback_pending') label = 'Feedback Due'
  else if (s === 'contract_drafted') label = 'Contract Drafted'
  else label = label.charAt(0).toUpperCase() + label.slice(1).replace(/_/g, ' ')

  const sizeClasses = size === 'sm' 
    ? 'text-[11px] px-2 py-0.5' 
    : size === 'lg' 
      ? 'text-[13px] px-3.5 py-1.5' 
      : 'text-[12px] px-2.5 py-1'

  const variantStyles = {
    hot: {
      background: 'var(--lyk-status-hot-bg, #fae8eb)',
      color: 'var(--lyk-status-hot-text, #8b1e3f)',
      border: '1px solid var(--lyk-status-hot-border, rgba(139, 30, 63, 0.25))',
    },
    warm: {
      background: 'var(--lyk-status-warm-bg, #fcf3dc)',
      color: 'var(--lyk-status-warm-text, #8a5800)',
      border: '1px solid var(--lyk-status-warm-border, rgba(138, 88, 0, 0.25))',
    },
    won: {
      background: 'var(--lyk-status-won-bg, #eaf7ee)',
      color: 'var(--lyk-status-won-text, #185736)',
      border: '1px solid var(--lyk-status-won-border, rgba(24, 87, 54, 0.25))',
    },
    cold: {
      background: 'var(--lyk-status-cold-bg, #edf2f7)',
      color: 'var(--lyk-status-cold-text, #4a5568)',
      border: '1px solid var(--lyk-status-cold-border, rgba(74, 85, 104, 0.22))',
    },
  }

  return (
    <span
      className={`inline-flex items-center font-semibold rounded-full tracking-wide uppercase ${sizeClasses} ${className}`}
      style={variantStyles[variant]}
    >
      <span
        className="w-1.5 h-1.5 rounded-full mr-1.5 shrink-0"
        style={{
          background: variantStyles[variant].color,
          opacity: 0.85
        }}
      />
      {label}
    </span>
  )
}

