// Thin API client for the Lyka Realty backend.
// All requests go through Vite's dev proxy (/api -> FastAPI :8000) in
// development and the Vercel /api rewrite in production — never a hardcoded
// host.
//
// Every request carries an AbortSignal timeout: the browser's fetch has no
// default timeout, and a hung backend must never leave a spinner running
// forever. Budgets stay under the backend's serverless cap (30s): AI turns
// get the largest window, plain reads a short one. A timeout surfaces as a
// normal Error ("Request timed out. Please try again.") with code 'timeout'.

const JSON_HEADERS = { 'Content-Type': 'application/json' }

const READ_TIMEOUT_MS = 15000
const AUTH_TIMEOUT_MS = 20000
const AI_TIMEOUT_MS = 32000 // chat/voice turn: serverless cap 30s + margin

function timeoutSignal(ms) {
  // AbortSignal.timeout: Chrome 103+, Safari 16+, Firefox 100+. Older
  // browsers simply run without the client-side guard.
  return typeof AbortSignal !== 'undefined' && AbortSignal.timeout
    ? AbortSignal.timeout(ms)
    : undefined
}

async function handle(res) {
  if (!res.ok) {
    let detail = res.statusText
    let raw = null
    try {
      const body = await res.json()
      raw = body.detail
      if (Array.isArray(body.detail)) {
        // FastAPI validation errors: [{loc, msg}, ...] → readable summary
        detail = body.detail
          .map((d) => `${(d.loc || []).slice(1).join('.') || 'body'}: ${d.msg}`)
          .join('; ')
      } else if (body.detail && typeof body.detail === 'object') {
        // structured errors (e.g. duplicate-lead conflict) keep their payload
        detail = body.detail.message || JSON.stringify(body.detail)
      } else {
        detail = body.detail || JSON.stringify(body)
      }
    } catch {
      /* keep statusText */
    }
    const err = new Error(detail)
    err.status = res.status
    err.detail = raw // structured detail (code, lead_id, ...) when present
    throw err
  }
  return res.json()
}

async function req(url, opts = {}, ms = READ_TIMEOUT_MS) {
  let res
  try {
    res = await fetch(url, { ...opts, signal: timeoutSignal(ms) })
  } catch (e) {
    if (e && (e.name === 'TimeoutError' || e.name === 'AbortError')) {
      const err = new Error('Request timed out. Please try again.')
      err.code = 'timeout'
      throw err
    }
    throw e
  }
  return handle(res)
}

