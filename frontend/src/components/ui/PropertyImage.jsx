import React from 'react'
import { getPropertyEmoji } from '../../utils/propertyAdapter.js'

export default function PropertyImage({
  src,
  alt = 'Property',
  propertyType = 'Apartment',
  className = '',
  aspectRatio = 'aspect-[16/10]',
}) {
  const [failed, setFailed] = React.useState(!src)
  const emoji = getPropertyEmoji(propertyType)

  if (src && !failed) {
    return (
      <div className={`relative ${aspectRatio} bg-slate-100 overflow-hidden ${className}`}>
        <img
          src={src}
          alt={alt}
          className="w-full h-full object-cover"
          onError={() => setFailed(true)}
        />
      </div>
    )
  }

  return (
    <div
      className={`relative ${aspectRatio} bg-slate-100 overflow-hidden flex flex-col items-center justify-center text-center p-4 text-[#0A192F] ${className}`}
    >
      <span className="text-3xl mb-1 opacity-80">{emoji}</span>
      <span className="text-[10px] uppercase tracking-widest font-semibold text-[#C5A880]">
        Lyka Collection
      </span>
    </div>
  )
}

