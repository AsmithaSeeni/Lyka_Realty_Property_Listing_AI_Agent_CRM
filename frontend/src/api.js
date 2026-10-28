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
}

export default api
