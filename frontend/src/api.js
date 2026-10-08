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

  // Chat
  chat: (message, conversationId = null) =>
    fetch('/api/chat', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ message, conversation_id: conversationId }),
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

  // Properties
  searchProperties: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v)
    })
    return fetch(`/api/properties/search?${qs}`).then(handle)
  },
  getProperty: (id) => fetch(`/api/properties/${id}`).then(handle),

  // Leads / CRM
  listLeads: (status = null) =>
    fetch(`/api/leads${status ? `?status=${status}` : ''}`).then(handle),
  getLead: (id) => fetch(`/api/leads/${id}`).then(handle),
  createLead: (data) =>
    fetch('/api/leads', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify(data),
    }).then(handle),
  updateLead: (id, data) =>
    fetch(`/api/leads/${id}`, {
      method: 'PATCH',
      headers: JSON_HEADERS,
      body: JSON.stringify(data),
    }).then(handle),

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
