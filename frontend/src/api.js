// Thin API client for the Lyka Realty backend.
// All requests go through Vite's dev proxy (/api -> FastAPI :8000).

const JSON_HEADERS = { 'Content-Type': 'application/json' }

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

export const api = {
  health: () => fetch('/api/health').then(handle),

  // Chat — propertyId is the listing the customer is viewing (context for LykAI).
  // propertySource tells the backend which id space propertyId refers to:
  //   'dataset' (default) | 'record' (DB-backed listing from the browse pages).
  // No language argument: the agent classifies each message itself and replies
  // in that same language (English / Tamil / Tanglish / mixed).
  chat: (message, conversationId = null, propertyId = null, propertySource = null, channel = 'text') =>
    fetch('/api/chat', {
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
    }).then(handle),

  // Conversations
  listConversations: () => fetch('/api/conversations').then(handle),
  getConversation: (id) => fetch(`/api/conversations/${id}`).then(handle),
  createConversation: (data = {}) =>
    fetch('/api/conversations', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify(data),
    }).then(handle),

  // ---- Customer accounts (optional — guests chat without signing in) ----
  customerMe: () => fetch('/api/customer/me', { credentials: 'same-origin' }).then(handle),
  customerRegister: (email, password, name = '', confirmPassword = null) =>
    fetch('/api/customer/register', {
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
    }).then(handle),
  customerLogin: (email, password) =>
    fetch('/api/customer/login', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify({ email, password }),
    }).then(handle),
  customerLogout: () =>
    fetch('/api/customer/logout', { method: 'POST', credentials: 'same-origin' }).then(handle),

  // Saved properties (signed-in customers). `source` picks the id space:
  // 'dataset' (default, legacy) or 'record' (DB-backed listing).
  savedProperties: () =>
    fetch('/api/customer/saved', { credentials: 'same-origin' }).then(handle),
  saveProperty: (propertyId, source = 'dataset') =>
    fetch('/api/customer/saved', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify({ property_id: propertyId, source }),
    }).then(handle),
  unsaveProperty: (propertyId, source = 'dataset') =>
    fetch(`/api/customer/saved/${propertyId}${source === 'record' ? '?source=record' : ''}`, {
      method: 'DELETE',
      credentials: 'same-origin',
    }).then(handle),

  // Properties
  searchProperties: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    return fetch(`/api/properties/search?${qs}`).then(handle)
  },
  getProperty: (id) => fetch(`/api/properties/${id}`).then(handle),

  // Phase 6 — DB-backed public listings (approved + available only).
  // These serve the `properties` table, not the UAE JSON dataset.
  listRecords: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    return fetch(`/api/properties${qs.toString() ? `?${qs}` : ''}`).then(handle)
  },
  getPropertyRecord: (id) => fetch(`/api/properties/record/${id}`).then(handle),

  // ---- Agent authentication (internal CRM) ----
  login: (username, password) =>
    fetch('/api/auth/login', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify({ username, password }),
    }).then(handle),
  logout: () =>
    fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }).then(handle),
  me: () => fetch('/api/auth/me', { credentials: 'same-origin' }).then(handle),

  // ---- Agent CRM (protected — validated server-side on every request) ----
  agentDashboard: () => fetch('/api/agent/dashboard', { credentials: 'same-origin' }).then(handle),

  agentLeads: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    const suffix = qs.toString()
    return fetch(`/api/agent/leads${suffix ? `?${suffix}` : ''}`, { credentials: 'same-origin' }).then(handle)
  },
  agentLead: (id) => fetch(`/api/agent/leads/${id}`, { credentials: 'same-origin' }).then(handle),
  updateAgentLead: (id, data) =>
    fetch(`/api/agent/leads/${id}`, {
      method: 'PATCH',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }).then(handle),

  // ---- Phase 5: lead CRM workflow (staff only; cookie session) ----
  // Review → edit → EXPLICIT confirmation → save. The server always
  // recomputes score/priority; client-supplied scores are ignored there.
  createAgentLead: (data) =>
    fetch('/api/agent/leads', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }).then(handle),
  // Optional prefill: OpenAI-structured extraction of an enquiry (Phase 3).
  extractEnquiry: (enquiry) =>
    fetch('/api/agent/leads/extract', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify({ enquiry }),
    }).then(handle),
  agentLeadFollowUps: (leadId) =>
    fetch(`/api/agent/leads/${leadId}/follow-ups`, { credentials: 'same-origin' }).then(handle),
  createAgentFollowUp: (leadId, data) =>
    fetch(`/api/agent/leads/${leadId}/follow-ups`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }).then(handle),
  updateAgentFollowUp: (id, patch) =>
    fetch(`/api/agent/follow-ups/${id}`, {
      method: 'PATCH',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(patch),
    }).then(handle),
  listAgentFollowUps: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    const suffix = qs.toString()
    return fetch(`/api/agent/follow-ups${suffix ? `?${suffix}` : ''}`, { credentials: 'same-origin' }).then(handle)
  },
  // Deterministic DB matching for a saved lead + deduplicated history save.
  runLeadRecommendations: (leadId, data = {}) =>
    fetch(`/api/agent/leads/${leadId}/recommendations`, {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify(data),
    }).then(handle),

  agentConversations: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    const suffix = qs.toString()
    return fetch(`/api/agent/conversations${suffix ? `?${suffix}` : ''}`, { credentials: 'same-origin' }).then(handle)
  },
  agentConversation: (id) =>
    fetch(`/api/agent/conversations/${id}`, { credentials: 'same-origin' }).then(handle),

  // Voice
  transcribe: (blob, language = null) => {
    const form = new FormData()
    form.append('file', blob, 'recording.webm')
    if (language) form.append('language', language)
    return fetch('/api/voice/transcribe', { method: 'POST', body: form }).then(handle)
  },
  voiceRespond: (message, conversationId = null, speak = true, language = 'ta-Latn', voice = null) =>
    fetch('/api/voice/respond', {
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
    }).then(handle),
  // `voice` overrides the server's default TTS voice (e.g. the Tamil neural
  // voice for Tamil-script text); the backend picks its default when null.
  synthesize: (text, language = null, voice = null) =>
    fetch('/api/voice/synthesize', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ text, language, ...(voice ? { voice } : {}) }),
    }),
}

export default api
