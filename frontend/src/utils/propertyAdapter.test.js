import test from 'node:test'
import assert from 'node:assert/strict'
import { adaptProperty, formatAedPrice, parseNumericPrice } from './propertyAdapter.js'

test('adaptProperty: full PostgreSQL DB property record', () => {
  const raw = {
    id: 101,
    external_ref: 'LYKA-DXB-V101',
    title: 'Signature Villa Palm Jumeirah',
    purpose: 'sale',
    price: 35000000,
    currency: 'AED',
    property_type: 'Villa',
    location: 'Palm Jumeirah, Dubai',
    bedrooms: 6,
    bathrooms: 7,
    area: 9500,
    area_unit: 'sqft',
    primary_image: 'https://images.unsplash.com/photo-1613490493576-7fde63acd811',
    images: ['https://images.unsplash.com/photo-1613490493576-7fde63acd811'],
    is_approved: true,
    is_published: true,
    availability: 'available',
    is_demo: false,
    source: 'record',
  }

  const p = adaptProperty(raw)
  assert.equal(p.id, 101)
  assert.equal(p.referenceNumber, 'LYKA-DXB-V101')
  assert.equal(p.title, 'Signature Villa Palm Jumeirah')
  assert.equal(p.propertyType, 'Villa')
  assert.equal(p.source, 'record')
  assert.equal(p.isDemo, false)
  assert.equal(p.price, 35000000)
  assert.equal(p.formattedPrice, 'AED 35,000,000')
  assert.equal(p.formattedPriceWithPeriod, 'AED 35,000,000')
  assert.equal(p.bedrooms, 6)
  assert.equal(p.bedroomLabel, '6 Beds')
  assert.equal(p.bathrooms, 7)
  assert.equal(p.bathroomLabel, '7 Baths')
  assert.equal(p.formattedArea, '9,500 sqft')
  assert.equal(p.hasRealImage, true)
  assert.equal(p.fallbackEmoji, '🏡')
})

test('adaptProperty: rental property correctly attaches / year suffix', () => {
  const raw = {
    id: 202,
    purpose: 'rent',
    price: 180000,
    property_type: 'Apartment',
    location: 'Downtown Dubai',
    bedrooms: 2,
    bathrooms: 2,
    area: 1200,
  }

  const p = adaptProperty(raw)
  assert.equal(p.purpose, 'rent')
  assert.equal(p.pricePeriod, 'per year')
  assert.equal(p.formattedPriceWithPeriod, 'AED 180,000 / year')
  assert.equal(p.bedroomLabel, '2 Beds')
  assert.equal(p.bathroomLabel, '2 Baths')
})

test('adaptProperty: studio property with 0 bedrooms labels as Studio, NOT 0 Beds', () => {
  const raw = {
    id: 303,
    title: 'Cozy Canal Studio',
    property_type: 'Studio',
    bedrooms: 0,
    bathrooms: 1,
    price: 650000,
  }

  const p = adaptProperty(raw)
  assert.equal(p.bedrooms, 0)
  assert.equal(p.bedroomLabel, 'Studio')
  assert.equal(p.bathroomLabel, '1 Bath')
})

test('adaptProperty: legacy UAE dataset item with no__of__beds and string price', () => {
  const raw = {
    property_id: 1542,
    no__of__beds: 'Studio',
    no_of_baths: 1.0,
    price: '48,000',
    property_type: 'Studio',
    location: 'International City',
    highlights: 'Well maintained studio apartment',
    source: 'dataset',
  }

  const p = adaptProperty(raw)
  assert.equal(p.id, 1542)
  assert.equal(p.source, 'dataset')
  assert.equal(p.price, 48000)
  assert.equal(p.formattedPrice, 'AED 48,000')
  assert.equal(p.bedrooms, 0)
  assert.equal(p.bedroomLabel, 'Studio')
  assert.equal(p.bathrooms, 1.0)
  assert.equal(p.bathroomLabel, '1 Bath')
  assert.equal(p.fallbackEmoji, '🏠')
})

test('adaptProperty: Indian grouping price 65,00,000 parses correctly', () => {
  assert.equal(parseNumericPrice('65,00,000'), 6500000)
  const p = adaptProperty({ price: '65,00,000' })
  assert.equal(p.price, 6500000)
  assert.equal(p.formattedPrice, 'AED 6,500,000')
})

test('adaptProperty: missing optional fields do not crash and produce honest labels', () => {
  const p = adaptProperty({ id: 505 })
  assert.equal(p.id, 505)
  assert.equal(p.formattedPrice, 'Price on request')
  assert.equal(p.bedroomLabel, '—')
  assert.equal(p.bathroomLabel, '—')
  assert.equal(p.formattedArea, '—')
  assert.equal(p.hasRealImage, false)
})

