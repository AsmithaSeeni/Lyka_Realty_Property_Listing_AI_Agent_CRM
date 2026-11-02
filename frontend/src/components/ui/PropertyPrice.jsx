import React from 'react'

export default function PropertyPrice({
  formattedPriceWithPeriod,
  size = 'md',
  className = '',
}) {
  const sizeClasses = {
    sm: 'text-base',
    md: 'text-xl',
    lg: 'text-2xl sm:text-3xl',
  }[size] || 'text-xl'

  return (
    <div
      className={`font-serif font-bold text-[#0A192F] tracking-tight ${sizeClasses} ${className}`}
      style={{ fontVariantNumeric: 'tabular-nums' }}
    >
      {formattedPriceWithPeriod || 'Price on request'}
    </div>
  )
}

