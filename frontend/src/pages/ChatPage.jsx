import React from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import api from '../api.js'

/* ------------------------------------------------------------------ */
/* Property card                                                       */
/* ------------------------------------------------------------------ */
function PropertyCard({ prop, onOpen }) {
  const beds = prop.no__of__beds ?? prop.bedrooms ?? '—'
  const baths = prop.no_of_baths ?? prop.bathrooms ?? '—'
  const price = prop.price
  const loc = prop.location || ''
  const type = prop.property_type || 'Property'
  const emoji =
    /villa/i.test(type) ? '🏡' :
    /townhouse/i.test(type) ? '🏘️' :
    /penthouse/i.test(type) ? '🌆' :
    /studio/i.test(String(beds)) ? '🏠' :
    /plot|land/i.test(type) ? '🗺️' : '🏢'

  return (
    <button className="prop-card" onClick={() => onOpen(prop)}>
      <div className="prop-thumb">
        <span>{emoji}</span>
        <span className="loc">📍 {loc}</span>
      </div>
      <div className="prop-body">
        <div className="prop-price">AED {price}</div>
        <div className="prop-title">{type} · {loc}</div>
        <div className="prop-specs">
          <span>🛏 {beds}</span>
          <span>🛁 {baths}</span>
          <span>📐 {prop.area || '—'}</span>
        </div>
      </div>
    </button>
  )
}

/* ------------------------------------------------------------------ */
/* Suggestions                                                         */
/* ------------------------------------------------------------------ */
const SUGGESTIONS = [
  '2 bed apartment in Dubai Marina under 3 million',
  'Show me villas in Arabian Ranches',
  'What can I get in Sharjah for 1 million?',
  'துபாயில் ஸ்டுடியோ வேணும்',
]

/* ------------------------------------------------------------------ */
/* Speech helpers (browser Web Speech API)                             */
/* ------------------------------------------------------------------ */
const SpeechRecognition =
  typeof window !== 'undefined' &&
  (window.SpeechRecognition || window.webkitSpeechRecognition)

function speakText(text) {
  return new Promise((resolve) => {
    if (!window.speechSynthesis || !text) return resolve()
    window.speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(text)
    u.lang = /[஀-௿]/.test(text) ? 'ta-IN' : 'en-US'
    u.rate = 1.02
    u.onend = resolve
    u.onerror = resolve
    window.speechSynthesis.speak(u)
  })
}

