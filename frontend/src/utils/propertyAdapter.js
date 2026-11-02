/**
 * Canonical Property Adapter for Lyka Realty CRM & LykAI Concierge.
 * 
 * Unifies the property representation across:
 * - PostgreSQL DB listings (`source: 'record'`)
 * - 25,082-row UAE reference dataset items (`source: 'dataset'`)
 * - AI chat recommendations
 * - Agent CRM inventory & lead dossiers
 * - Customer portal shortlists
 * 
 * Guarantees consistent field semantics, AED currency formatting,
 * accurate Studio detection (0 bedrooms -> 'Studio'), and safe media fallbacks.
 */

const EMOJI_MAP = [
  [/villa|mansion/i, '🏡'],
  [/townhouse/i, '🏘️'],
  [/penthouse/i, '🌆'],
  [/studio/i, '🏠'],
  [/plot|land/i, '🗺️'],
]

export function getPropertyEmoji(type = '') {
  for (const [re, emoji] of EMOJI_MAP) {
    if (re.test(String(type || ''))) return emoji
  }
  return '🏢'
}

export function parseNumericPrice(val) {
  if (val === null || val === undefined || val === '') return null
  if (typeof val === 'number') return isNaN(val) ? null : val
  // Strip non-numeric except digits and dot
  const clean = String(val).replace(/,/g, '').trim()
  const num = parseFloat(clean)
  return isNaN(num) ? null : num
}

export function formatAedPrice(amount, currency = 'AED') {
  if (amount === null || amount === undefined || isNaN(amount)) {
    return 'Price on request'
  }
  return `${currency || 'AED'} ${Number(amount).toLocaleString('en-US', {
    maximumFractionDigits: 0,
  })}`
}

