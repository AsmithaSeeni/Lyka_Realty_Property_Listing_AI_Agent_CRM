import React from 'react'
import { adaptProperty } from '../../utils/propertyAdapter.js'
import StatusBadge from './StatusBadge.jsx'

/**
 * Enterprise Canonical PropertyCard for Lyka Realty CRM & Concierge.
 * 
 * Unifies the visual hierarchy, data contracts, and field formatting across:
 * - Public Marketplace (`variant="public"`)
 * - Customer Portal & Shortlists (`variant="saved"`)
 * - LykAI Concierge Recommendations (`variant="chat"`)
 * - Staff CRM Inventory & Lead Dossiers (`variant="agent"`)
 * - Compact horizontal references (`variant="compact"`)
 */
export default function PropertyCard({
  property,
  prop,
  variant = 'public',
  onSelect = null,
  onOpen = null,
  actions = null,
  badge = null,
  index = null,
  className = '',
}) {
  const p = adaptProperty(property || prop)
  if (!p) return null

  const handleSelect = onSelect || onOpen
  const isCompact = variant === 'compact'

  // Image fallback error state
  const [imgFailed, setImgFailed] = React.useState(false)

  // Status badge selection based on variant
  const renderBadge = () => {
    if (badge) return badge

    if (p.isDemo) {
      return (
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            padding: '2px 8px',
            borderRadius: '9999px',
            fontSize: '10px',
            fontWeight: 700,
            letterSpacing: '0.05em',
            textTransform: 'uppercase',
            background: 'rgba(69, 26, 3, 0.85)',
            color: '#fcd34d',
            border: '1px solid rgba(180, 83, 9, 0.4)',
            backdropFilter: 'blur(4px)',
          }}
        >
          Demo
        </span>
      )
    }

    if (variant === 'agent') {
      const vStatus = p.verificationStatus
      return (
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            padding: '2px 8px',
            borderRadius: '9999px',
            fontSize: '10px',
            fontWeight: 700,
            letterSpacing: '0.05em',
            textTransform: 'uppercase',
            background: vStatus === 'verified' ? 'rgba(6, 78, 59, 0.85)' : 'rgba(30, 41, 59, 0.85)',
            color: vStatus === 'verified' ? '#6ee7b7' : '#cbd5e1',
            border: '1px solid rgba(148, 163, 184, 0.3)',
            backdropFilter: 'blur(4px)',
          }}
        >
          {vStatus === 'verified' ? '✓ Verified' : vStatus === 'pending_review' ? '⏳ Review' : 'Draft'}
        </span>
      )
    }

    if (p.source === 'dataset') {
      return (
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            padding: '2px 8px',
            borderRadius: '9999px',
            fontSize: '10px',
            fontWeight: 700,
            letterSpacing: '0.05em',
            textTransform: 'uppercase',
            background: 'rgba(58, 12, 38, 0.9)',
            color: '#f3d99c',
            border: '1px solid rgba(232, 189, 104, 0.45)',
            backdropFilter: 'blur(4px)',
          }}
        >
          Market Reference
        </span>
      )
    }

    if (p.source === 'record' && p.isApproved) {
      return (
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            padding: '2px 8px',
            borderRadius: '9999px',
            fontSize: '10px',
            fontWeight: 700,
            letterSpacing: '0.05em',
            textTransform: 'uppercase',
            background: 'rgba(6, 78, 59, 0.9)',
            color: '#6ee7b7',
            border: '1px solid rgba(16, 185, 129, 0.4)',
            backdropFilter: 'blur(4px)',
          }}
        >
          ✓ Verified Lyka
        </span>
      )
    }

    if (p.purpose) {
      return (
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            padding: '2px 8px',
            borderRadius: '9999px',
            fontSize: '10px',
            fontWeight: 700,
            letterSpacing: '0.05em',
            textTransform: 'uppercase',
            background: 'rgba(90, 22, 69, 0.9)',
            color: '#ffffff',
            border: '1px solid rgba(255, 255, 255, 0.25)',
            backdropFilter: 'blur(4px)',
          }}
        >
          {p.purpose === 'rent' || p.purpose === 'lease' ? 'For Rent' : 'For Sale'}
        </span>
      )
    }

    return null
  }

  // Compact horizontal view (e.g. for drawers, sidebars)
  if (isCompact) {
    return (
      <article
        onClick={() => handleSelect && handleSelect(p)}
        className={`bg-white border border-slate-200 rounded-xl p-3 flex items-center justify-between gap-3 shadow-sm hover:border-slate-300 transition-all ${
          handleSelect ? 'cursor-pointer hover:shadow-md' : ''
        } ${className}`}
        style={{
          background: '#ffffff',
          border: '1px solid #e2e8f0',
          borderRadius: '12px',
          padding: '12px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '12px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0 }}>
          <div
            style={{
              width: '48px',
              height: '48px',
              borderRadius: '8px',
              background: '#0f172a',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              fontSize: '20px',
              overflow: 'hidden',
            }}
          >
            {p.hasRealImage && !imgFailed ? (
              <img
                src={p.primaryImage}
                alt={p.title}
                style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                onError={() => setImgFailed(true)}
              />
            ) : (
              <span>{p.fallbackEmoji}</span>
            )}
          </div>
          <div style={{ minWidth: 0 }}>
            <h4
              style={{
                fontSize: '13px',
                fontWeight: 600,
                color: '#0f172a',
                margin: 0,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {p.title}
            </h4>
            <p
              style={{
                fontSize: '11px',
                color: '#64748b',
                margin: '2px 0 0 0',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              📍 {p.location}
            </p>
            <div
              style={{
                fontSize: '12px',
                fontWeight: 700,
                color: '#0A192F',
                marginTop: '4px',
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {p.formattedPriceWithPeriod}
            </div>
          </div>
        </div>
        {actions && <div style={{ flexShrink: 0 }}>{actions}</div>}
      </article>
    )
  }

  // Standard Card view (Public, Saved, Chat, Agent)
  return (
    <article
      onClick={() => handleSelect && handleSelect(p)}
      className={`property-card-root ${handleSelect ? 'interactive' : ''} ${className}`}
      style={{
        background: '#ffffff',
        border: '1px solid #ebd8e3',
        borderRadius: '16px',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        boxShadow: '0 4px 14px -2px rgba(58, 12, 38, 0.06)',
        width: '100%',
        boxSizing: 'border-box',
        cursor: handleSelect ? 'pointer' : 'default',
      }}
    >
      <div>
        {/* Media Container with 16:10 Luxury Aspect Ratio */}
        <div
          className="prop-card-media"
          style={{
            width: '100%',
            aspectRatio: '16 / 10',
            position: 'relative',
            overflow: 'hidden',
            background: 'linear-gradient(135deg, #2a081a 0%, #44102f 50%, #5a1645 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          {p.hasRealImage && !imgFailed ? (
            <img
              src={p.primaryImage}
              alt={p.title}
              style={{
                width: '100%',
                height: '100%',
                objectFit: 'cover',
                display: 'block',
              }}
              onError={() => setImgFailed(true)}
            />
          ) : (
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                textAlign: 'center',
                padding: '24px 16px',
                color: '#ffffff',
              }}
            >
              <span style={{ fontSize: '36px', marginBottom: '4px', filter: 'drop-shadow(0 2px 4px rgba(0,0,0,0.3))' }}>
                {p.fallbackEmoji}
              </span>
              <span style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.12em', fontWeight: 600, color: '#e8bd68' }}>
                Lyka Market Reference
              </span>
            </div>
          )}

          {/* Badges Overlay */}
          <div
            style={{
              position: 'absolute',
              top: '12px',
              left: '12px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              zIndex: 2,
            }}
          >
            {renderBadge()}
          </div>

          <div
            style={{
              position: 'absolute',
              top: '12px',
              right: '12px',
              background: 'rgba(42, 8, 26, 0.78)',
              border: '1px solid rgba(232, 189, 104, 0.35)',
              backdropFilter: 'blur(6px)',
              padding: '2px 10px',
              borderRadius: '9999px',
              fontSize: '10px',
              fontWeight: 600,
              color: '#fff9ed',
              zIndex: 2,
            }}
          >
            {p.propertyType}
          </div>

          {index != null && (
            <div
              style={{
                position: 'absolute',
                bottom: '10px',
                left: '10px',
                width: '24px',
                height: '24px',
                borderRadius: '9999px',
                background: 'rgba(58, 12, 38, 0.9)',
                border: '1px solid rgba(232, 189, 104, 0.4)',
                backdropFilter: 'blur(4px)',
                color: '#f3d99c',
                fontWeight: 700,
                fontSize: '11px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                zIndex: 2,
              }}
            >
              {index}
            </div>
          )}
        </div>

        {/* Content Body */}
        <div className="prop-card-body" style={{ padding: '16px 18px', display: 'flex', flexDirection: 'column' }}>
          {/* Price Header */}
          <div
            className="prop-card-price"
            style={{
              fontSize: '20px',
              fontWeight: 700,
              color: '#5a1645',
              fontVariantNumeric: 'tabular-nums',
              marginBottom: '4px',
            }}
          >
            {p.formattedPriceWithPeriod}
          </div>

          {/* Title */}
          <h3
            className="prop-card-title"
            title={p.title}
            style={{
              fontSize: '14.5px',
              fontWeight: 600,
              color: '#0f172a',
              lineHeight: 1.4,
              margin: '0 0 4px 0',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {p.title}
          </h3>

          {/* Location */}
          <p
            className="prop-card-location"
            style={{
              fontSize: '12px',
              color: '#64748b',
              margin: '0 0 12px 0',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
            }}
          >
            <span>📍</span>
            <span>{p.location}</span>
          </p>

          {/* Specs Row */}
          <div
            className="prop-card-specs"
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              paddingTop: '12px',
              borderTop: '1px solid #f1f5f9',
              fontSize: '12px',
              color: '#475569',
            }}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <span>🛏</span>
              <b>{p.bedroomLabel}</b>
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <span>🛁</span>
              <b>{p.bathroomLabel}</b>
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <span>📐</span>
              <b>{p.formattedArea}</b>
            </span>
          </div>
        </div>
      </div>

      {/* Action Footer Slot */}
      {actions && (
        <div style={{ padding: '0 18px 16px 18px', borderTop: 'none', display: 'flex', alignItems: 'center', gap: '8px' }}>
          {actions}
        </div>
      )}
    </article>
  )
}