/* ------------------------------------------------------------------ */
/* Main chat page                                                      */
/* ------------------------------------------------------------------ */
export default function ChatPage() {
  const navigate = useNavigate()
  const { conversationId: routeConvId } = useParams()

  const [conversations, setConversations] = React.useState([])
  const [sideOpen, setSideOpen] = React.useState(false) // mobile drawer
  const [conversationId, setConversationId] = React.useState(
    routeConvId ? Number(routeConvId) : null,
  )
  const [messages, setMessages] = React.useState([])
  const [input, setInput] = React.useState('')
  const [typing, setTyping] = React.useState(false)
  const [properties, setProperties] = React.useState([])
  const [error, setError] = React.useState(null)
  const [language, setLanguage] = React.useState('auto')

  // Voice state
  const [voiceMode, setVoiceMode] = React.useState(false)
  const [voiceState, setVoiceState] = React.useState('idle') // idle|listening|processing|speaking
  const [liveTranscript, setLiveTranscript] = React.useState('')
  const [muted, setMuted] = React.useState(false)
  const [voiceLog, setVoiceLog] = React.useState([])
  const recognitionRef = React.useRef(null)
  const stopVoiceRef = React.useRef(false)

  const scrollRef = React.useRef(null)
  const inputRef = React.useRef(null)

  /* -------- load conversation list -------- */
  const loadConversations = React.useCallback(() => {
    api.listConversations().then(setConversations).catch(() => {})
  }, [])

  React.useEffect(loadConversations, [loadConversations])

  /* -------- load a conversation's history -------- */
  React.useEffect(() => {
    if (!routeConvId) return
    setConversationId(Number(routeConvId))
    api
      .getConversation(routeConvId)
      .then((conv) => {
        const hist = (conv.messages || []).map((m) => ({
          role: m.role,
          content: m.content,
          language: m.detected_language,
          at: m.created_at,
        }))
        setMessages(hist)
        const recs = conv.property_recommendations || []
        if (recs.length) {
          setProperties(
            recs.map((r) => ({
              property_id: r.property_id,
              price: r.price,
              property_type: r.property_type,
              location: r.location,
              no__of__beds: r.bedrooms,
              no_of_baths: r.bathrooms,
              area: r.area,
              highlights: r.highlights,
            })),
          )
        }
      })
      .catch(() => {})
  }, [routeConvId])

  /* -------- autoscroll -------- */
  React.useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, typing])

  /* -------- focus composer on desktop so you can type immediately -------- */
  React.useEffect(() => {
    if (window.matchMedia?.('(min-width: 981px)')?.matches) {
      inputRef.current?.focus()
    }
  }, [])

  /* -------- send a text message -------- */
  const send = React.useCallback(
    async (text, { fromVoice = false } = {}) => {
      const msg = (text || '').trim()
      if (!msg) return
      setError(null)
      setInput('')
      setMessages((m) => [...m, { role: 'user', content: msg }])
      setTyping(true)

      try {
        const res = await api.chat(msg, conversationId)
        setTyping(false)
        setConversationId(res.conversation_id)
        setMessages((m) => [
          ...m,
          {
            role: 'assistant',
            content: res.response,
            language: res.detected_language,
          },
        ])
        if (res.properties && res.properties.length) {
          setProperties(res.properties)
        }
        if (!conversationId) {
          // keep URL in sync so refresh/reopen works
          navigate(`/chat/${res.conversation_id}`, { replace: true })
        }
        loadConversations()

        // Voice mode: speak the reply
        if (fromVoice && !muted && res.response) {
          setVoiceState('speaking')
          setVoiceLog((l) => [...l, { who: 'ai', text: res.response }])
          await speakText(res.response)
          setVoiceState('idle')
        }
      } catch (e) {
        setTyping(false)
        setError(e.message || 'Something went wrong talking to the backend.')
        if (fromVoice) setVoiceState('idle')
      }
    },
    [conversationId, muted, navigate, loadConversations],
  )

  /* -------- new conversation -------- */
  const newChat = () => {
    stopVoice()
    setSideOpen(false)
    setConversationId(null)
    setMessages([])
    setProperties([])
    setError(null)
    navigate('/chat', { replace: true })
    setTimeout(() => inputRef.current?.focus(), 50)
  }

  /* ---------------- Voice mode ---------------- */
  const stopVoice = React.useCallback(() => {
    stopVoiceRef.current = true
    try {
      recognitionRef.current?.stop()
    } catch {
      /* noop */
    }
    if (window.speechSynthesis) window.speechSynthesis.cancel()
    setVoiceState('idle')
    setLiveTranscript('')
  }, [])

  const listenOnce = React.useCallback(() => {
    if (!SpeechRecognition) {
      setError(
        'Speech recognition is not supported in this browser. Try Chrome or Edge.',
      )
      setVoiceState('idle')
      return
    }
    const rec = new SpeechRecognition()
    recognitionRef.current = rec
    rec.lang = language === 'ta' ? 'ta-IN' : language === 'en' ? 'en-US' : 'en-US'
    rec.interimResults = true
    rec.continuous = false
    rec.maxAlternatives = 1

    rec.onresult = (event) => {
      let interim = ''
      let final = ''
      for (const result of event.results) {
        if (result.isFinal) final += result[0].transcript
        else interim += result[0].transcript
      }
      setLiveTranscript(final || interim)
      if (final) {
        setVoiceLog((l) => [...l, { who: 'me', text: final }])
        setVoiceState('processing')
        send(final, { fromVoice: true }).then(() => {
          // After reply, listen again for a natural loop
          if (!stopVoiceRef.current) setTimeout(() => listenOnce(), 400)
        })
      }
    }
    rec.onerror = (event) => {
      if (event.error === 'no-speech') {
        setLiveTranscript("I didn't catch that — please speak again.")
        if (!stopVoiceRef.current) setTimeout(() => listenOnce(), 300)
        return
      }
      if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
        setError('Microphone access was denied. Allow the mic to use voice mode.')
        setVoiceState('idle')
        return
      }
      // other errors: retry gently
      if (!stopVoiceRef.current) setTimeout(() => listenOnce(), 400)
    }
    rec.onend = () => {
      // If we didn't transition into processing/speaking, resume listening
      if (!stopVoiceRef.current && voiceState === 'listening') {
        setTimeout(() => {
          try {
            rec.start()
          } catch {
            /* already started */
          }
        }, 250)
      }
    }

    try {
      stopVoiceRef.current = false
      setVoiceState('listening')
      setLiveTranscript('')
      rec.start()
    } catch {
      setVoiceState('idle')
    }
  }, [language, send, voiceState])

  const startVoice = () => {
    setVoiceMode(true)
    setVoiceLog([])
    setError(null)
    listenOnce()
  }

  const endVoice = () => {
    stopVoice()
    setVoiceMode(false)
  }

  /* ---------------- render ---------------- */
  const currentConv = conversations.find((c) => c.id === conversationId)

  return (
    <>
      <div className="chat-shell">
        {/* Mobile: dim background behind the conversation drawer */}
        {sideOpen && (
          <div className="side-backdrop" onClick={() => setSideOpen(false)} aria-hidden="true" />
        )}

        {/* Sidebar: conversation list (off-canvas drawer on mobile) */}
        <aside className={`chat-side${sideOpen ? ' open' : ''}`}>
          <button className="btn btn-dark btn-sm btn-block" onClick={newChat}>
            + New conversation
          </button>
          <div className="side-label">Recent</div>
          {conversations.length === 0 && (
            <div style={{ fontSize: 13, color: 'var(--muted)', padding: '0 6px' }}>
              No conversations yet. Start one!
            </div>
          )}
          {conversations.map((c) => (
            <button
              key={c.id}
              className={`conv-item ${c.id === conversationId ? 'active' : ''}`}
              onClick={() => {
                setSideOpen(false)
                navigate(`/chat/${c.id}`)
              }}
            >
              <b>{c.customer_name || `Conversation #${c.id}`}</b>
              <span>
                {c.message_count ?? 0} messages · {new Date(c.updated_at || c.created_at).toLocaleDateString()}
              </span>
            </button>
          ))}
        </aside>

        {/* Main column */}
        <main className="chat-main">
          <div className="chat-head">
            <div className="who">
              <div className="avatar">AI</div>
              <div>
                <b>Lyka AI Consultant</b>
                <span>
                  {currentConv
                    ? `Conversation #${currentConv.id} · ${currentConv.message_count ?? messages.length} messages`
                    : 'New conversation · English / தமிழ் / Tanglish'}
                </span>
              </div>
            </div>
            <div className="chat-actions">
              <button
                className="icon-btn mobile-only"
                title="Conversations"
                aria-label="Open conversations"
                onClick={() => setSideOpen((o) => !o)}
              >
                ☰
              </button>
              <select
                className="lang-select"
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                title="Reply language"
              >
                <option value="auto">🌐 Auto-detect</option>
                <option value="en">English</option>
                <option value="ta">தமிழ்</option>
              </select>
              <button
                className={`icon-btn ${voiceMode ? 'active' : ''}`}
                title="Voice mode"
                onClick={() => (voiceMode ? endVoice() : startVoice())}
              >
                {voiceMode ? '📵' : '🎙️'}
              </button>
              <button className="icon-btn" title="New chat" onClick={newChat}>
                ✏️
              </button>
            </div>
          </div>

          {error && (
            <div style={{ padding: '10px 22px' }}>
              <div className="notice">⚠️ {error}</div>
            </div>
          )}

          {/* Messages */}
          <div className="chat-scroll" ref={scrollRef}>
            {messages.length === 0 && !typing && (
              <div className="empty">
                <div className="big">👋</div>
                <b style={{ display: 'block', fontSize: 18, color: 'var(--ink)', marginBottom: 6 }}>
                  Welcome! I'm your Lyka Realty AI consultant.
                </b>
                Tell me what you're looking for — location, budget, bedrooms — and I'll
                search 25,000+ UAE properties for you.
                <div className="suggestions" style={{ justifyContent: 'center', marginTop: 20, padding: 0 }}>
                  {SUGGESTIONS.map((s) => (
                    <button key={s} className="suggestion" onClick={() => send(s)}>
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m, i) => (
              <div key={i} className={`msg ${m.role}`}>
                <div className="avatar" style={{ width: 34, height: 34, fontSize: 13 }}>
                  {m.role === 'user' ? '🙂' : 'AI'}
                </div>
                <div>
                  <div className="bubble">{m.content}</div>
                  <div className="meta">
                    {m.language && m.language !== 'en' ? `${m.language} · ` : ''}
                    {m.at ? new Date(m.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
                  </div>
                </div>
              </div>
            ))}

            {typing && (
              <div className="msg assistant">
                <div className="avatar" style={{ width: 34, height: 34, fontSize: 13 }}>AI</div>
                <div className="bubble">
                  <span className="typing">
                    <i />
                    <i />
                    <i />
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* Suggestions (visible when conversation started) */}
          {messages.length > 0 && messages.length < 3 && (
            <div className="suggestions">
              {SUGGESTIONS.slice(0, 3).map((s) => (
                <button key={s} className="suggestion" onClick={() => send(s)}>
                  {s}
                </button>
              ))}
            </div>
          )}

          {/* Property rail */}
          {properties.length > 0 && (
            <div className="prop-rail">
              <div className="prop-rail-head">
                <b>🏠 Recommended properties ({properties.length})</b>
                <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                  click a card for full details
                </span>
              </div>
              <div className="prop-grid">
                {properties.map((p, i) => (
                  <PropertyCard
                    key={`${p.property_id}-${i}`}
                    prop={p}
                    onOpen={(prop) =>
                      prop.property_id && navigate(`/property/${prop.property_id}`)
                    }
                  />
                ))}
              </div>
            </div>
          )}

          {/* Composer */}
          <div className="composer">
            <div className="composer-row">
              <input
                ref={inputRef}
                type="text"
                value={input}
                placeholder="Describe your ideal property… (e.g. 3 bed in JVC under 2 million)"
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    send(input)
                  }
                }}
                disabled={typing}
              />
              <button
                className={`icon-btn ${voiceState === 'listening' ? 'recording' : ''}`}
                title="Quick voice input"
                onClick={() => (voiceMode ? endVoice() : startVoice())}
                disabled={typing}
              >
                {voiceState === 'listening' ? '⏹' : '🎤'}
              </button>
              <button
                className="icon-btn active"
                title="Send"
                onClick={() => send(input)}
                disabled={typing || !input.trim()}
                style={{ background: 'var(--gold)', color: 'var(--maroon-deep)', borderColor: 'var(--gold)' }}
              >
                ➤
              </button>
            </div>
            {liveTranscript && voiceMode && (
              <div className="transcript">🎙 You: {liveTranscript}</div>
            )}
          </div>
        </main>
      </div>

      {/* Voice overlay */}
      {voiceMode && (
        <div className="voice-stage">
          <div className={`voice-status`}>
            {voiceState === 'listening' && 'Listening…'}
            {voiceState === 'processing' && 'Thinking…'}
            {voiceState === 'speaking' && 'Speaking…'}
            {voiceState === 'idle' && 'Voice mode'}
          </div>

          <div
            className={`voice-orb ${
              voiceState === 'listening'
                ? 'listening'
                : voiceState === 'speaking'
                  ? 'speaking'
                  : ''
            }`}
          >
            {voiceState === 'speaking' ? '🔊' : voiceState === 'processing' ? '🧠' : '🎙️'}
          </div>

          <div className="voice-transcript-live">
            {liveTranscript || (voiceState === 'listening' ? 'Go ahead, I’m listening…' : '…')}
          </div>

          <div className="voice-log">
            {voiceLog.slice(-6).map((l, i) => (
              <div key={i} className={`v-msg ${l.who === 'me' ? 'me' : ''}`}>
                <b>{l.who === 'me' ? 'You' : 'AI'}:</b> {l.text}
              </div>
            ))}
          </div>

          <div className="voice-controls">
            <button
              className="voice-btn"
              onClick={() => {
                setMuted((m) => !m)
                if (!muted && window.speechSynthesis) window.speechSynthesis.cancel()
              }}
            >
              {muted ? '🔇 Unmute' : '🔊 Mute replies'}
            </button>
            <button
              className="voice-btn"
              onClick={() => {
                stopVoice()
                setTimeout(listenOnce, 300)
              }}
            >
              ↻ Restart listening
            </button>
            <button className="voice-btn danger" onClick={endVoice}>
              ⏹ End voice chat
            </button>
            <button className="voice-btn gold" onClick={() => { endVoice(); }}>
              Done — back to text
            </button>
          </div>

          <p className="voice-hint">
            Speak naturally — “I need a 2 bedroom flat in JVC, budget 1.5 million”.
            The agent asks one question at a time and remembers your answers.
          </p>
        </div>
      )}
    </>
  )
}