export function adaptProperty(raw) {
  if (!raw || typeof raw !== 'object') return null

  // 1. Identify primary ID and source space
  const id = raw.id ?? raw.property_id ?? raw.property_record_id ?? null
  const isDataset = raw.source === 'dataset' || raw.source === 'uae_dataset' || Boolean(raw.property_id && !raw.source && !raw.is_approved)
  const source = isDataset ? 'dataset' : (raw.source || 'record')
  const isDemo = Boolean(raw.is_demo)

  // 2. Reference Number
  const referenceNumber = raw.external_ref || (id ? `#${id}` : '')

  // 3. Property Type
  const propertyType = raw.property_type || (raw.type ? String(raw.type) : 'Apartment')

  // 4. Bedrooms & Studio normalization
  let bedrooms = null
  const rawBeds = raw.bedrooms !== undefined && raw.bedrooms !== null 
    ? raw.bedrooms 
    : (raw.no__of__beds !== undefined ? raw.no__of__beds : null)

  if (rawBeds !== null && rawBeds !== '') {
    if (typeof rawBeds === 'string' && /studio/i.test(rawBeds)) {
      bedrooms = 0
    } else {
      const parsedBeds = parseInt(rawBeds, 10)
      if (!isNaN(parsedBeds)) bedrooms = parsedBeds
    }
  } else if (/studio/i.test(propertyType)) {
    bedrooms = 0
  }

  let bedroomLabel = '—'
  if (bedrooms === 0) {
    bedroomLabel = 'Studio'
  } else if (bedrooms === 1) {
    bedroomLabel = '1 Bed'
  } else if (bedrooms > 1) {
    bedroomLabel = `${bedrooms} Beds`
  }

  // 5. Bathrooms normalization
  let bathrooms = null
  const rawBaths = raw.bathrooms !== undefined && raw.bathrooms !== null 
    ? raw.bathrooms 
    : (raw.no_of_baths !== undefined ? raw.no_of_baths : null)

  if (rawBaths !== null && rawBaths !== '') {
    const parsedBaths = parseFloat(rawBaths)
    if (!isNaN(parsedBaths)) bathrooms = parsedBaths
  }

  let bathroomLabel = '—'
  if (bathrooms !== null) {
    bathroomLabel = `${bathrooms} ${bathrooms === 1 ? 'Bath' : 'Baths'}`
  }

  // 6. Area normalization
  let area = null
  if (raw.area !== null && raw.area !== undefined && raw.area !== '') {
    if (typeof raw.area === 'number') {
      area = isNaN(raw.area) ? null : raw.area
    } else {
      const match = String(raw.area).replace(/,/g, '').match(/[\d.]+/)
      if (match) area = parseFloat(match[0])
    }
  } else if (raw.area_sqft !== null && raw.area_sqft !== undefined) {
    area = Number(raw.area_sqft) || null
  }

  const areaUnit = raw.area_unit || 'sqft'
  const formattedArea = area ? `${Number(area).toLocaleString('en-US')} ${areaUnit}` : '—'

  // 7. Commercial: Price, Currency, Purpose, Period
  const numericPrice = parseNumericPrice(raw.price)
  const currency = raw.currency || 'AED'
  const formattedPrice = formatAedPrice(numericPrice, currency)

  const purpose = raw.purpose || (
    raw.price_period === 'per year' || raw.price_period === 'per month' 
      ? 'rent' 
      : (source === 'record' ? 'sale' : null)
  )

  let pricePeriod = raw.price_period || null
  if (!pricePeriod) {
    if (purpose === 'rent' || purpose === 'lease') {
      pricePeriod = 'per year'
    } else if (purpose === 'sale') {
      pricePeriod = 'one-time'
    }
  }

  let formattedPriceWithPeriod = formattedPrice
  if (numericPrice !== null) {
    if (pricePeriod === 'per year') {
      formattedPriceWithPeriod = `${formattedPrice} / year`
    } else if (pricePeriod === 'per month') {
      formattedPriceWithPeriod = `${formattedPrice} / month`
    }
  }

  // 8. Location
  const location = raw.location ? String(raw.location).trim() : 'Dubai, UAE'

  // 9. Title
  let title = raw.title ? String(raw.title).trim() : ''
  if (!title) {
    if (raw.highlights && typeof raw.highlights === 'string' && raw.highlights.length < 80) {
      title = raw.highlights.split(/[;\n]/)[0].trim()
    } else {
      title = `${propertyType} in ${location}`
    }
  }

  // 10. Media / Images
  let primaryImage = raw.primary_image || raw.featured_image || null
  let images = []

  if (Array.isArray(raw.images)) {
    images = raw.images
      .map((item) => (typeof item === 'string' ? item : item?.url || ''))
      .filter((u) => Boolean(u && typeof u === 'string' && u.startsWith('http')))
  } else if (typeof raw.images === 'string' && raw.images.trim().startsWith('[')) {
    try {
      const parsed = JSON.parse(raw.images)
      if (Array.isArray(parsed)) {
        images = parsed
          .map((item) => (typeof item === 'string' ? item : item?.url || ''))
          .filter((u) => Boolean(u && typeof u === 'string' && u.startsWith('http')))
      }
    } catch {
      images = []
    }
  }

  if (!primaryImage && images.length > 0) {
    primaryImage = images[0]
  }

  const hasRealImage = Boolean(primaryImage && typeof primaryImage === 'string' && primaryImage.startsWith('http'))
  const fallbackEmoji = getPropertyEmoji(propertyType)

  // 11. Lifecycle & Governance
  const availability = raw.availability || 'available'
  const verificationStatus = raw.verification_status || (raw.is_approved ? 'verified' : 'unverified')
  const isApproved = Boolean(raw.is_approved)
  const isPublished = Boolean(raw.is_published)

  return {
    id,
    referenceNumber,
    title,
    description: raw.description || '',
    propertyType,
    source,
    isDemo,
    price: numericPrice,
    currency,
    formattedPrice,
    purpose,
    pricePeriod,
    formattedPriceWithPeriod,
    location,
    bedrooms,
    bedroomLabel,
    bathrooms,
    bathroomLabel,
    area,
    areaUnit,
    formattedArea,
    primaryImage,
    images,
    hasRealImage,
    fallbackEmoji,
    availability,
    verificationStatus,
    isApproved,
    isPublished,
    highlights: raw.highlights || '',
    amenities: Array.isArray(raw.amenities) ? raw.amenities : [],
    // Preserve original raw object for any low-level backward-compat need
    _raw: raw,
  }
}

export default adaptProperty

