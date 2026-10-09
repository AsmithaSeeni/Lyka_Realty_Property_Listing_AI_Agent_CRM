// Thin API client for the Lyka Realty backend.
// All requests go through Vite's dev proxy (/api -> FastAPI :8000).

const JSON_HEADERS = { 'Content-Type': 'application/json' }

async function handle(res) {
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail || JSON.stringify(body)
    } catch {
      /* keep statusText */
    }
    const err = new Error(detail)
    err.status = res.status
    throw err
  }
  return res.json()
}

export const api = {
  health: () => fetch('/api/health').then(handle),

  // Chat — propertyId is the listing the customer is viewing (context for LykAI)
  chat: (message, conversationId = null, propertyId = null) =>
    fetch('/api/chat', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify({
        message,
        conversation_id: conversationId,
        ...(propertyId ? { property_id: propertyId } : {}),
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
  customerRegister: (email, password, name = '') =>
    fetch('/api/customer/register', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify({ email, password, name }),
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

  // Saved properties (signed-in customers)
  savedProperties: () =>
    fetch('/api/customer/saved', { credentials: 'same-origin' }).then(handle),
  saveProperty: (propertyId) =>
    fetch('/api/customer/saved', {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify({ property_id: propertyId }),
    }).then(handle),
  unsaveProperty: (propertyId) =>
    fetch(`/api/customer/saved/${propertyId}`, { method: 'DELETE', credentials: 'same-origin' }).then(handle),

  // Properties
  searchProperties: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    return fetch(`/api/properties/search?${qs}`).then(handle)
  },
  getProperty: (id) => fetch(`/api/properties/${id}`).then(handle),

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
  voiceRespond: (message, conversationId = null, speak = false) =>
    fetch('/api/voice/respond', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({
        message,
        conversation_id: conversationId,
        speak,
      }),
    }).then(handle),
  synthesize: (text, language = null) =>
    fetch('/api/voice/synthesize', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ text, language }),
    }),
}

export default api