export const api = {
  health: () => req('/api/health', {}, 10000),

  // Chat — propertyId is the listing the customer is viewing (context for LykAI).
  // propertySource tells the backend which id space propertyId refers to:
  //   'dataset' (default) | 'record' (DB-backed listing from the browse pages).
  // No language argument: the agent classifies each message itself and replies
  // in that same language (English / Tamil / Tanglish / mixed).
  chat: (message, conversationId = null, propertyId = null, propertySource = null, channel = 'text') =>
    req(
      '/api/chat',
      {
        method: 'POST',
        headers: JSON_HEADERS,
        credentials: 'same-origin',
        body: JSON.stringify({
          message,
          conversation_id: conversationId,
          channel,
          ...(propertyId ? { property_id: propertyId } : {}),
          ...(propertyId && propertySource ? { property_source: propertySource } : {}),
        }),
      },
      AI_TIMEOUT_MS,
    ),

  // Conversations
  listConversations: () => req('/api/conversations'),
  getConversation: (id) => req(`/api/conversations/${id}`),

  // ---- Customer accounts (optional — guests chat without signing in) ----
  customerMe: () => req('/api/customer/me', { credentials: 'same-origin' }),
  customerRegister: (email, password, name = '', confirmPassword = null) =>
    req(
      '/api/customer/register',
      {
        method: 'POST',
        headers: JSON_HEADERS,
        credentials: 'same-origin',
        body: JSON.stringify({
          email,
          password,
          name,
          // Confirm-password field from the signup form (validated again server-side)
          ...(confirmPassword ? { confirm_password: confirmPassword } : {}),
        }),
      },
      AUTH_TIMEOUT_MS,
    ),
  customerLogin: (email, password) =>
    req(
      '/api/customer/login',
      {
        method: 'POST',
        headers: JSON_HEADERS,
        credentials: 'same-origin',
        body: JSON.stringify({ email, password }),
      },
      AUTH_TIMEOUT_MS,
    ),
  customerLogout: () =>
    req('/api/customer/logout', { method: 'POST', credentials: 'same-origin' }),

  // Saved properties (signed-in customers). `source` picks the id space:
  // 'dataset' (default, legacy) or 'record' (DB-backed listing).
  savedProperties: () =>
    req('/api/customer/saved', { credentials: 'same-origin' }),
  saveProperty: (propertyId, source = 'dataset') =>
    req('/api/customer/saved', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify({ property_id: propertyId, source }),
    }),
  unsaveProperty: (propertyId, source = 'dataset') =>
    req(`/api/customer/saved/${propertyId}${source === 'record' ? '?source=record' : ''}`, {
      method: 'DELETE',
      credentials: 'same-origin',
    }),

  // Properties
  getProperty: (id) => req(`/api/properties/${id}`),

  // Phase 6 — DB-backed public listings (approved + available only).
  // These serve the `properties` table, not the UAE JSON dataset.
  listRecords: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    return req(`/api/properties${qs.toString() ? `?${qs}` : ''}`)
  },
  // Separate endpoint, separate id space: the UAE dataset browse grid
  // (dataset property_id 1..25082). Items come back with source="dataset"
  // and null purpose/price_period/availability — the dataset has none of
  // those columns, so the server states them instead of guessing.
  listDataset: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    return req(`/api/properties/dataset${qs.toString() ? `?${qs}` : ''}`)
  },
  getPropertyRecord: (id) => req(`/api/properties/record/${id}`),

  // ---- Agent authentication (internal CRM) ----
  login: (username, password) =>
    req(
      '/api/auth/login',
      {
        method: 'POST',
        headers: JSON_HEADERS,
        credentials: 'same-origin',
        body: JSON.stringify({ username, password }),
      },
      AUTH_TIMEOUT_MS,
    ),
  logout: () =>
    req('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }),
  me: () => req('/api/auth/me', { credentials: 'same-origin' }),

  // ---- Global portal (Phase 3) ----
  // One endpoint resolves staff OR customer identity + roles/permissions/landing.
  // Never throws for the anonymous case — returns {authenticated:false}.
  session: () =>
    req('/api/auth/session', { credentials: 'same-origin' }, 12000),
  portalLogin: (identifier, password) =>
    req(
      '/api/auth/portal-login',
      {
        method: 'POST',
        headers: JSON_HEADERS,
        credentials: 'same-origin',
        body: JSON.stringify({ identifier, password }),
      },
      AUTH_TIMEOUT_MS,
    ),

  // ---- Admin: provisioning, roles, audit (Phase 5/6) ----
  // Unwired client contract for the tested admin/audit API — the admin UI
  // consumes these when it is built (see docs/PRODUCTION_CLEANUP_AUDIT.md).
  adminUsers: () => req('/api/admin/users', { credentials: 'same-origin' }),
  adminRoles: () => req('/api/admin/roles', { credentials: 'same-origin' }),
  adminCreateUser: (data) =>
    req('/api/admin/users', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  adminChangeRole: (userId, role, currentPassword) =>
    req(`/api/admin/users/${userId}/role`, {
      method: 'PATCH',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify({ role, current_password: currentPassword }),
    }),
  adminGrantRole: (userId, roleKey, currentPassword) =>
    req(`/api/admin/users/${userId}/roles/${roleKey}`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      // step-up body is accepted by the route's own dependency contract
      body: JSON.stringify({ current_password: currentPassword }),
    }),
  adminRevokeRole: (userId, roleKey, currentPassword) =>
    req(`/api/admin/users/${userId}/roles/${roleKey}`, {
      method: 'DELETE',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify({ current_password: currentPassword }),
    }),
  adminSuspendUser: (userId, suspend, currentPassword) =>
    req(`/api/admin/users/${userId}/suspend`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify({ suspend, current_password: currentPassword }),
    }),
  adminAgents: () => req('/api/admin/agents', { credentials: 'same-origin' }),
  adminAgentDetail: (id) => req('/api/admin/agents/' + id, { credentials: 'same-origin' }),
  adminCreateAgent: (data) =>
    req('/api/admin/agents', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  adminResetAgentPassword: (id, data = {}) =>
    req('/api/admin/agents/' + id + '/reset-password', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  adminUpdateAgentStatus: (id, is_active) =>
    req('/api/admin/agents/' + id + '/status', {
      method: 'PATCH',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify({ is_active }),
    }),
  auditLog: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    const suffix = qs.toString()
    return req(`/api/audit/log${suffix ? `?${suffix}` : ''}`, { credentials: 'same-origin' })
  },

  // ---- Agent CRM (protected — validated server-side on every request) ----
  agentDashboard: () => req('/api/agent/dashboard', { credentials: 'same-origin' }),

  agentLeads: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    const suffix = qs.toString()
    return req(`/api/agent/leads${suffix ? `?${suffix}` : ''}`, { credentials: 'same-origin' })
  },
  agentLead: (id) => req(`/api/agent/leads/${id}`, { credentials: 'same-origin' }),
  updateAgentLead: (id, data) =>
    req(`/api/agent/leads/${id}`, {
      method: 'PATCH',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),

  // ---- Phase 5: lead CRM workflow (staff only; cookie session) ----
  // Review → edit → EXPLICIT confirmation → save. The server always
  // recomputes score/priority; client-supplied scores are ignored there.
  createAgentLead: (data) =>
    req('/api/agent/leads', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  // Optional prefill: OpenAI-structured extraction of an enquiry (Phase 3).
  extractEnquiry: (enquiry) =>
    req(
      '/api/agent/leads/extract',
      {
        method: 'POST',
        headers: JSON_HEADERS,
        credentials: 'same-origin',
        body: JSON.stringify({ enquiry }),
      },
      35000, // backend OpenAI budget is 30s + retry margin
    ),
  agentLeadFollowUps: (leadId) =>
    req(`/api/agent/leads/${leadId}/follow-ups`, { credentials: 'same-origin' }),
  createAgentFollowUp: (leadId, data) =>
    req(`/api/agent/leads/${leadId}/follow-ups`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  updateAgentFollowUp: (id, patch) =>
    req(`/api/agent/follow-ups/${id}`, {
      method: 'PATCH',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(patch),
    }),
  listAgentFollowUps: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    const suffix = qs.toString()
    return req(`/api/agent/follow-ups${suffix ? `?${suffix}` : ''}`, { credentials: 'same-origin' })
  },
  // Deterministic DB matching for a saved lead + deduplicated history save.
  runLeadRecommendations: (leadId, data = {}) =>
    req(`/api/agent/leads/${leadId}/recommendations`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),

  // ---- Phase E: Lifecycle, Assignment, Duplicate Merge & Property Linking ----
  agentSalesAgents: () =>
    req('/api/agent/sales-agents', { credentials: 'same-origin' }),
  transitionLeadStatus: (leadId, data) =>
    req(`/api/agent/leads/${leadId}/status`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  assignAgentLead: (leadId, data) =>
    req(`/api/agent/leads/${leadId}/assign`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  agentLeadDuplicates: (leadId) =>
    req(`/api/agent/leads/${leadId}/duplicates`, { credentials: 'same-origin' }),
  mergeAgentLead: (leadId, data) =>
    req(`/api/agent/leads/${leadId}/merge`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  linkLeadProperty: (leadId, data) =>
    req(`/api/agent/leads/${leadId}/properties`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  unlinkLeadProperty: (leadId, recId) =>
    req(`/api/agent/leads/${leadId}/properties/${recId}`, {
      method: 'DELETE',
      credentials: 'same-origin',
    }),
  agentLeadActivity: (leadId, params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    const suffix = qs.toString()
    return req(
      `/api/agent/leads/${leadId}/activity${suffix ? `?${suffix}` : ''}`,
      { credentials: 'same-origin' },
    )
  },
  cancelAgentFollowUp: (id, reason = null) =>
    req(`/api/agent/follow-ups/${id}/cancel`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(reason ? { reason } : {}),
    }),

  // ---- Phase F: Appointments, Viewings, Offers, Negotiations & Deals ----
  agentSalesOpsSummary: () =>
    req('/api/agent/sales-ops/summary', { credentials: 'same-origin' }),

  agentAppointments: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    const suffix = qs.toString()
    return req(`/api/agent/appointments${suffix ? `?${suffix}` : ''}`, { credentials: 'same-origin' })
  },
  agentAppointment: (id) =>
    req(`/api/agent/appointments/${id}`, { credentials: 'same-origin' }),
  createAgentAppointment: (data) =>
    req('/api/agent/appointments', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  createLeadAppointment: (leadId, data) =>
    req(`/api/agent/leads/${leadId}/appointments`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  updateAgentAppointment: (id, data) =>
    req(`/api/agent/appointments/${id}`, {
      method: 'PATCH',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  rescheduleAgentAppointment: (id, data) =>
    req(`/api/agent/appointments/${id}/reschedule`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  cancelAgentAppointment: (id, data) =>
    req(`/api/agent/appointments/${id}/cancel`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  recordAgentAppointmentOutcome: (id, data) =>
    req(`/api/agent/appointments/${id}/outcome`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),

  agentOffers: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    const suffix = qs.toString()
    return req(`/api/agent/offers${suffix ? `?${suffix}` : ''}`, { credentials: 'same-origin' })
  },
  agentOffer: (id) =>
    req(`/api/agent/offers/${id}`, { credentials: 'same-origin' }),
  createAgentOffer: (data) =>
    req('/api/agent/offers', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  createLeadOffer: (leadId, data) =>
    req(`/api/agent/leads/${leadId}/offers`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  counterAgentOffer: (id, data) =>
    req(`/api/agent/offers/${id}/counter`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  transitionAgentOfferStatus: (id, data) =>
    req(`/api/agent/offers/${id}/status`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),

  agentDeals: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    const suffix = qs.toString()
    return req(`/api/agent/deals${suffix ? `?${suffix}` : ''}`, { credentials: 'same-origin' })
  },
  agentDeal: (id) =>
    req(`/api/agent/deals/${id}`, { credentials: 'same-origin' }),
  createAgentDeal: (data) =>
    req('/api/agent/deals', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  createLeadDeal: (leadId, data) =>
    req(`/api/agent/leads/${leadId}/deals`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  updateAgentDeal: (id, data) =>
    req(`/api/agent/deals/${id}`, {
      method: 'PATCH',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  transitionAgentDealStage: (id, data) =>
    req(`/api/agent/deals/${id}/stage`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  addDealChecklistItem: (dealId, data) =>
    req(`/api/agent/deals/${dealId}/checklist`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  updateDealChecklistItem: (dealId, itemId, data) =>
    req(`/api/agent/deals/${dealId}/checklist/${itemId}`, {
      method: 'PATCH',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),

  agentConversations: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    const suffix = qs.toString()
    return req(`/api/agent/conversations${suffix ? `?${suffix}` : ''}`, { credentials: 'same-origin' })
  },
  agentConversation: (id) =>
    req(`/api/agent/conversations/${id}`, { credentials: 'same-origin' }),

  // ---- Staff & Admin Property Inventory Management (Phase D) ----
  agentProperties: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    const suffix = qs.toString()
    return req(`/api/agent/properties${suffix ? `?${suffix}` : ''}`, { credentials: 'same-origin' })
  },
  agentProperty: (id) =>
    req(`/api/agent/properties/${id}`, { credentials: 'same-origin' }),
  createAgentProperty: (data) =>
    req('/api/agent/properties', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  updateAgentProperty: (id, data) =>
    req(`/api/agent/properties/${id}`, {
      method: 'PATCH',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }),
  archiveAgentProperty: (id) =>
    req(`/api/agent/properties/${id}/archive`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
    }),
  deleteAgentProperty: (id) =>
    req(`/api/agent/properties/${id}`, {
      method: 'DELETE',
      credentials: 'same-origin',
    }),

  // Phase I: Property Lifecycle, Verification & Batch Import
  submitPropertyForReview: (id) =>
    req(`/api/agent/properties/${id}/submit-review`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
    }),
  approveProperty: (id) =>
    req(`/api/admin/properties/${id}/approve`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
    }),
  rejectProperty: (id, reason) =>
    req(`/api/admin/properties/${id}/reject`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify({ reason }),
    }),
  publishProperty: (id) =>
    req(`/api/admin/properties/${id}/publish`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
    }),
  unpublishProperty: (id) =>
    req(`/api/admin/properties/${id}/unpublish`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
    }),
  updatePropertyImages: (id, images, primaryImage) =>
    req(`/api/admin/properties/${id}/images`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify({ images, primary_image: primaryImage }),
    }),
  uploadPropertyImage: (id, file, { isPrimary = false, altText = '', displayOrder = null } = {}) => {
    const fd = new FormData()
    fd.append('file', file)
    if (isPrimary) fd.append('is_primary', 'true')
    if (altText) fd.append('alt_text', altText)
    if (displayOrder !== null) fd.append('display_order', String(displayOrder))
    return req(`/api/admin/properties/${id}/images/upload`, {
      method: 'POST',
      credentials: 'same-origin',
      body: fd,
    }, 60000)
  },
  getPropertyImages: (id) => req(`/api/properties/${id}/images`),
  setPropertyPrimaryImage: (propertyId, imageId) =>
    req(`/api/admin/properties/${propertyId}/images/${imageId}/primary`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
    }),
  deletePropertyImage: (propertyId, imageId) =>
    req(`/api/admin/properties/${propertyId}/images/${imageId}`, {
      method: 'DELETE',
      credentials: 'same-origin',
    }),
  bulkPropertyAction: (propertyIds, action, reason = null) =>
    req('/api/admin/properties/bulk-action', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify({ property_ids: propertyIds, action, reason }),
    }),
  previewPropertyImport: (records) =>
    req('/api/admin/properties/import-preview', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify({ records }),
    }),
  stagePropertyImport: (records, source = 'uae_dataset', filename = null, skipDuplicates = true, dryRun = false) =>
    req('/api/admin/properties/import-batch', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify({ records, source, filename, skip_duplicates: skipDuplicates, dry_run: dryRun }),
    }),
  listImportBatches: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    const suffix = qs.toString()
    return req(`/api/admin/properties/import-batches${suffix ? `?${suffix}` : ''}`, {
      credentials: 'same-origin',
    })
  },
  getImportBatch: (batchId) =>
    req(`/api/admin/properties/import-batches/${batchId}`, { credentials: 'same-origin' }),

  // Voice — the chat UI records via the browser's SpeechRecognition (STT)
  // and speaks replies through these endpoints (TTS).
  voiceRespond: (message, conversationId = null, speak = true, language = 'en-IN', voice = null) =>
    req(
      '/api/voice/respond',
      {
        method: 'POST',
        headers: JSON_HEADERS,
        credentials: 'same-origin',
        body: JSON.stringify({
          message,
          conversation_id: conversationId,
          speak,
          channel: 'voice',
          ...(language && language !== 'auto' ? { language } : {}),
          // Optional TTS voice override (backend VoiceRespondRequest.voice).
          ...(voice ? { voice } : {}),
        }),
      },
      AI_TIMEOUT_MS,
    ),
  // `voice` overrides the server's default TTS voice (e.g. the Tamil neural
  // voice for Tamil-script text); the backend picks its default when null.
  // Returns the raw Response (the caller reads audio via .blob()).
  synthesize: (text, language = null, voice = null) =>
    fetch('/api/voice/synthesize', {
      method: 'POST',
      headers: JSON_HEADERS,
      signal: timeoutSignal(AI_TIMEOUT_MS),
      body: JSON.stringify({ text, language, ...(voice ? { voice } : {}) }),
    }),

  // ---- Phase G: Executive Dashboards & Analytics ----
  analyticsExecutive: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    const suffix = qs.toString()
    return req(`/api/analytics/executive${suffix ? `?${suffix}` : ''}`, { credentials: 'same-origin' })
  },
  analyticsManager: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    const suffix = qs.toString()
    return req(`/api/analytics/manager${suffix ? `?${suffix}` : ''}`, { credentials: 'same-origin' })
  },
  analyticsAgent: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    const suffix = qs.toString()
    return req(`/api/analytics/agent${suffix ? `?${suffix}` : ''}`, { credentials: 'same-origin' })
  },
  analyticsExportAgentsUrl: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    const suffix = qs.toString()
    return `/api/analytics/export/agents${suffix ? `?${suffix}` : ''}`
  },

  // ---- Phase H: Customer Portal, Viewing Requests, Communications & Notifications ----
  customerProfile: () =>
    req('/api/customer/profile', { credentials: 'same-origin' }),
  customerUpdateProfile: (payload) =>
    req('/api/customer/profile', {
      method: 'PUT',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(payload),
    }),
  customerChangePassword: (payload) =>
    req('/api/customer/change-password', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(payload),
    }),
  customerDashboard: () =>
    req('/api/customer/dashboard', { credentials: 'same-origin' }),
  customerAppointments: () =>
    req('/api/customer/appointments', { credentials: 'same-origin' }),
  customerRequestViewing: (payload) =>
    req('/api/customer/appointments/request', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(payload),
    }),
  customerRescheduleViewing: (id, payload) =>
    req(`/api/customer/appointments/${id}/reschedule-request`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(payload),
    }),
  customerCancelViewing: (id, payload = {}) =>
    req(`/api/customer/appointments/${id}/cancel`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(payload),
    }),
  customerCommunications: (appointmentId = null) => {
    const qs = appointmentId ? `?appointment_id=${appointmentId}` : ''
    return req(`/api/customer/communications${qs}`, { credentials: 'same-origin' })
  },
  customerSendCommunication: (payload) =>
    req('/api/customer/communications', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(payload),
    }),
  customerNotifications: () =>
    req('/api/customer/notifications', { credentials: 'same-origin' }),
  customerMarkNotificationRead: (id) =>
    req(`/api/customer/notifications/${id}/read`, {
      method: 'POST',
      credentials: 'same-origin',
    }),
  customerMarkAllNotificationsRead: () =>
    req('/api/customer/notifications/mark-all-read', {
      method: 'POST',
      credentials: 'same-origin',
    }),

  // Agent viewing queue & customer management
  agentViewingRequests: (status = null) => {
    const qs = status ? `?status=${encodeURIComponent(status)}` : ''
    return req(`/api/agent/viewing-requests${qs}`, { credentials: 'same-origin' })
  },
  agentAcceptViewingRequest: (id, payload = {}) =>
    req(`/api/agent/appointments/${id}/accept-request`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(payload),
    }),
  agentRejectViewingRequest: (id, payload) =>
    req(`/api/agent/appointments/${id}/reject-request`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(payload),
    }),
  agentCustomers: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    const suffix = qs.toString()
    return req(`/api/agent/customers${suffix ? `?${suffix}` : ''}`, { credentials: 'same-origin' })
  },
  agentCustomerDetail: (id) =>
    req(`/api/agent/customers/${id}`, { credentials: 'same-origin' }),
  agentAddCustomerCommunication: (id, payload) =>
    req(`/api/agent/customers/${id}/communications`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(payload),
    }),
  agentNotifications: () =>
    req('/api/agent/notifications', { credentials: 'same-origin' }),
  agentMarkNotificationRead: (id) =>
    req(`/api/agent/notifications/${id}/read`, {
      method: 'POST',
      credentials: 'same-origin',
    }),
  agentMarkAllNotificationsRead: () =>
    req('/api/agent/notifications/mark-all-read', {
      method: 'POST',
      credentials: 'same-origin',
    }),

  // ---- Stage 6J: HR Management & Attendance ----
  hrDashboard: (date) =>
    req(`/api/hr/dashboard${date ? `?date=${encodeURIComponent(date)}` : ""}`, { credentials: "same-origin" }),
  hrEmployees: (params = {}) => {
    const q = new URLSearchParams()
    if (params.department) q.set("department", params.department)
    if (params.status) q.set("status", params.status)
    if (params.q) q.set("q", params.q)
    if (params.limit) q.set("limit", params.limit)
    if (params.offset) q.set("offset", params.offset)
    const qs = q.toString()
    return req(`/api/hr/employees${qs ? `?${qs}` : ""}`, { credentials: "same-origin" })
  },
  hrCreateEmployee: (payload) =>
    req("/api/hr/employees", {
      method: "POST",
      headers: JSON_HEADERS,
      credentials: "same-origin",
      body: JSON.stringify(payload),
    }),
  hrEmployee: (id) =>
    req(`/api/hr/employees/${id}`, { credentials: "same-origin" }),
  hrUpdateEmployee: (id, payload) =>
    req(`/api/hr/employees/${id}`, {
      method: "PATCH",
      headers: JSON_HEADERS,
      credentials: "same-origin",
      body: JSON.stringify(payload),
    }),
  hrDeactivateEmployee: (id, reason) =>
    req(`/api/hr/employees/${id}/deactivate`, {
      method: "POST",
      headers: JSON_HEADERS,
      credentials: "same-origin",
      body: JSON.stringify({ reason }),
    }),
  hrResetEmployeePassword: (id, payload = {}) =>
    req(`/api/hr/employees/${id}/reset-password`, {
      method: "POST",
      headers: JSON_HEADERS,
      credentials: "same-origin",
      body: JSON.stringify(payload),
    }),
  hrUpdateEmployeeAccount: (id, payload) =>
    req(`/api/hr/employees/${id}/account`, {
      method: "POST",
      headers: JSON_HEADERS,
      credentials: "same-origin",
      body: JSON.stringify(payload),
    }),
  hrLinkEmployeeAccount: (id, payload = {}) =>
    req(`/api/hr/employees/${id}/link-account`, {
      method: "POST",
      headers: JSON_HEADERS,
      credentials: "same-origin",
      body: JSON.stringify(payload),
    }),
  hrAttendance: (params = {}) => {
    const q = new URLSearchParams()
    if (params.date_from) q.set("date_from", params.date_from)
    if (params.date_to) q.set("date_to", params.date_to)
    if (params.employee_id) q.set("employee_id", params.employee_id)
    if (params.department) q.set("department", params.department)
    if (params.status) q.set("status", params.status)
    if (params.limit) q.set("limit", params.limit)
    if (params.offset) q.set("offset", params.offset)
    const qs = q.toString()
    return req(`/api/hr/attendance${qs ? `?${qs}` : ""}`, { credentials: "same-origin" })
  },
  hrCorrectAttendance: (payload) =>
    req("/api/hr/attendance/correct", {
      method: "POST",
      headers: JSON_HEADERS,
      credentials: "same-origin",
      body: JSON.stringify(payload),
    }),
  hrLeaveRequests: (params = {}) => {
    const q = new URLSearchParams()
    if (params.employee_id) q.set("employee_id", params.employee_id)
    if (params.status) q.set("status", params.status)
    if (params.limit) q.set("limit", params.limit)
    if (params.offset) q.set("offset", params.offset)
    const qs = q.toString()
    return req(`/api/hr/leave-requests${qs ? `?${qs}` : ""}`, { credentials: "same-origin" })
  },
  hrReviewLeave: (id, payload) =>
    req(`/api/hr/leave-requests/${id}/review`, {
      method: "POST",
      headers: JSON_HEADERS,
      credentials: "same-origin",
      body: JSON.stringify(payload),
    }),
  agentAttendanceToday: () =>
    req("/api/agent/attendance/today", { credentials: "same-origin" }),
  agentCheckIn: (payload = {}) =>
    req("/api/agent/attendance/check-in", {
      method: "POST",
      headers: JSON_HEADERS,
      credentials: "same-origin",
      body: JSON.stringify(payload),
    }),
  agentCheckOut: (payload = {}) =>
    req("/api/agent/attendance/check-out", {
      method: "POST",
      headers: JSON_HEADERS,
      credentials: "same-origin",
      body: JSON.stringify(payload),
    }),
  agentSubmitLeave: (payload) =>
    req("/api/agent/leave-requests", {
      method: "POST",
      headers: JSON_HEADERS,
      credentials: "same-origin",
      body: JSON.stringify(payload),
    }),
  agentOwnLeaveRequests: (params = {}) => {
    const q = new URLSearchParams()
    if (params.status) q.set("status", params.status)
    if (params.limit) q.set("limit", params.limit)
    const qs = q.toString()
    return req(`/api/agent/leave-requests${qs ? `?${qs}` : ""}`, { credentials: "same-origin" })
  },
  agentCancelLeave: (id) =>
    req(`/api/agent/leave-requests/${id}/cancel`, {
      method: "POST",
      credentials: "same-origin",
    }),
  changePassword: (payload) =>
    req('/api/auth/change-password', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(payload),
    }),
}

export default api
