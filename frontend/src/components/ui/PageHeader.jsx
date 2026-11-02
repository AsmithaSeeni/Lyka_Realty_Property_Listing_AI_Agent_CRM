import React from 'react'
import { Link } from 'react-router-dom'

/**
 * Editorial PageHeader with breadcrumbs and actions tray.
 */
export default function PageHeader({
  breadcrumbs = [], // [{ label: 'CRM', to: '/agent/dashboard' }, { label: 'Deals' }]
  title,
  subtitle = '',
  badge = null,
  actions = null,
  className = '',
}) {
  return (
    <div className={`mb-6 sm:mb-8 pb-4 border-b border-[var(--line)] ${className}`}>
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-xs text-[var(--muted)] mb-2 font-medium">
          {breadcrumbs.map((crumb, idx) => {
            const isLast = idx === breadcrumbs.length - 1
            return (
              <React.Fragment key={idx}>
                {crumb.to && !isLast ? (
                  <Link
                    to={crumb.to}
                    className="hover:text-[var(--maroon)] transition-colors"
                  >
                    {crumb.label}
                  </Link>
                ) : (
                  <span className={isLast ? 'text-[var(--ink)] font-semibold' : ''}>
                    {crumb.label}
                  </span>
                )}
                {!isLast && <span className="opacity-40">/</span>}
              </React.Fragment>
            )
          })}
        </nav>
      )}

      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl sm:text-3xl font-serif font-bold text-[var(--ink)] tracking-tight m-0">
              {title}
            </h1>
            {badge}
          </div>
          {subtitle && (
            <p className="mt-1 text-sm text-[var(--muted)] leading-relaxed m-0 max-w-3xl">
              {subtitle}
            </p>
          )}
        </div>

        {actions && (
          <div className="flex items-center gap-2.5 shrink-0 flex-wrap">
            {actions}
          </div>
        )}
      </div>
    </div>
  )
}

