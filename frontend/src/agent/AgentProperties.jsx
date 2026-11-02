import React from 'react'
import { Link, useParams, useNavigate } from 'react-router-dom'
import api from '../api.js'
import { useAuth, hasPerm } from '../auth/AuthContext.jsx'
import { formatAedPrice } from '../utils/propertyAdapter.js'

export const PURPOSES = [
  ['sale', 'For Sale'],
  ['rent', 'For Rent'],
  ['lease', 'For Lease'],
]

export const AVAILABILITIES = [
  ['available', 'Available'],
  ['reserved', 'Reserved'],
  ['sold', 'Sold'],
  ['rented', 'Rented'],
  ['off_market', 'Off Market (Archived)'],
]

export const PROPERTY_TYPES = [
  'Apartment',
  'Villa',
  'Townhouse',
  'Penthouse',
  'Studio',
  'Duplex',
  'Hotel Apartment',
  'Commercial',
  'Residential Plot',
]

const PAGE_SIZE = 20

// Market Dataset & Custom Staging Ingestion Pipeline
function fmtPrice(price, currency = 'AED', purpose = 'sale') {
  const base = formatAedPrice(price, currency)
  if (base === 'Price on request') return base
  const suffix = purpose === 'rent' || purpose === 'lease' ? ' / year' : ''
  return `${base}${suffix}`
}

function fmtDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString([], {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function emptyForm() {
  return {
    title: '',
    external_ref: '',
    purpose: 'sale',
    availability: 'available',
    price: '',
    currency: 'AED',
    property_type: 'Apartment',
    location: '',
    bedrooms: 1,
    bathrooms: 1,
    area: '',
    area_unit: 'sqft',
    amenities_text: '',
    highlights: '',
    description: '',
    is_approved: false,
    is_published: false,
    verification_status: 'unverified',
    images_text: '',
  }
}

function propToForm(p) {
  let imagesStr = ''
  try {
    if (Array.isArray(p.images)) {
      imagesStr = p.images.map((img) => (typeof img === 'string' ? img : img.url)).join('\n')
    } else if (typeof p.images === 'string') {
      const parsed = JSON.parse(p.images)
      imagesStr = Array.isArray(parsed)
        ? parsed.map((img) => (typeof img === 'string' ? img : img.url)).join('\n')
        : p.images
    }
  } catch {
    imagesStr = ''
  }

  return {
    title: p.title || '',
    external_ref: p.external_ref || '',
    purpose: p.purpose || 'sale',
    availability: p.availability || 'available',
    price: p.price != null ? String(p.price) : '',
    currency: p.currency || 'AED',
    property_type: p.property_type || 'Apartment',
    location: p.location || '',
    bedrooms: p.bedrooms != null ? p.bedrooms : 0,
    bathrooms: p.bathrooms != null ? p.bathrooms : 1,
    area: p.area != null ? String(p.area) : '',
    area_unit: p.area_unit || 'sqft',
    amenities_text: Array.isArray(p.amenities) ? p.amenities.join(', ') : '',
    highlights: p.highlights || '',
    description: p.description || '',
    is_approved: Boolean(p.is_approved),
    is_published: Boolean(p.is_published),
    verification_status: p.verification_status || 'unverified',
    images_text: imagesStr,
  }
}

export default function AgentProperties() {
  const { id: routePropertyId } = useParams()
  const navigate = useNavigate()
  const { permissions } = useAuth()

  const canCreate = hasPerm({ permissions }, 'properties.create')
  const canUpdate = hasPerm({ permissions }, 'properties.update')
  const canDelete = hasPerm({ permissions }, 'properties.delete')
  const canManage = canCreate || canUpdate || canDelete

  // Workspace View Mode: 'inventory' | 'import_staging'
  const [activeTab, setActiveTab] = React.useState('inventory')

  // Inventory Table State
  const [rows, setRows] = React.useState([])
  const [total, setTotal] = React.useState(0)
  const [summary, setSummary] = React.useState(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState(null)
  const [banner, setBanner] = React.useState(null)

  // Selection for bulk actions
  const [selectedIds, setSelectedIds] = React.useState([])
  const [bulkLoading, setBulkLoading] = React.useState(false)

  // Filters
  const [lifecycleTab, setLifecycleTab] = React.useState('all') // 'all'|'published'|'pending'|'unverified'|'rejected'|'off_market'
  const [q, setQ] = React.useState('')
  const [purpose, setPurpose] = React.useState('')
  const [availability, setAvailability] = React.useState('')
  const [propertyType, setPropertyType] = React.useState('')
  const [location, setLocation] = React.useState('')
  const [minBedrooms, setMinBedrooms] = React.useState('')
  const [minPrice, setMinPrice] = React.useState('')
  const [maxPrice, setMaxPrice] = React.useState('')
  const [sourceFilter, setSourceFilter] = React.useState('crm')
  const [sort, setSort] = React.useState('newest')
  const [offset, setOffset] = React.useState(0)

  // Selected property detail & modal state
  const [selected, setSelected] = React.useState(null)
  const [detailLoading, setDetailLoading] = React.useState(false)
  const [modalMode, setModalMode] = React.useState(null) // 'create' | 'edit' | null
  const [form, setForm] = React.useState(emptyForm)
  const [formError, setFormError] = React.useState(null)
  const [saving, setSaving] = React.useState(false)

  // Rejection reason dialog
  const [rejectDialog, setRejectDialog] = React.useState({ open: false, property: null, reason: '' })

  // Media management modal (PostgreSQL Persistent Storage + URLs)
  const [imagesModal, setImagesModal] = React.useState({
    open: false,
    property: null,
    storedImages: [],
    loadingStored: false,
    selectedFiles: [],
    uploading: false,
    uploadProgress: '',
    setPrimaryOnUpload: true,
    error: null,
    activeSubTab: 'upload', // 'upload' | 'urls'
    imagesText: '',
    primary: '',
  })

  // Close popup modal or detail drawer on Escape key
  React.useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        if (modalMode) setModalMode(null)
        else if (rejectDialog.open) setRejectDialog({ open: false, property: null, reason: '' })
        else if (imagesModal.open) setImagesModal((prev) => ({ ...prev, open: false, selectedFiles: [], error: null }))
        else if (selected) setSelected(null)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [modalMode, selected, rejectDialog.open, imagesModal.open])

  // Import Preview & Staging State
  const [importState, setImportState] = React.useState({
    inputMode: 'dataset_sample', // 'dataset_sample' | 'custom_json'
    customJsonText: '',
    preview: null,
    previewLoading: false,
    stageLoading: false,
    batchResult: null,
    error: null,
  })

  // Build query parameters based on lifecycle tab and filters
  const buildQueryParams = React.useCallback(
    (customOffset = offset) => {
      const effectiveIncludeDataset = !canManage || sourceFilter !== 'crm'
      const params = {
        sort,
        limit: PAGE_SIZE,
        offset: customOffset,
        include_dataset: effectiveIncludeDataset,
      }
      if (canManage && ['manual', 'demo_seed', 'uae_dataset'].includes(sourceFilter)) {
        params.source = sourceFilter
      }
      if (q.trim()) params.q = q.trim()
      if (purpose) params.purpose = purpose
      if (propertyType.trim()) params.property_type = propertyType.trim()
      if (location.trim()) params.location = location.trim()
      if (minBedrooms !== '') params.min_bedrooms = minBedrooms
      if (minPrice !== '') params.min_price = minPrice
      if (maxPrice !== '') params.max_price = maxPrice

      // Apply lifecycle tab semantics
      if (lifecycleTab === 'published') {
        params.is_published = true
        params.approved = true
        params.availability = 'available'
      } else if (lifecycleTab === 'pending') {
        params.verification_status = 'pending_review'
      } else if (lifecycleTab === 'unverified') {
        params.verification_status = 'unverified'
      } else if (lifecycleTab === 'rejected') {
        params.verification_status = 'rejected'
      } else if (lifecycleTab === 'off_market') {
        params.availability = 'off_market'
      } else if (availability) {
        params.availability = availability
      }

      return params
    },
    [
      canManage,
      q,
      purpose,
      availability,
      propertyType,
      location,
      minBedrooms,
      minPrice,
      maxPrice,
      sourceFilter,
      sort,
      offset,
      lifecycleTab,
    ],
  )

  const fetchInventory = React.useCallback(
    (targetOffset = 0) => {
      setLoading(true)
      api
        .agentProperties(buildQueryParams(targetOffset))
        .then((res) => {
          setRows(res.results || [])
          setTotal(res.total || 0)
          if (res.summary) setSummary(res.summary)
          setError(null)
          setSelectedIds([]) // Reset multi-selection on reload
        })
        .catch((err) => setError(err.message || 'Failed to load property inventory'))
        .finally(() => setLoading(false))
    },
    [buildQueryParams],
  )

  React.useEffect(() => {
    setOffset(0)
    const timer = setTimeout(() => {
      fetchInventory(0)
    }, 200)
    return () => clearTimeout(timer)
  }, [
    q,
    purpose,
    availability,
    propertyType,
    location,
    minBedrooms,
    minPrice,
    maxPrice,
    sourceFilter,
    sort,
    lifecycleTab,
    fetchInventory,
  ])

  // Open detail drawer if route has :id
  React.useEffect(() => {
    if (!routePropertyId) return
    const pid = Number(routePropertyId)
    if (!Number.isFinite(pid) || pid <= 0) return
    setDetailLoading(true)
    api
      .agentProperty(pid)
      .then((res) => {
        setSelected(res.property)
      })
      .catch((err) => {
        setError(err.message || 'Property not found')
      })
      .finally(() => setDetailLoading(false))
  }, [routePropertyId])

  const openDetail = async (prop) => {
    setDetailLoading(true)
    setSelected(prop)
    try {
      const res = await api.agentProperty(prop.id)
      setSelected(res.property)
    } catch (err) {
      setError(err.message)
    } finally {
      setDetailLoading(false)
    }
  }

  const closeDetail = () => {
    setSelected(null)
    if (routePropertyId) {
      navigate('/agent/properties', { replace: true })
    }
  }

  const openCreateModal = () => {
    setForm(emptyForm())
    setFormError(null)
    setModalMode('create')
  }

  const openEditModal = (prop) => {
    setForm(propToForm(prop))
    setFormError(null)
    setSelected(prop)
    setModalMode('edit')
  }

  // Multi-selection handlers
  const handleSelectAll = (e) => {
    if (e.target.checked) {
      setSelectedIds(rows.map((r) => r.id))
    } else {
      setSelectedIds([])
    }
  }

  const handleToggleSelectRow = (pid) => {
    setSelectedIds((prev) =>
      prev.includes(pid) ? prev.filter((id) => id !== pid) : [...prev, pid],
    )
  }

  // Lifecycle transitions
  const handleSubmitReview = async (prop) => {
    try {
      const res = await api.submitPropertyForReview(prop.id)
      setBanner(`Property #${prop.id} submitted for verification review.`)
      setRows((prev) => prev.map((r) => (r.id === prop.id ? res.property : r)))
      if (selected && selected.id === prop.id) setSelected(res.property)
      fetchInventory(offset)
    } catch (err) {
      setError(err.message || 'Failed to submit property for review')
    }
  }

  const handleApprove = async (prop) => {
    if (!canUpdate) return
    try {
      const res = await api.approveProperty(prop.id)
      setBanner(`Property #${prop.id} verified and approved.`)
      setRows((prev) => prev.map((r) => (r.id === prop.id ? res.property : r)))
      if (selected && selected.id === prop.id) setSelected(res.property)
      fetchInventory(offset)
    } catch (err) {
      setError(err.message || 'Failed to approve property')
    }
  }

  const handleRejectPrompt = (prop) => {
    setRejectDialog({ open: true, property: prop, reason: '' })
  }

  const handleRejectConfirm = async () => {
    if (!rejectDialog.property || !rejectDialog.reason.trim()) return
    try {
      const res = await api.rejectProperty(rejectDialog.property.id, rejectDialog.reason.trim())
      setBanner(`Property #${rejectDialog.property.id} rejected: "${rejectDialog.reason.trim()}".`)
      setRows((prev) => prev.map((r) => (r.id === rejectDialog.property.id ? res.property : r)))
      if (selected && selected.id === rejectDialog.property.id) setSelected(res.property)
      setRejectDialog({ open: false, property: null, reason: '' })
      fetchInventory(offset)
    } catch (err) {
      setError(err.message || 'Failed to reject property')
    }
  }

  const handlePublish = async (prop) => {
    if (!canUpdate) return
    try {
      const res = await api.publishProperty(prop.id)
      setBanner(`Property #${prop.id} published live for customer discovery.`)
      setRows((prev) => prev.map((r) => (r.id === prop.id ? res.property : r)))
      if (selected && selected.id === prop.id) setSelected(res.property)
      fetchInventory(offset)
    } catch (err) {
      setError(err.message || 'Failed to publish property')
    }
  }

  const handleUnpublish = async (prop) => {
    if (!canUpdate) return
    if (!window.confirm(`Unpublish #${prop.id} (“${prop.title}”)? It will be hidden from customer portals.`)) {
      return
    }
    try {
      const res = await api.unpublishProperty(prop.id)
      setBanner(`Property #${prop.id} unpublished.`)
      setRows((prev) => prev.map((r) => (r.id === prop.id ? res.property : r)))
      if (selected && selected.id === prop.id) setSelected(res.property)
      fetchInventory(offset)
    } catch (err) {
      setError(err.message || 'Failed to unpublish property')
    }
  }

  const handleArchive = async (prop) => {
    if (!canUpdate && !canDelete) return
    if (!window.confirm(`Archive property #${prop.id} off-market? Active customer viewings will be halted.`)) {
      return
    }
    try {
      const res = await api.archiveAgentProperty(prop.id)
      setRows((prev) => prev.map((r) => (r.id === prop.id ? res.property : r)))
      if (selected && selected.id === prop.id) setSelected(res.property)
      setBanner(`Property #${prop.id} archived (off_market).`)
      fetchInventory(offset)
    } catch (err) {
      setError(err.message || 'Failed to archive property')
    }
  }

  // Bulk actions
  const handleBulkAction = async (action) => {
    if (selectedIds.length === 0) return
    const actionLabel = action.toUpperCase()
    if (!window.confirm(`Execute ${actionLabel} on ${selectedIds.length} selected property listing(s)?`)) {
      return
    }
    setBulkLoading(true)
    try {
      const res = await api.bulkPropertyAction(selectedIds, action)
      setBanner(`Bulk ${action} completed: ${res.succeeded_count} succeeded, ${res.failed_count} failed.`)
      if (res.failed_count > 0 && res.failures?.length) {
        setError(`Errors on some items: ${res.failures.map((f) => `#${f.property_id}: ${f.error}`).join('; ')}`)
      }
      setSelectedIds([])
      fetchInventory(offset)
    } catch (err) {
      setError(err.message || 'Bulk action failed')
    } finally {
      setBulkLoading(false)
    }
  }

  // Media modal open & PostgreSQL binary storage handlers
  const openImagesModal = async (prop) => {
    let rawUrls = ''
    try {
      const imgs = Array.isArray(prop.images) ? prop.images : JSON.parse(prop.images || '[]')
      rawUrls = imgs.map((img) => (typeof img === 'string' ? img : img.url)).join('\n')
    } catch {
      rawUrls = ''
    }
    setImagesModal({
      open: true,
      property: prop,
      storedImages: [],
      loadingStored: true,
      selectedFiles: [],
      uploading: false,
      uploadProgress: '',
      setPrimaryOnUpload: true,
      error: null,
      activeSubTab: 'upload',
      imagesText: rawUrls,
      primary: prop.primary_image || '',
    })
    try {
      const res = await api.getPropertyImages(prop.id)
      setImagesModal((prev) => ({
        ...prev,
        storedImages: res.images || [],
        loadingStored: false,
      }))
    } catch (err) {
      setImagesModal((prev) => ({ ...prev, loadingStored: false }))
    }
  }

  const handleFileSelect = (e) => {
    const files = Array.from(e.target.files || [])
    setImagesModal((prev) => ({
      ...prev,
      selectedFiles: files,
      error: null,
    }))
  }

  const handleUploadLocalFiles = async () => {
    if (!imagesModal.property || imagesModal.selectedFiles.length === 0) return
    setImagesModal((prev) => ({
      ...prev,
      uploading: true,
      uploadProgress: 'Starting upload to PostgreSQL...',
      error: null,
    }))
    try {
      const propId = imagesModal.property.id
      for (let i = 0; i < imagesModal.selectedFiles.length; i++) {
        const file = imagesModal.selectedFiles[i]
        const isPrimary = imagesModal.setPrimaryOnUpload && i === 0 && imagesModal.storedImages.length === 0
        setImagesModal((prev) => ({
          ...prev,
          uploadProgress: `Uploading file ${i + 1} of ${prev.selectedFiles.length}: ${file.name}...`,
        }))
        await api.uploadPropertyImage(propId, file, { isPrimary })
      }
      const [imgRes, propRes] = await Promise.all([
        api.getPropertyImages(propId),
        api.agentProperty(propId),
      ])
      const updatedProp = propRes.property
      setImagesModal((prev) => ({
        ...prev,
        storedImages: imgRes.images || [],
        selectedFiles: [],
        uploading: false,
        uploadProgress: 'Upload complete! Stored in PostgreSQL.',
        property: updatedProp,
        primary: updatedProp.primary_image || '',
      }))
      setRows((prev) => prev.map((r) => (r.id === updatedProp.id ? updatedProp : r)))
      if (selected && selected.id === updatedProp.id) setSelected(updatedProp)
      setBanner(`Successfully stored ${imagesModal.selectedFiles.length} image(s) in PostgreSQL for property #${propId}.`)
    } catch (err) {
      setImagesModal((prev) => ({
        ...prev,
        uploading: false,
        error: err.message || 'Image upload failed.',
      }))
    }
  }

  const handleSetPrimaryImage = async (imgId) => {
    if (!imagesModal.property) return
    try {
      const propId = imagesModal.property.id
      await api.setPropertyPrimaryImage(propId, imgId)
      const [imgRes, propRes] = await Promise.all([
        api.getPropertyImages(propId),
        api.agentProperty(propId),
      ])
      const updatedProp = propRes.property
      setImagesModal((prev) => ({
        ...prev,
        storedImages: imgRes.images || [],
        property: updatedProp,
        primary: updatedProp.primary_image || '',
      }))
      setRows((prev) => prev.map((r) => (r.id === updatedProp.id ? updatedProp : r)))
      if (selected && selected.id === updatedProp.id) setSelected(updatedProp)
      setBanner(`Primary listing thumbnail updated for property #${propId}.`)
    } catch (err) {
      setImagesModal((prev) => ({ ...prev, error: err.message || 'Failed to set primary image' }))
    }
  }

  const handleDeleteImage = async (imgId) => {
    if (!imagesModal.property) return
    if (!window.confirm('Delete this image from PostgreSQL database storage?')) return
    try {
      const propId = imagesModal.property.id
      await api.deletePropertyImage(propId, imgId)
      const [imgRes, propRes] = await Promise.all([
        api.getPropertyImages(propId),
        api.agentProperty(propId),
      ])
      const updatedProp = propRes.property
      setImagesModal((prev) => ({
        ...prev,
        storedImages: imgRes.images || [],
        property: updatedProp,
        primary: updatedProp.primary_image || '',
      }))
      setRows((prev) => prev.map((r) => (r.id === updatedProp.id ? updatedProp : r)))
      if (selected && selected.id === updatedProp.id) setSelected(updatedProp)
      setBanner(`Image deleted from PostgreSQL for property #${propId}.`)
    } catch (err) {
      setImagesModal((prev) => ({ ...prev, error: err.message || 'Failed to delete image' }))
    }
  }

  const handleShareProperty = (p) => {
    const url = `${window.location.origin}/properties?q=${encodeURIComponent(p.title)}`
    const summaryText = `${p.title} (${p.location}) · ${fmtPrice(p.price, p.currency, p.purpose)} · ${p.bedrooms === 0 ? 'Studio' : p.bedrooms + ' Bed'} · Details: ${url}`
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(summaryText)
      setBanner(`Copied listing link & summary for "${p.title}" to clipboard!`)
    } else {
      setBanner(`Property: ${summaryText}`)
    }
  }

  const handleTogglePublish = async (p) => {
    try {
      const res = p.is_published
        ? await api.unpublishProperty(p.id)
        : await api.publishProperty(p.id)
      setBanner(p.is_published ? `Unpublished property #${p.id}.` : `Published property #${p.id} to live website & concierge.`)
      setRows((prev) => prev.map((r) => (r.id === p.id ? res.property : r)))
      if (selected && selected.id === p.id) setSelected(res.property)
    } catch (err) {
      setError(err.message || 'Failed to update publication status')
    }
  }

  const handleSaveImages = async () => {
    if (!imagesModal.property) return
    const urls = imagesModal.imagesText
      .split('\n')
      .map((u) => u.trim())
      .filter(Boolean)
    try {
      const res = await api.updatePropertyImages(
        imagesModal.property.id,
        urls,
        imagesModal.primary.trim() || null,
      )
      setBanner(`Updated media for property #${imagesModal.property.id}.`)
      setRows((prev) => prev.map((r) => (r.id === imagesModal.property.id ? res.property : r)))
      if (selected && selected.id === imagesModal.property.id) setSelected(res.property)
      setImagesModal((prev) => ({ ...prev, open: false }))
    } catch (err) {
      setImagesModal((prev) => ({ ...prev, error: err.message || 'Failed to update images' }))
    }
  }

  // Form Submit (Create / Edit)
  const handleFormSubmit = async (e) => {
    e.preventDefault()
    setFormError(null)

    if (!form.title.trim()) {
      setFormError('Title is required.')
      return
    }
    if (!form.location.trim()) {
      setFormError('Location is required.')
      return
    }
    if (!form.property_type.trim()) {
      setFormError('Property type is required.')
      return
    }
    const parsedPrice = Number(String(form.price).replace(/,/g, '').trim())
    if (form.price === '' || Number.isNaN(parsedPrice) || parsedPrice <= 0) {
      setFormError('Please enter a valid positive price (> 0).')
      return
    }

    const amenities = form.amenities_text
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)

    const imagesList = form.images_text
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean)

    const payload = {
      title: form.title.trim(),
      external_ref: form.external_ref.trim() || null,
      purpose: form.purpose,
      availability: form.availability,
      price: parsedPrice,
      currency: (form.currency || 'AED').trim().toUpperCase(),
      property_type: form.property_type.trim(),
      location: form.location.trim(),
      bedrooms: Number(form.bedrooms) || 0,
      bathrooms: Number(form.bathrooms) || 1,
      area: form.area ? Number(String(form.area).replace(/,/g, '').trim()) : null,
      area_unit: (form.area_unit || 'sqft').trim() || 'sqft',
      amenities,
      highlights: form.highlights.trim() || null,
      description: form.description.trim(),
      images: imagesList,
      primary_image: imagesList[0] || null,
      is_approved: Boolean(form.is_approved),
      is_published: Boolean(form.is_published),
      verification_status: form.verification_status || 'unverified',
    }

    setSaving(true)
    try {
      if (modalMode === 'create') {
        const res = await api.createAgentProperty(payload)
        setBanner(`Created property #${res.property.id} (“${res.property.title}”).`)
        setSelected(res.property)
      } else if (modalMode === 'edit' && selected) {
        const res = await api.updateAgentProperty(selected.id, payload)
        setBanner(`Updated property #${res.property.id} (“${res.property.title}”).`)
        setSelected(res.property)
      }
      setModalMode(null)
      fetchInventory(offset)
    } catch (err) {
      setFormError(err.message || 'Could not save property.')
    } finally {
      setSaving(false)
    }
  }

  // Import Preview & Staging handlers
  const handleRunImportPreview = async () => {
    let recordsToPreview = []
    if (importState.inputMode === 'dataset_sample') {
      try {
        setImportState((prev) => ({ ...prev, previewLoading: true, error: null }))
        const dsRes = await api.listDataset({ limit: 5 })
        recordsToPreview = dsRes.results || []
      } catch (err) {
        setImportState((prev) => ({ ...prev, error: `Failed to load dataset sample: ${err.message}`, previewLoading: false }))
        return
      }
    } else {
      try {
        recordsToPreview = JSON.parse(importState.customJsonText || '[]')
        if (!Array.isArray(recordsToPreview)) {
          throw new Error('Custom payload must be an array of property objects.')
        }
      } catch (err) {
        setImportState((prev) => ({ ...prev, error: `Invalid JSON format: ${err.message}` }))
        return
      }
    }

    if (recordsToPreview.length === 0) {
      setImportState((prev) => ({ ...prev, error: 'No records provided for preview.', previewLoading: false }))
      return
    }

    setImportState((prev) => ({ ...prev, previewLoading: true, error: null, batchResult: null }))
    try {
      const preview = await api.previewPropertyImport(recordsToPreview)
      setImportState((prev) => ({ ...prev, preview, previewLoading: false }))
    } catch (err) {
      setImportState((prev) => ({ ...prev, error: err.message || 'Import preview failed', previewLoading: false }))
    }
  }

  const handleExecuteImportStaging = async () => {
    let recordsToStage = []
    if (importState.inputMode === 'dataset_sample') {
      try {
        const dsRes = await api.listDataset({ limit: 5 })
        recordsToStage = dsRes.results || []
      } catch (err) {
        setImportState((prev) => ({ ...prev, error: `Failed to load dataset sample: ${err.message}` }))
        return
      }
    } else {
      try {
        recordsToStage = JSON.parse(importState.customJsonText || '[]')
      } catch {
        return
      }
    }

    if (!window.confirm(`Stage ${recordsToStage.length} property records into the database? Records will be ingested strictly as UNVERIFIED, UNAPPROVED, and OFF-MARKET.`)) {
      return
    }

    setImportState((prev) => ({ ...prev, stageLoading: true, error: null }))
    try {
      const res = await api.stagePropertyImport(
        recordsToStage,
        'synthetic_fixture',
        'synthetic_fixture_v1.json',
        true,
        false,
      )
      setImportState((prev) => ({ ...prev, batchResult: res, stageLoading: false }))
      setBanner(`Staged import batch ${res.batch_id}: ${res.imported_records} imported, ${res.duplicate_records} duplicates skipped.`)
      fetchInventory(0)
    } catch (err) {
      setImportState((prev) => ({ ...prev, error: err.message || 'Staging execution failed', stageLoading: false }))
    }
  }

  const resetFilters = () => {
    setQ('')
    setPurpose('')
    setAvailability('')
    setPropertyType('')
    setLocation('')
    setMinBedrooms('')
    setMinPrice('')
    setMaxPrice('')
    setSourceFilter('crm')
    setSort('newest')
    setLifecycleTab('all')
  }

  const goPage = (newOffset) => {
    const clamped = Math.max(0, newOffset)
    setOffset(clamped)
    fetchInventory(clamped)
  }

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', paddingBottom: 60 }}>
      {/* Top Workspace Command Bar */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 18,
          flexWrap: 'wrap',
          gap: 12,
          background: '#ffffff',
          padding: '12px 18px',
          borderRadius: 12,
          border: '1px solid #ebdbe4',
          boxShadow: '0 1px 3px rgba(90, 22, 69, 0.04)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ background: '#f8f4f7', padding: 4, borderRadius: 8, display: 'flex', gap: 4 }}>
            <button
              type="button"
              className={`btn btn-xs ${activeTab === 'inventory' ? '' : 'btn-ghost'}`}
              onClick={() => setActiveTab('inventory')}
              style={{
                background: activeTab === 'inventory' ? '#5a1645' : 'transparent',
                color: activeTab === 'inventory' ? '#ffffff' : '#64748b',
                fontWeight: 600,
                padding: '6px 14px',
                border: 'none',
              }}
            >
              🏢 Inventory Workspace
            </button>
            {canManage && (
              <button
                type="button"
                className={`btn btn-xs ${activeTab === 'import_staging' ? '' : 'btn-ghost'}`}
                onClick={() => setActiveTab('import_staging')}
                style={{
                  background: activeTab === 'import_staging' ? '#5a1645' : 'transparent',
                  color: activeTab === 'import_staging' ? '#ffffff' : '#64748b',
                  fontWeight: 600,
                  padding: '6px 14px',
                  border: 'none',
                }}
              >
                📥 Safe Data Staging &amp; Dry-Run
              </button>
            )}
          </div>
          <span style={{ fontSize: 13, color: '#64748b' }}>
            Verified UAE real-estate inventory &amp; publication governance
          </span>
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <a
            href="/properties"
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-xs btn-ghost"
            style={{
              color: '#5a1645',
              borderColor: '#d4c0ce',
              padding: '6px 12px',
              textDecoration: 'none',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
            }}
          >
            Public Catalogue ↗
          </a>

          {canCreate && activeTab === 'inventory' && (
            <button
              type="button"
              className="btn btn-xs"
              onClick={openCreateModal}
              style={{
                background: '#5a1645',
                color: '#e8bd68',
                border: '1px solid #e8bd68',
                fontWeight: 700,
                padding: '7px 16px',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 5,
                boxShadow: '0 2px 8px rgba(90, 22, 69, 0.2)',
              }}
            >
              <span style={{ fontSize: 14 }}>＋</span> New Listing
            </button>
          )}
        </div>
      </div>

      {/* Executive KPI Overview Cards */}
      {summary && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: 12,
            marginBottom: 22,
          }}
        >
          {[
            {
              tab: 'all',
              label: 'Total Inventory',
              count: summary.total,
              sub: 'Active CRM listings',
              color: '#5a1645',
              bg: '#fcf8fa',
            },
            {
              tab: 'published',
              label: 'Published & Live',
              count: summary.published || 0,
              sub: 'Live on website & LykAI',
              color: '#10b981',
              bg: '#f0fdf4',
            },
            {
              tab: 'pending',
              label: 'Pending Review',
              count: summary.pending_approval || 0,
              sub: 'Awaiting admin audit',
              color: '#f59e0b',
              bg: '#fffbeb',
            },
            {
              tab: 'unverified',
              label: 'Unverified Staged',
              count: summary.unverified || 0,
              sub: 'Quarantined from public',
              color: '#64748b',
              bg: '#f8fafc',
            },
            {
              tab: 'all',
              label: 'Reserved / Closed',
              count: summary.reserved_or_closed || 0,
              sub: 'Under deal or transacted',
              color: '#8b5cf6',
              bg: '#faf5ff',
            },
            {
              tab: 'off_market',
              label: 'Off-Market',
              count: summary.archived || 0,
              sub: 'Historical archives',
              color: '#94a3b8',
              bg: '#f8fafc',
            },
          ].map((kpi, idx) => {
            const isTabActive = lifecycleTab === kpi.tab && kpi.tab !== 'all'
            return (
              <div
                key={idx}
                onClick={() => kpi.tab && setLifecycleTab(kpi.tab)}
                style={{
                  background: '#ffffff',
                  border: isTabActive ? `2px solid ${kpi.color}` : '1px solid #e2e8f0',
                  borderLeft: `4px solid ${kpi.color}`,
                  borderRadius: 12,
                  padding: '14px 16px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 3,
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.transform = 'translateY(-2px)'
                  e.currentTarget.style.boxShadow = '0 6px 14px -2px rgba(0,0,0,0.08)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.transform = 'none'
                  e.currentTarget.style.boxShadow = '0 1px 3px rgba(0,0,0,0.04)'
                }}
                title={`Filter by ${kpi.label}`}
              >
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                    color: '#64748b',
                  }}
                >
                  {kpi.label}
                </span>
                <span
                  style={{
                    fontSize: 26,
                    fontWeight: 800,
                    color: kpi.color,
                    lineHeight: 1.1,
                    fontVariantNumeric: 'tabular-nums',
                  }}
                >
                  {kpi.count.toLocaleString()}
                </span>
                <span style={{ fontSize: 11.5, color: '#94a3b8' }}>{kpi.sub}</span>
              </div>
            )
          })}
        </div>
      )}

      {/* Feedback Banners */}
      {banner && (
        <div
          style={{
            marginBottom: 16,
            padding: '12px 18px',
            background: '#ecfdf5',
            color: '#065f46',
            borderRadius: 8,
            borderLeft: '4px solid #10b981',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <span>✓ {banner}</span>
          <button className="btn btn-sm btn-ghost" onClick={() => setBanner(null)}>✕</button>
        </div>
      )}

      {error && (
        <div
          style={{
            marginBottom: 16,
            padding: '12px 18px',
            background: '#fef2f2',
            color: '#991b1b',
            borderRadius: 8,
            borderLeft: '4px solid #ef4444',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <span>⚠ {error}</span>
          <button className="btn btn-sm btn-ghost" onClick={() => setError(null)}>✕</button>
        </div>
      )}

      {/* VIEW: SAFE DATA STAGING & PREVIEW */}
      {activeTab === 'import_staging' && (
        <div className="ax-card" style={{ padding: 24, marginBottom: 24, border: '1px solid #e2e8f0' }}>
          <div style={{ borderBottom: '1px solid #e2e8f0', paddingBottom: 16, marginBottom: 20 }}>
            <h2 style={{ fontSize: 18, margin: '0 0 6px', color: '#1e293b' }}>
              Audited Property Ingestion Pipeline
            </h2>
            <p style={{ margin: 0, color: '#64748b', fontSize: 14 }}>
              Preview, validate, and safely stage external listings without touching active customer inventory.
              All imported listings are quarantined with <code>is_approved=false</code> and <code>availability=off_market</code>.
            </p>
          </div>

          {/* Test Fixture Selector */}
          <div style={{ display: 'flex', gap: 16, marginBottom: 20, alignItems: 'center', flexWrap: 'wrap' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontWeight: 600 }}>
              <input
                type="radio"
                name="inputMode"
                value="dataset_sample"
                checked={importState.inputMode === 'dataset_sample'}
                onChange={() => setImportState((prev) => ({ ...prev, inputMode: 'dataset_sample' }))}
              />
              Live Market Reference Dataset Sample (5 Real UAE Records)
            </label>

            <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontWeight: 600 }}>
              <input
                type="radio"
                name="inputMode"
                value="custom_json"
                checked={importState.inputMode === 'custom_json'}
                onChange={() => setImportState((prev) => ({ ...prev, inputMode: 'custom_json' }))}
              />
              Custom JSON Payload
            </label>

            <button
              className="btn btn-sm"
              disabled={importState.previewLoading}
              onClick={handleRunImportPreview}
              style={{ background: '#5a1645', color: '#fff', marginLeft: 'auto' }}
            >
              {importState.previewLoading ? 'Validating…' : 'Run Dry-Run Preview'}
            </button>
          </div>

          {importState.inputMode === 'custom_json' && (
            <div style={{ marginBottom: 20 }}>
              <textarea
                rows={6}
                className="ax-input"
                style={{ width: '100%', fontFamily: 'monospace', fontSize: 13 }}
                placeholder='[{"property_id": 1, "title": "...", "price": "1,500,000", "location": "Dubai Marina", ...}]'
                value={importState.customJsonText}
                onChange={(e) => setImportState((prev) => ({ ...prev, customJsonText: e.target.value }))}
              />
            </div>
          )}

          {/* Preview Results Panel */}
          {importState.preview && (
            <div style={{ background: '#f8fafc', padding: 20, borderRadius: 8, border: '1px solid #cbd5e1' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                <h3 style={{ margin: 0, fontSize: 16 }}>Dry-Run Validation Report (Zero DB Writes)</h3>
                <span style={{ fontSize: 12, padding: '4px 10px', borderRadius: 999, background: '#dcfce7', color: '#166534', fontWeight: 600 }}>
                  Safe Simulation Mode
                </span>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 20 }}>
                <div style={{ background: '#fff', padding: 12, borderRadius: 6, border: '1px solid #e2e8f0' }}>
                  <span style={{ fontSize: 12, color: '#64748b' }}>Total Processed</span>
                  <div style={{ fontSize: 20, fontWeight: 700 }}>{importState.preview.total_records}</div>
                </div>
                <div style={{ background: '#fff', padding: 12, borderRadius: 6, border: '1px solid #e2e8f0' }}>
                  <span style={{ fontSize: 12, color: '#16a34a' }}>Valid Listings</span>
                  <div style={{ fontSize: 20, fontWeight: 700, color: '#16a34a' }}>{importState.preview.valid_records}</div>
                </div>
                <div style={{ background: '#fff', padding: 12, borderRadius: 6, border: '1px solid #e2e8f0' }}>
                  <span style={{ fontSize: 12, color: '#dc2626' }}>Invalid / Rejected</span>
                  <div style={{ fontSize: 20, fontWeight: 700, color: '#dc2626' }}>{importState.preview.invalid_records}</div>
                </div>
                <div style={{ background: '#fff', padding: 12, borderRadius: 6, border: '1px solid #e2e8f0' }}>
                  <span style={{ fontSize: 12, color: '#d97706' }}>Duplicate Candidates</span>
                  <div style={{ fontSize: 20, fontWeight: 700, color: '#d97706' }}>{importState.preview.duplicate_records}</div>
                </div>
                <div style={{ background: '#fff', padding: 12, borderRadius: 6, border: '1px solid #e2e8f0' }}>
                  <span style={{ fontSize: 12, color: '#64748b' }}>Average Price</span>
                  <div style={{ fontSize: 16, fontWeight: 700 }}>
                    AED {Math.round(importState.preview.price_summary?.avg || 0).toLocaleString()}
                  </div>
                </div>
              </div>

              {/* Sample Items Table */}
              <h4 style={{ margin: '0 0 10px', fontSize: 14 }}>Sample Validated Listings Preview:</h4>
              <div style={{ overflowX: 'auto', background: '#fff', borderRadius: 6, border: '1px solid #e2e8f0', marginBottom: 20 }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                  <thead>
                    <tr style={{ background: '#f1f5f9', textAlign: 'left', borderBottom: '1px solid #cbd5e1' }}>
                      <th style={{ padding: '8px 12px' }}>#</th>
                      <th style={{ padding: '8px 12px' }}>Title</th>
                      <th style={{ padding: '8px 12px' }}>Type</th>
                      <th style={{ padding: '8px 12px' }}>Location</th>
                      <th style={{ padding: '8px 12px' }}>Price</th>
                      <th style={{ padding: '8px 12px' }}>Validation</th>
                    </tr>
                  </thead>
                  <tbody>
                    {importState.preview.preview_items?.map((item, idx) => (
                      <tr key={idx} style={{ borderBottom: '1px solid #f1f5f9' }}>
                        <td style={{ padding: '8px 12px' }}>{item.row_index + 1}</td>
                        <td style={{ padding: '8px 12px', fontWeight: 600 }}>{item.normalized?.title || '—'}</td>
                        <td style={{ padding: '8px 12px' }}>{item.normalized?.property_type || '—'}</td>
                        <td style={{ padding: '8px 12px' }}>{item.normalized?.location || '—'}</td>
                        <td style={{ padding: '8px 12px' }}>AED {Number(item.normalized?.price || 0).toLocaleString()}</td>
                        <td style={{ padding: '8px 12px' }}>
                          {item.is_valid ? (
                            <span style={{ color: '#16a34a', fontWeight: 600 }}>✓ Valid</span>
                          ) : (
                            <span style={{ color: '#dc2626', fontWeight: 600 }}>✕ {item.errors?.join(', ')}</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Action Buttons for Staging */}
              <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end', alignItems: 'center' }}>
                <span style={{ fontSize: 12, color: '#64748b' }}>
                  Safety Check: Properties are staged as <b>Unverified</b> &amp; <b>Off-Market</b>.
                </span>
                <button
                  className="btn btn-sm"
                  disabled={importState.stageLoading || importState.preview.valid_records === 0}
                  onClick={handleExecuteImportStaging}
                  style={{ background: '#10b981', color: '#fff', fontWeight: 600 }}
                >
                  {importState.stageLoading ? 'Staging…' : `Stage ${importState.preview.valid_records} Valid Records`}
                </button>
              </div>
            </div>
          )}

          {/* Batch Staging Result */}
          {importState.batchResult && (
            <div style={{ marginTop: 20, padding: 16, background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8 }}>
              <h4 style={{ margin: '0 0 8px', color: '#15803d' }}>
                ✓ Staging Succeeded: Batch #{importState.batchResult.batch_id}
              </h4>
              <p style={{ margin: 0, fontSize: 13, color: '#166534' }}>
                Imported {importState.batchResult.imported_records} listings. They are safely quarantined in staging.
                Admins may now review, approve, and selectively publish them from the Inventory Workspace.
              </p>
            </div>
          )}
        </div>
      )}

      {/* VIEW: MAIN INVENTORY WORKSPACE */}
      {activeTab === 'inventory' && (
        <>
          {/* Lifecycle Filter Tabs */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 14, overflowX: 'auto', paddingBottom: 4 }}>
            {[
              ['all', 'All CRM Listings'],
              ['published', 'Published & Live'],
              ['pending', 'Pending Review'],
              ['unverified', 'Unverified Staged'],
              ['rejected', 'Rejected'],
              ['off_market', 'Off-Market'],
            ].map(([tabKey, label]) => (
              <button
                key={tabKey}
                onClick={() => setLifecycleTab(tabKey)}
                style={{
                  padding: '6px 14px',
                  borderRadius: 20,
                  fontSize: 13,
                  fontWeight: 600,
                  border: '1px solid',
                  cursor: 'pointer',
                  background: lifecycleTab === tabKey ? '#5a1645' : '#fff',
                  color: lifecycleTab === tabKey ? '#e8bd68' : '#64748b',
                  borderColor: lifecycleTab === tabKey ? '#5a1645' : '#cbd5e1',
                  transition: 'all 0.15s ease',
                }}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Search & Filter Toolbar */}
          <div className="ax-toolbar" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 16 }}>
            <input
              className="ax-input ax-input--search"
              placeholder="Search title, location, ref or description…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              style={{ minWidth: 220 }}
            />
            <select className="ax-input" value={purpose} onChange={(e) => setPurpose(e.target.value)}>
              <option value="">All purposes</option>
              {PURPOSES.map(([k, lbl]) => (
                <option key={k} value={k}>
                  {lbl}
                </option>
              ))}
            </select>
            <select
              className="ax-input"
              value={propertyType}
              onChange={(e) => setPropertyType(e.target.value)}
            >
              <option value="">All property types</option>
              {PROPERTY_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <input
              className="ax-input"
              placeholder="Location…"
              style={{ width: 140 }}
              value={location}
              onChange={(e) => setLocation(e.target.value)}
            />
            <select
              className="ax-input"
              value={minBedrooms}
              onChange={(e) => setMinBedrooms(e.target.value)}
            >
              <option value="">Any beds</option>
              <option value="0">Studio (0+)</option>
              <option value="1">1+ Bed</option>
              <option value="2">2+ Beds</option>
              <option value="3">3+ Beds</option>
              <option value="4">4+ Beds</option>
            </select>
            <input
              className="ax-input"
              type="number"
              min="0"
              placeholder="Min AED…"
              style={{ width: 110 }}
              value={minPrice}
              onChange={(e) => setMinPrice(e.target.value)}
            />
            <input
              className="ax-input"
              type="number"
              min="0"
              placeholder="Max AED…"
              style={{ width: 110 }}
              value={maxPrice}
              onChange={(e) => setMaxPrice(e.target.value)}
            />
            <select className="ax-input" value={sort} onChange={(e) => setSort(e.target.value)}>
              <option value="newest">Newest first</option>
              <option value="updated_desc">Recently updated</option>
              <option value="price_asc">Price: Low → High</option>
              <option value="price_desc">Price: High → Low</option>
              <option value="oldest">Oldest first</option>
            </select>
            {canManage && (
              <select
                className="ax-input"
                value={sourceFilter}
                onChange={(e) => setSourceFilter(e.target.value)}
              >
                <option value="crm">CRM Listings</option>
                <option value="all">All Sources (Incl. UAE Dataset)</option>
                <option value="manual">Manual CRM Only</option>
                <option value="uae_dataset">UAE Dataset Staged</option>
                <option value="demo_seed">Demo Seed Only</option>
              </select>
            )}
            <button className="btn btn-sm btn-ghost" onClick={resetFilters}>
              Reset
            </button>
            <span className="ax-count">
              {total.toLocaleString()} listing{total === 1 ? '' : 's'}
            </span>
          </div>

          {/* Floating Bulk Actions Bar (when items selected) */}
          {selectedIds.length > 0 && canManage && (
            <div
              style={{
                marginBottom: 16,
                padding: '12px 18px',
                background: '#5a1645',
                color: '#fff',
                borderRadius: 8,
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                boxShadow: '0 4px 12px rgba(90, 22, 69, 0.25)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ fontWeight: 700, color: '#e8bd68' }}>
                  {selectedIds.length} listing{selectedIds.length === 1 ? '' : 's'} selected
                </span>
                <button
                  className="btn btn-xs btn-ghost"
                  onClick={() => setSelectedIds([])}
                  style={{ color: '#fff' }}
                >
                  Clear Selection
                </button>
              </div>

              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  className="btn btn-sm"
                  disabled={bulkLoading}
                  onClick={() => handleBulkAction('approve')}
                  style={{ background: '#10b981', color: '#fff', fontWeight: 600 }}
                >
                  Approve Selected
                </button>
                <button
                  className="btn btn-sm"
                  disabled={bulkLoading}
                  onClick={() => handleBulkAction('publish')}
                  style={{ background: '#3b82f6', color: '#fff', fontWeight: 600 }}
                >
                  Publish Selected
                </button>
                <button
                  className="btn btn-sm btn-ghost"
                  disabled={bulkLoading}
                  onClick={() => handleBulkAction('unpublish')}
                  style={{ color: '#f8fafc', border: '1px solid rgba(255,255,255,0.3)' }}
                >
                  Unpublish Selected
                </button>
                <button
                  className="btn btn-sm btn-ghost"
                  disabled={bulkLoading}
                  onClick={() => handleBulkAction('archive')}
                  style={{ color: '#fca5a5', border: '1px solid rgba(252,165,165,0.4)' }}
                >
                  Archive Selected
                </button>
              </div>
            </div>
          )}

          {/* Inventory Table (Streamlined: Checkboxes removed for regular sales agents) */}
          <div className={`ax-table ${canManage ? 'ax-table--prop' : 'ax-table--prop-agent'}`}>
            <div className="ax-table__head">
              {canManage && (
                <span>
                  <input
                    type="checkbox"
                    checked={rows.length > 0 && selectedIds.length === rows.length}
                    onChange={handleSelectAll}
                    aria-label="Select all on this page"
                  />
                </span>
              )}
              <span>Property</span>
              <span>Location &amp; Type</span>
              <span>Specs</span>
              <span>Price</span>
              <span>Purpose</span>
              <span>Verification</span>
              <span>Publication</span>
              <span style={{ textAlign: 'right' }}>Actions</span>
            </div>

            {loading && rows.length === 0 && (
              <div className="ax-empty sm">
                <div className="ax-spin" /> Loading property inventory…
              </div>
            )}
            {!loading && rows.length === 0 && (
              <div className="ax-empty sm">No properties match the selected filters.</div>
            )}

            {rows.map((p) => {
              const isSelected = selectedIds.includes(p.id)
              const vStatus = p.verification_status || (p.is_approved ? 'verified' : 'unverified')
              const isPub = Boolean(p.is_published)

              return (
                <div
                  key={p.id}
                  className={`ax-table__row ${isSelected ? 'ax-table__row--selected' : ''}`}
                  style={{
                    background: isSelected ? 'rgba(90, 22, 69, 0.05)' : undefined,
                    borderLeft: isSelected ? '3px solid #5a1645' : '3px solid transparent',
                  }}
                  onClick={() => openDetail(p)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === 'Enter' && openDetail(p)}
                >
                  {/* Row Checkbox (Visible only to Admin / Governance roles) */}
                  {canManage && (
                    <span onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => handleToggleSelectRow(p.id)}
                        aria-label={`Select property #${p.id}`}
                      />
                    </span>
                  )}

                  {/* Property Details */}
                  <span className="ax-cell-strong">
                    <i className="ax-id">#{p.id}</i> {p.title}
                    <div className="ax-cell-sub" style={{ marginTop: 3 }}>
                      {p.external_ref && <span style={{ marginRight: 8 }}>Ref: {p.external_ref}</span>}
                      {p.is_demo && (
                        <span
                          style={{
                            fontSize: 10,
                            padding: '1px 6px',
                            borderRadius: 4,
                            background: 'rgba(245,158,11,0.18)',
                            color: '#fbbf24',
                            marginRight: 6,
                          }}
                        >
                          DEMO
                        </span>
                      )}
                      <span style={{ opacity: 0.7 }}>src: {p.source}</span>
                    </div>
                  </span>

                  {/* Location & Type */}
                  <span className="ax-cell-sub">
                    <strong>{p.location}</strong>
                    <br />
                    {p.property_type}
                  </span>

                  {/* Specs */}
                  <span className="ax-cell-sub">
                    {p.bedrooms === 0 ? 'Studio' : `${p.bedrooms} Bed`} · {p.bathrooms} Bath
                    <br />
                    {p.area ? `${Number(p.area).toLocaleString()} ${p.area_unit || 'sqft'}` : '—'}
                  </span>

                  {/* Price */}
                  <span className="ax-cell-strong">{fmtPrice(p.price, p.currency, p.purpose)}</span>

                  {/* Purpose */}
                  <span style={{ textTransform: 'capitalize' }}>{p.purpose}</span>

                  {/* Verification Status Badge */}
                  <span>
                    {vStatus === 'verified' && (
                      <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, background: '#dcfce7', color: '#166534', fontWeight: 600 }}>
                        ✓ Verified
                      </span>
                    )}
                    {vStatus === 'pending_review' && (
                      <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, background: '#fef3c7', color: '#92400e', fontWeight: 600 }}>
                        ⏳ Review
                      </span>
                    )}
                    {vStatus === 'unverified' && (
                      <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, background: '#f1f5f9', color: '#475569', fontWeight: 600 }}>
                        Unverified
                      </span>
                    )}
                    {vStatus === 'rejected' && (
                      <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, background: '#fee2e2', color: '#991b1b', fontWeight: 600 }} title={p.rejection_reason || 'Rejected'}>
                        ✕ Rejected
                      </span>
                    )}
                  </span>

                  {/* Publication State */}
                  <span>
                    {isPub ? (
                      <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, background: 'rgba(34,197,94,0.16)', color: '#16a34a', fontWeight: 600 }}>
                        Live
                      </span>
                    ) : (
                      <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, background: 'rgba(148,163,184,0.16)', color: '#64748b', fontWeight: 600 }}>
                        Hidden
                      </span>
                    )}
                  </span>

                  {/* Row Actions (Streamlined: Sleek horizontal controls, no vertical stacking) */}
                  <span
                    onClick={(e) => e.stopPropagation()}
                    style={{
                      display: 'flex',
                      gap: 6,
                      alignItems: 'center',
                      justifyContent: 'flex-end',
                      flexWrap: 'nowrap',
                      width: '100%',
                    }}
                  >
                    <button
                      type="button"
                      className="btn btn-xs btn-ghost"
                      onClick={() => openDetail(p)}
                      title="View complete property details"
                      style={{
                        padding: '4px 10px',
                        fontSize: 11.5,
                        whiteSpace: 'nowrap',
                        color: '#5a1645',
                        borderColor: '#e2d5de',
                        fontWeight: 600,
                        background: '#fff',
                      }}
                    >
                      View
                    </button>

                    {/* Sales Agent Share Action */}
                    {!canManage && (
                      <button
                        type="button"
                        className="btn btn-xs btn-ghost"
                        onClick={() => handleShareProperty(p)}
                        title="Copy recommendation link & summary to clipboard"
                        style={{
                          padding: '4px 10px',
                          fontSize: 11.5,
                          whiteSpace: 'nowrap',
                          color: '#5a1645',
                          borderColor: '#ebdbe4',
                          background: '#fcf8fa',
                          fontWeight: 500,
                        }}
                      >
                        Share
                      </button>
                    )}

                    {/* Admin Management Controls */}
                    {canManage && (
                      <>
                        <button
                          type="button"
                          className="btn btn-xs btn-ghost"
                          onClick={() => openEditModal(p)}
                          title="Edit property specifications"
                          style={{
                            padding: '4px 8px',
                            fontSize: 11.5,
                            whiteSpace: 'nowrap',
                            color: '#475569',
                            borderColor: '#cbd5e1',
                          }}
                        >
                          Edit
                        </button>

                        <button
                          type="button"
                          className="btn btn-xs btn-ghost"
                          onClick={() => openImagesModal(p)}
                          title="Upload & manage PostgreSQL persistent images"
                          style={{
                            padding: '4px 8px',
                            fontSize: 11.5,
                            whiteSpace: 'nowrap',
                            color: '#5a1645',
                            borderColor: '#ebdbe4',
                            background: '#fcf8fa',
                            fontWeight: 600,
                          }}
                        >
                          📷 Media
                        </button>

                        {vStatus !== 'verified' ? (
                          <>
                            <button
                              type="button"
                              className="btn btn-xs"
                              onClick={() => handleApprove(p)}
                              title="Verify and approve listing"
                              style={{
                                padding: '4px 8px',
                                fontSize: 11.5,
                                background: '#10b981',
                                color: '#ffffff',
                                fontWeight: 600,
                                border: 'none',
                                whiteSpace: 'nowrap',
                              }}
                            >
                              ✓ Approve
                            </button>
                            {vStatus !== 'rejected' && (
                              <button
                                type="button"
                                className="btn btn-xs btn-ghost"
                                onClick={() => handleRejectPrompt(p)}
                                title="Reject listing with feedback"
                                style={{
                                  padding: '4px 8px',
                                  fontSize: 11.5,
                                  color: '#dc2626',
                                  borderColor: '#fca5a5',
                                  whiteSpace: 'nowrap',
                                }}
                              >
                                ✕
                              </button>
                            )}
                          </>
                        ) : (
                          <button
                            type="button"
                            className="btn btn-xs btn-ghost"
                            onClick={() => handleTogglePublish(p)}
                            title={isPub ? 'Hide from public catalogue' : 'Publish to public catalogue'}
                            style={{
                              padding: '4px 8px',
                              fontSize: 11.5,
                              color: isPub ? '#64748b' : '#059669',
                              borderColor: isPub ? '#cbd5e1' : '#a7f3d0',
                              background: isPub ? 'transparent' : '#f0fdf4',
                              whiteSpace: 'nowrap',
                              fontWeight: 600,
                            }}
                          >
                            {isPub ? 'Unpublish' : 'Publish'}
                          </button>
                        )}
                      </>
                    )}
                  </span>
                </div>
              )
            })}
          </div>

          {/* Pagination */}
          {total > PAGE_SIZE && (
            <div
              style={{
                marginTop: 16,
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <span className="ax-muted">
                Showing {offset + 1}–{Math.min(offset + rows.length, total)} of {total.toLocaleString()}
              </span>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  className="btn btn-sm btn-ghost"
                  disabled={offset === 0 || loading}
                  onClick={() => goPage(offset - PAGE_SIZE)}
                >
                  ← Previous
                </button>
                <button
                  className="btn btn-sm btn-ghost"
                  disabled={offset + PAGE_SIZE >= total || loading}
                  onClick={() => goPage(offset + PAGE_SIZE)}
                >
                  Next →
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* REJECTION REASON DIALOG */}
      {rejectDialog.open && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(20, 8, 16, 0.65)',
            backdropFilter: 'blur(5px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 10002,
          }}
          onClick={() => setRejectDialog({ open: false, property: null, reason: '' })}
        >
          <div
            style={{ background: '#fff', padding: 24, borderRadius: 12, width: 460, maxWidth: '90%', boxShadow: '0 20px 40px rgba(0,0,0,0.3)', border: '1px solid #fca5a5' }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ margin: '0 0 10px', color: '#991b1b', fontSize: 18 }}>Reject Property Listing</h3>
            <p style={{ margin: '0 0 14px', fontSize: 13, color: '#64748b', lineHeight: 1.5 }}>
              State the reason for rejecting <b>#{rejectDialog.property?.id} {rejectDialog.property?.title}</b>.
              The agent will be prompted to correct these items.
            </p>
            <textarea
              className="ax-input"
              rows={4}
              style={{ width: '100%', marginBottom: 14 }}
              placeholder="e.g. Price exceeds current market range; missing high-res images of the master bedroom."
              value={rejectDialog.reason}
              onChange={(e) => setRejectDialog((prev) => ({ ...prev, reason: e.target.value }))}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                onClick={() => setRejectDialog({ open: false, property: null, reason: '' })}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-sm"
                disabled={!rejectDialog.reason.trim()}
                onClick={handleRejectConfirm}
                style={{ background: '#ef4444', color: '#fff', fontWeight: 600 }}
              >
                Confirm Rejection
              </button>
            </div>
          </div>
        </div>
      )}

      {/* POSTGRESQL PERSISTENT IMAGE STORAGE & GALLERY MODAL */}
      {imagesModal.open && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(20, 8, 16, 0.65)',
            backdropFilter: 'blur(6px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 10002,
            padding: 20,
          }}
          onClick={() => setImagesModal((prev) => ({ ...prev, open: false, selectedFiles: [], error: null }))}
        >
          <div
            style={{
              background: '#ffffff',
              padding: '24px 28px',
              borderRadius: 16,
              width: 780,
              maxWidth: '95%',
              maxHeight: '90vh',
              overflowY: 'auto',
              boxShadow: '0 24px 48px -12px rgba(90, 22, 69, 0.35)',
              border: '1px solid #e8bd68',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16, borderBottom: '1px solid #ebdbe4', paddingBottom: 14 }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 999, background: '#fcf8fa', color: '#5a1645', border: '1px solid #ebdbe4' }}>
                    POSTGRESQL BYTEA STORAGE
                  </span>
                  <span style={{ fontSize: 13, color: '#64748b', fontWeight: 500 }}>
                    Listing #{imagesModal.property?.id}
                  </span>
                </div>
                <h3 style={{ margin: '6px 0 0', color: '#5a1645', fontSize: 20, fontWeight: 700 }}>
                  Property Images &amp; Media Gallery
                </h3>
                <p style={{ margin: '4px 0 0', fontSize: 13, color: '#64748b' }}>
                  Upload JPEG, PNG, or WebP photos (up to 10MB) from your local computer directly into persistent PostgreSQL storage.
                </p>
              </div>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                onClick={() => setImagesModal((prev) => ({ ...prev, open: false, selectedFiles: [], error: null }))}
                style={{ fontSize: 18, padding: '4px 10px', lineHeight: 1 }}
                aria-label="Close dialog"
              >
                ✕
              </button>
            </div>

            {/* Sub-tab navigation */}
            <div style={{ display: 'flex', gap: 6, marginBottom: 18, background: '#f8f4f7', padding: 4, borderRadius: 8 }}>
              <button
                type="button"
                className={`btn btn-xs ${imagesModal.activeSubTab === 'upload' ? '' : 'btn-ghost'}`}
                onClick={() => setImagesModal((prev) => ({ ...prev, activeSubTab: 'upload' }))}
                style={{
                  background: imagesModal.activeSubTab === 'upload' ? '#5a1645' : 'transparent',
                  color: imagesModal.activeSubTab === 'upload' ? '#ffffff' : '#64748b',
                  fontWeight: 600,
                  border: 'none',
                  padding: '6px 14px',
                }}
              >
                📁 Local Upload &amp; PostgreSQL Gallery ({imagesModal.storedImages.length})
              </button>
              <button
                type="button"
                className={`btn btn-xs ${imagesModal.activeSubTab === 'urls' ? '' : 'btn-ghost'}`}
                onClick={() => setImagesModal((prev) => ({ ...prev, activeSubTab: 'urls' }))}
                style={{
                  background: imagesModal.activeSubTab === 'urls' ? '#5a1645' : 'transparent',
                  color: imagesModal.activeSubTab === 'urls' ? '#ffffff' : '#64748b',
                  fontWeight: 600,
                  border: 'none',
                  padding: '6px 14px',
                }}
              >
                🔗 Legacy External URLs
              </button>
            </div>

            {imagesModal.error && (
              <div style={{ marginBottom: 14, padding: '10px 14px', background: '#fef2f2', color: '#991b1b', borderRadius: 8, borderLeft: '4px solid #ef4444', fontSize: 13 }}>
                ⚠ {imagesModal.error}
              </div>
            )}

            {/* TAB 1: PostgreSQL Binary Upload & Gallery */}
            {imagesModal.activeSubTab === 'upload' && (
              <div>
                {/* Upload Box */}
                <div
                  style={{
                    border: '2px dashed #d4c0ce',
                    borderRadius: 12,
                    padding: '20px 24px',
                    textAlign: 'center',
                    background: '#fcf8fa',
                    marginBottom: 20,
                  }}
                >
                  <input
                    type="file"
                    id="local-property-images-file-input"
                    multiple
                    accept="image/jpeg,image/png,image/webp"
                    style={{ display: 'none' }}
                    onChange={handleFileSelect}
                  />
                  <label
                    htmlFor="local-property-images-file-input"
                    style={{ cursor: 'pointer', display: 'inline-block' }}
                  >
                    <div style={{ fontSize: 32, marginBottom: 6 }}>📸</div>
                    <div style={{ fontSize: 15, fontWeight: 700, color: '#5a1645' }}>
                      Click to Browse Images from Local Computer
                    </div>
                    <div style={{ fontSize: 12.5, color: '#64748b', marginTop: 4 }}>
                      Supported formats: <b>JPEG (.jpg, .jpeg)</b>, <b>PNG (.png)</b>, <b>WebP (.webp)</b> · Max 10MB per image
                    </div>
                  </label>

                  {/* Selected files preview */}
                  {imagesModal.selectedFiles.length > 0 && (
                    <div style={{ marginTop: 16, textAlign: 'left', background: '#ffffff', padding: 14, borderRadius: 8, border: '1px solid #ebdbe4' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                        <span style={{ fontSize: 13, fontWeight: 700, color: '#5a1645' }}>
                          Selected {imagesModal.selectedFiles.length} file(s) to upload:
                        </span>
                        <button
                          type="button"
                          className="btn btn-xs btn-ghost"
                          onClick={() => setImagesModal((prev) => ({ ...prev, selectedFiles: [] }))}
                          style={{ color: '#dc2626' }}
                        >
                          Clear
                        </button>
                      </div>
                      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', maxHeight: 120, overflowY: 'auto' }}>
                        {imagesModal.selectedFiles.map((f, i) => (
                          <div
                            key={i}
                            style={{
                              padding: '4px 10px',
                              background: '#f8fafc',
                              border: '1px solid #e2e8f0',
                              borderRadius: 6,
                              fontSize: 12,
                              color: '#334155',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 6,
                            }}
                          >
                            <span>📄 {f.name}</span>
                            <span style={{ opacity: 0.6 }}>({Math.round(f.size / 1024)} KB)</span>
                          </div>
                        ))}
                      </div>

                      <div style={{ marginTop: 14, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#475569', cursor: 'pointer' }}>
                          <input
                            type="checkbox"
                            checked={imagesModal.setPrimaryOnUpload}
                            onChange={(e) => setImagesModal((prev) => ({ ...prev, setPrimaryOnUpload: e.target.checked }))}
                          />
                          Set first uploaded image as primary thumbnail
                        </label>
                        <button
                          type="button"
                          className="btn btn-sm"
                          disabled={imagesModal.uploading}
                          onClick={handleUploadLocalFiles}
                          style={{
                            background: '#5a1645',
                            color: '#e8bd68',
                            border: '1px solid #e8bd68',
                            fontWeight: 700,
                            padding: '8px 18px',
                          }}
                        >
                          {imagesModal.uploading ? 'Uploading to PostgreSQL…' : `Upload ${imagesModal.selectedFiles.length} Image(s)`}
                        </button>
                      </div>

                      {imagesModal.uploadProgress && (
                        <div style={{ marginTop: 8, fontSize: 12, color: '#5a1645', fontStyle: 'italic' }}>
                          ⏳ {imagesModal.uploadProgress}
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Stored PostgreSQL Gallery Section */}
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                    <h4 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: '#5a1645' }}>
                      Stored PostgreSQL Images ({imagesModal.storedImages.length})
                    </h4>
                    <span style={{ fontSize: 12, color: '#64748b' }}>
                      Binary data saved in database · Auto-served via HTTP caching
                    </span>
                  </div>

                  {imagesModal.loadingStored ? (
                    <div style={{ padding: 24, textAlign: 'center', color: '#64748b', fontSize: 13 }}>
                      Loading database images…
                    </div>
                  ) : imagesModal.storedImages.length === 0 ? (
                    <div style={{ padding: 28, textAlign: 'center', background: '#f8fafc', borderRadius: 8, border: '1px solid #e2e8f0', color: '#64748b', fontSize: 13 }}>
                      No persistent images stored in PostgreSQL for this property yet.
                      <br />
                      Select files above to upload images from your local computer.
                    </div>
                  ) : (
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(210px, 1fr))', gap: 14 }}>
                      {imagesModal.storedImages.map((img) => {
                        const imgUrl = `/api/properties/${imagesModal.property.id}/images/${img.id}`
                        return (
                          <div
                            key={img.id}
                            style={{
                              background: '#ffffff',
                              border: img.is_primary ? '2px solid #e8bd68' : '1px solid #e2e8f0',
                              borderRadius: 10,
                              overflow: 'hidden',
                              boxShadow: img.is_primary ? '0 4px 12px rgba(232, 189, 104, 0.25)' : '0 1px 3px rgba(0,0,0,0.05)',
                              display: 'flex',
                              flexDirection: 'column',
                            }}
                          >
                            <div style={{ position: 'relative', height: 130, background: '#f1f5f9' }}>
                              <img
                                src={imgUrl}
                                alt={img.alt_text || img.original_filename || 'Property photo'}
                                style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                                onError={(e) => {
                                  e.currentTarget.style.display = 'none'
                                }}
                              />
                              {img.is_primary && (
                                <span
                                  style={{
                                    position: 'absolute',
                                    top: 8,
                                    left: 8,
                                    background: '#e8bd68',
                                    color: '#5a1645',
                                    fontWeight: 700,
                                    fontSize: 10.5,
                                    padding: '3px 8px',
                                    borderRadius: 6,
                                    boxShadow: '0 2px 6px rgba(0,0,0,0.2)',
                                  }}
                                >
                                  ⭐ PRIMARY
                                </span>
                              )}
                            </div>

                            <div style={{ padding: '10px 12px', flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'space-between', gap: 8 }}>
                              <div>
                                <div style={{ fontSize: 12, fontWeight: 600, color: '#1e293b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={img.original_filename}>
                                  {img.original_filename || `Image #${img.id}`}
                                </div>
                                <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>
                                  {img.mime_type} · {Math.round((img.file_size || 0) / 1024)} KB
                                </div>
                              </div>

                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6, borderTop: '1px solid #f1f5f9', paddingTop: 8 }}>
                                {!img.is_primary ? (
                                  <button
                                    type="button"
                                    className="btn btn-xs btn-ghost"
                                    onClick={() => handleSetPrimaryImage(img.id)}
                                    style={{ fontSize: 11, padding: '3px 8px', color: '#5a1645', borderColor: '#ebdbe4' }}
                                    title="Make this the primary thumbnail"
                                  >
                                    Set Primary
                                  </button>
                                ) : (
                                  <span style={{ fontSize: 11, color: '#d97706', fontWeight: 600 }}>Active Primary</span>
                                )}

                                <button
                                  type="button"
                                  className="btn btn-xs btn-ghost"
                                  onClick={() => handleDeleteImage(img.id)}
                                  style={{ fontSize: 11, padding: '3px 8px', color: '#dc2626', borderColor: '#fecaca' }}
                                  title="Delete from PostgreSQL"
                                >
                                  🗑 Delete
                                </button>
                              </div>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* TAB 2: External URLs (Legacy) */}
            {imagesModal.activeSubTab === 'urls' && (
              <div>
                <p style={{ margin: '0 0 14px', fontSize: 13, color: '#64748b' }}>
                  Optionally paste external image URLs (one per line). PostgreSQL binary storage is recommended over external URLs for reliability.
                </p>

                <label style={{ display: 'block', marginBottom: 12 }}>
                  <span className="ax-muted" style={{ fontSize: 12 }}>Primary Image URL (Optional override)</span>
                  <input
                    className="ax-input"
                    style={{ width: '100%', marginTop: 4 }}
                    placeholder="https://..."
                    value={imagesModal.primary}
                    onChange={(e) => setImagesModal((prev) => ({ ...prev, primary: e.target.value }))}
                  />
                </label>

                <label style={{ display: 'block', marginBottom: 16 }}>
                  <span className="ax-muted" style={{ fontSize: 12 }}>Gallery Image URLs (One per line)</span>
                  <textarea
                    className="ax-input"
                    rows={6}
                    style={{ width: '100%', marginTop: 4, fontFamily: 'monospace', fontSize: 12 }}
                    placeholder="https://images.unsplash.com/...&#10;https://images.unsplash.com/..."
                    value={imagesModal.imagesText}
                    onChange={(e) => setImagesModal((prev) => ({ ...prev, imagesText: e.target.value }))}
                  />
                </label>

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost"
                    onClick={() => setImagesModal((prev) => ({ ...prev, open: false }))}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={handleSaveImages}
                    style={{ background: '#5a1645', color: '#e8bd68', fontWeight: 600 }}
                  >
                    Save URL Gallery
                  </button>
                </div>
              </div>
            )}

            {/* Footer */}
            <div style={{ marginTop: 20, paddingTop: 14, borderTop: '1px solid #ebdbe4', display: 'flex', justifyContent: 'flex-end' }}>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                onClick={() => setImagesModal((prev) => ({ ...prev, open: false, selectedFiles: [], error: null }))}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* PROPERTY DETAIL SLIDE-OVER DRAWER */}
      {selected && !modalMode && activeTab === 'inventory' && (
        <div
          className="prop-drawer-overlay"
          onClick={closeDetail}
          role="dialog"
          aria-modal="true"
        >
          <div
            className="prop-drawer"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Drawer Header */}
            <div
              style={{
                padding: '20px 24px',
                borderBottom: '1px solid #ebdbe4',
                background: '#ffffff',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'flex-start',
                gap: 12,
              }}
            >
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#5a1645', letterSpacing: '0.05em' }}>
                    PROPERTY #{selected.id}
                  </span>
                  {selected.verification_status === 'verified' && (
                    <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, background: '#dcfce7', color: '#166534', fontWeight: 600 }}>
                      ✓ Verified
                    </span>
                  )}
                  {selected.is_published ? (
                    <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, background: '#e0f2fe', color: '#0369a1', fontWeight: 600 }}>
                      Live on Portal
                    </span>
                  ) : (
                    <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, background: '#f1f5f9', color: '#64748b', fontWeight: 600 }}>
                      Hidden / Staged
                    </span>
                  )}
                </div>
                <h3 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: '#5a1645', lineHeight: 1.3 }}>
                  {selected.title}
                </h3>
                <p style={{ margin: '4px 0 0', fontSize: 13, color: '#64748b' }}>
                  {selected.location} · {selected.property_type}
                </p>
              </div>

              <button
                type="button"
                className="btn btn-sm btn-ghost"
                onClick={closeDetail}
                style={{ fontSize: 18, padding: '4px 10px', lineHeight: 1, color: '#64748b' }}
                aria-label="Close drawer"
              >
                ✕
              </button>
            </div>

            {/* Quick Action Toolbar inside Drawer */}
            <div
              style={{
                padding: '12px 24px',
                background: '#fcf8fa',
                borderBottom: '1px solid #ebdbe4',
                display: 'flex',
                gap: 8,
                flexWrap: 'wrap',
                alignItems: 'center',
              }}
            >
              {canUpdate && (
                <button
                  type="button"
                  className="btn btn-xs"
                  onClick={() => openEditModal(selected)}
                  style={{ background: '#5a1645', color: '#e8bd68', fontWeight: 600 }}
                >
                  ✎ Edit Listing
                </button>
              )}
              {canUpdate && (
                <button
                  type="button"
                  className="btn btn-xs btn-ghost"
                  onClick={() => openImagesModal(selected)}
                  style={{ borderColor: '#cbd5e1', color: '#475569' }}
                >
                  🖼 Manage Media
                </button>
              )}
              {canUpdate && !selected.is_approved && (
                <button
                  type="button"
                  className="btn btn-xs"
                  onClick={() => handleApprove(selected)}
                  style={{ background: '#10b981', color: '#fff', fontWeight: 600 }}
                >
                  ✓ Approve
                </button>
              )}
              {canUpdate && selected.verification_status !== 'rejected' && (
                <button
                  type="button"
                  className="btn btn-xs btn-ghost"
                  onClick={() => handleRejectPrompt(selected)}
                  style={{ color: '#dc2626', borderColor: '#fca5a5' }}
                >
                  ✕ Reject
                </button>
              )}
              {canUpdate && selected.is_approved && (
                <button
                  type="button"
                  className="btn btn-xs btn-ghost"
                  onClick={() => (selected.is_published ? handleUnpublish(selected) : handlePublish(selected))}
                  style={{ color: selected.is_published ? '#64748b' : '#059669', borderColor: '#cbd5e1' }}
                >
                  {selected.is_published ? 'Unpublish' : 'Publish Live'}
                </button>
              )}
              {selected.is_published && selected.availability === 'available' && (
                <a
                  href={`/properties/${selected.id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn btn-xs btn-ghost"
                  style={{ marginLeft: 'auto', color: '#5a1645', borderColor: '#d4c0ce' }}
                >
                  Customer View ↗
                </a>
              )}
            </div>

            {/* Scrollable Drawer Body */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
              {/* Rejection Alert if present */}
              {selected.rejection_reason && (
                <div
                  style={{
                    marginBottom: 16,
                    padding: '12px 16px',
                    background: '#fef2f2',
                    borderLeft: '4px solid #ef4444',
                    borderRadius: 6,
                    color: '#991b1b',
                    fontSize: 13,
                  }}
                >
                  <b>Correction Required:</b> {selected.rejection_reason}
                </div>
              )}

              {/* Price Banner */}
              <div
                style={{
                  background: 'linear-gradient(135deg, #5a1645 0%, #3a0c26 100%)',
                  color: '#ffffff',
                  padding: '16px 20px',
                  borderRadius: 12,
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: 20,
                  boxShadow: '0 4px 14px rgba(90, 22, 69, 0.2)',
                }}
              >
                <div>
                  <span style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em', color: '#e8bd68', fontWeight: 700 }}>
                    Listing Price ({selected.currency || 'AED'})
                  </span>
                  <div style={{ fontSize: 24, fontWeight: 800, color: '#ffffff', marginTop: 2 }}>
                    {fmtPrice(selected.price, selected.currency, selected.purpose)}
                  </div>
                </div>
                <span
                  style={{
                    background: 'rgba(232, 189, 104, 0.2)',
                    color: '#e8bd68',
                    padding: '4px 12px',
                    borderRadius: 20,
                    fontSize: 12,
                    fontWeight: 700,
                    textTransform: 'uppercase',
                  }}
                >
                  {selected.purpose}
                </span>
              </div>

              {/* Media preview gallery */}
              {selected.images && (
                <div style={{ marginBottom: 20 }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Media Gallery
                  </span>
                  <div style={{ display: 'flex', gap: 10, marginTop: 8, overflowX: 'auto', paddingBottom: 6 }}>
                    {(Array.isArray(selected.images) ? selected.images : JSON.parse(selected.images || '[]')).map((img, idx) => {
                      const url = typeof img === 'string' ? img : img.url
                      const isPrimary = selected.primary_image === url || img.is_primary
                      return (
                        <div
                          key={idx}
                          style={{
                            position: 'relative',
                            width: 150,
                            height: 96,
                            flexShrink: 0,
                            borderRadius: 8,
                            overflow: 'hidden',
                            border: isPrimary ? '2px solid #e8bd68' : '1px solid #cbd5e1',
                          }}
                        >
                          <img
                            src={url}
                            alt={`Property image ${idx + 1}`}
                            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                            onError={(e) => { e.currentTarget.src = 'https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?w=800&auto=format&fit=crop&q=80' }}
                          />
                          {isPrimary && (
                            <span
                              style={{
                                position: 'absolute',
                                bottom: 4,
                                left: 4,
                                background: 'rgba(90, 22, 69, 0.85)',
                                color: '#e8bd68',
                                fontSize: 9,
                                padding: '1px 5px',
                                borderRadius: 3,
                                fontWeight: 700,
                              }}
                            >
                              PRIMARY
                            </span>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Key Specs Grid */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))',
                  gap: 12,
                  marginBottom: 20,
                  background: '#f8fafc',
                  padding: 16,
                  borderRadius: 10,
                  border: '1px solid #e2e8f0',
                }}
              >
                <div>
                  <span className="ax-muted" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    External Reference
                  </span>
                  <div style={{ fontWeight: 600, marginTop: 2 }}>{selected.external_ref || 'None'}</div>
                </div>
                <div>
                  <span className="ax-muted" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Listing Purpose
                  </span>
                  <div style={{ fontWeight: 600, textTransform: 'capitalize', marginTop: 2 }}>{selected.purpose}</div>
                </div>
                <div>
                  <span className="ax-muted" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Availability
                  </span>
                  <div style={{ fontWeight: 600, textTransform: 'capitalize', marginTop: 2 }}>{selected.availability}</div>
                </div>
                <div>
                  <span className="ax-muted" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Bedrooms &amp; Baths
                  </span>
                  <div style={{ fontWeight: 600, marginTop: 2 }}>
                    {selected.bedrooms === 0 ? 'Studio' : `${selected.bedrooms} Beds`} · {selected.bathrooms} Baths
                  </div>
                </div>
                <div>
                  <span className="ax-muted" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Built-up Area
                  </span>
                  <div style={{ fontWeight: 600, marginTop: 2 }}>
                    {selected.area ? `${Number(selected.area).toLocaleString()} ${selected.area_unit || 'sqft'}` : 'Not Specified'}
                  </div>
                </div>
                <div>
                  <span className="ax-muted" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Ingestion Source
                  </span>
                  <div style={{ fontWeight: 600, marginTop: 2 }}>{selected.source || 'Manual Entry'}</div>
                </div>
              </div>

              {/* Highlights & Amenities */}
              {selected.highlights && (
                <div style={{ marginBottom: 16 }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Highlights
                  </span>
                  <div style={{ marginTop: 4, fontSize: 14, fontWeight: 600, color: '#5a1645' }}>
                    {selected.highlights}
                  </div>
                </div>
              )}

              {selected.amenities && (
                <div style={{ marginBottom: 16 }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Amenities &amp; Features
                  </span>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
                    {(Array.isArray(selected.amenities)
                      ? selected.amenities
                      : typeof selected.amenities === 'string'
                        ? selected.amenities.split(',').map((s) => s.trim())
                        : []
                    ).map((amenity, idx) => (
                      <span
                        key={idx}
                        style={{
                          fontSize: 12,
                          background: '#f1f5f9',
                          color: '#334155',
                          padding: '4px 10px',
                          borderRadius: 6,
                          fontWeight: 500,
                        }}
                      >
                        ✓ {amenity}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Description */}
              {selected.description && (
                <div>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Listing Description
                  </span>
                  <p style={{ margin: '6px 0 0', fontSize: 14, lineHeight: 1.6, color: '#334155', whiteSpace: 'pre-wrap' }}>
                    {selected.description}
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* CREATE / EDIT PROPERTY MODAL (Centered Popup Dialog) */}
      {modalMode && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 10001,
            background: 'rgba(20, 8, 16, 0.65)',
            backdropFilter: 'blur(6px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 20,
          }}
          onClick={(e) => {
            if (e.target === e.currentTarget) setModalMode(null)
          }}
        >
          <div
            className="ax-card"
            style={{
              width: '100%',
              maxWidth: 840,
              maxHeight: '90vh',
              overflowY: 'auto',
              background: '#ffffff',
              borderRadius: 16,
              boxShadow: '0 24px 48px -12px rgba(0, 0, 0, 0.35)',
              border: '1px solid #e8bd68',
              padding: '24px 28px',
              position: 'relative',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18, borderBottom: '1px solid #f1f5f9', paddingBottom: 14 }}>
              <div>
                <h3 style={{ margin: 0, color: '#5a1645', fontSize: 20, fontWeight: 700 }}>
                  {modalMode === 'create' ? 'Create New Property Listing' : `Edit Property #${selected?.id}`}
                </h3>
                <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: 13 }}>
                  {modalMode === 'create'
                    ? 'Enter property specifications to register a new listing in the CRM.'
                    : `Modify details and publication settings for property #${selected?.id}.`}
                </p>
              </div>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                onClick={() => setModalMode(null)}
                style={{ fontSize: 18, padding: '4px 10px', lineHeight: 1 }}
                aria-label="Close modal"
              >
                ✕
              </button>
            </div>

          {formError && (
            <div style={{ marginBottom: 14, padding: '10px 14px', background: '#fef2f2', color: '#991b1b', borderRadius: 6, borderLeft: '4px solid #ef4444' }}>
              ⚠ {formError}
            </div>
          )}

          <form onSubmit={handleFormSubmit}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 14 }}>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span className="ax-muted" style={{ fontSize: 12 }}>Title *</span>
                <input
                  className="ax-input"
                  required
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  placeholder="e.g. Marina Gate 2BR Sea View Apartment"
                />
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span className="ax-muted" style={{ fontSize: 12 }}>External Reference</span>
                <input
                  className="ax-input"
                  value={form.external_ref}
                  onChange={(e) => setForm({ ...form, external_ref: e.target.value })}
                  placeholder="e.g. LYKA-DXB-101"
                />
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span className="ax-muted" style={{ fontSize: 12 }}>Location *</span>
                <input
                  className="ax-input"
                  required
                  value={form.location}
                  onChange={(e) => setForm({ ...form, location: e.target.value })}
                  placeholder="e.g. Dubai Marina, Dubai"
                />
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span className="ax-muted" style={{ fontSize: 12 }}>Property Type *</span>
                <input
                  className="ax-input"
                  required
                  list="lyka-property-types-list"
                  value={form.property_type}
                  onChange={(e) => setForm({ ...form, property_type: e.target.value })}
                />
                <datalist id="lyka-property-types-list">
                  {PROPERTY_TYPES.map((t) => (
                    <option key={t} value={t} />
                  ))}
                </datalist>
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span className="ax-muted" style={{ fontSize: 12 }}>Purpose *</span>
                <select
                  className="ax-input"
                  value={form.purpose}
                  onChange={(e) => setForm({ ...form, purpose: e.target.value })}
                >
                  {PURPOSES.map(([k, lbl]) => (
                    <option key={k} value={k}>
                      {lbl}
                    </option>
                  ))}
                </select>
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span className="ax-muted" style={{ fontSize: 12 }}>Availability *</span>
                <select
                  className="ax-input"
                  value={form.availability}
                  onChange={(e) => setForm({ ...form, availability: e.target.value })}
                >
                  {AVAILABILITIES.map(([k, lbl]) => (
                    <option key={k} value={k}>
                      {lbl}
                    </option>
                  ))}
                </select>
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span className="ax-muted" style={{ fontSize: 12 }}>Price (AED) *</span>
                <input
                  className="ax-input"
                  type="number"
                  min="1"
                  required
                  value={form.price}
                  onChange={(e) => setForm({ ...form, price: e.target.value })}
                  placeholder="e.g. 2450000"
                />
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span className="ax-muted" style={{ fontSize: 12 }}>Bedrooms (0 = Studio) *</span>
                <input
                  className="ax-input"
                  type="number"
                  min="0"
                  step="1"
                  required
                  value={form.bedrooms}
                  onChange={(e) => setForm({ ...form, bedrooms: e.target.value })}
                />
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span className="ax-muted" style={{ fontSize: 12 }}>Bathrooms *</span>
                <input
                  className="ax-input"
                  type="number"
                  min="1"
                  step="1"
                  required
                  value={form.bathrooms}
                  onChange={(e) => setForm({ ...form, bathrooms: e.target.value })}
                />
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span className="ax-muted" style={{ fontSize: 12 }}>Area (sqft)</span>
                <input
                  className="ax-input"
                  type="number"
                  min="0"
                  value={form.area}
                  onChange={(e) => setForm({ ...form, area: e.target.value })}
                  placeholder="e.g. 1350"
                />
              </label>
            </div>

            <div style={{ marginTop: 14, display: 'grid', gap: 12 }}>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span className="ax-muted" style={{ fontSize: 12 }}>Highlights / Subtitle</span>
                <input
                  className="ax-input"
                  value={form.highlights}
                  onChange={(e) => setForm({ ...form, highlights: e.target.value })}
                  placeholder="e.g. Full Marina View · High Floor · Vacant on Transfer"
                />
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span className="ax-muted" style={{ fontSize: 12 }}>Amenities (comma-separated)</span>
                <input
                  className="ax-input"
                  value={form.amenities_text}
                  onChange={(e) => setForm({ ...form, amenities_text: e.target.value })}
                  placeholder="e.g. Infinity Pool, Gym, Concierge, Covered Parking"
                />
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span className="ax-muted" style={{ fontSize: 12 }}>Image URLs (one per line)</span>
                <textarea
                  className="ax-input"
                  rows={3}
                  value={form.images_text}
                  onChange={(e) => setForm({ ...form, images_text: e.target.value })}
                  placeholder="https://images.unsplash.com/..."
                />
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span className="ax-muted" style={{ fontSize: 12 }}>Description</span>
                <textarea
                  className="ax-input"
                  rows={3}
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  placeholder="Detailed marketing description…"
                />
              </label>
            </div>

            <div style={{ marginTop: 16, display: 'flex', gap: 10 }}>
              <button
                type="submit"
                className="btn btn-sm"
                disabled={saving}
                style={{ background: '#5a1645', color: '#e8bd68', fontWeight: 600 }}
              >
                {saving ? 'Saving…' : modalMode === 'create' ? 'Create Listing' : 'Save Changes'}
              </button>
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => setModalMode(null)}>
                Cancel
              </button>
            </div>
          </form>
          </div>
        </div>
      )}
    </div>
  )
}
