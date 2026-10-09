import React from 'react'
import { useNavigate, useParams, useSearchParams, Link } from 'react-router-dom'
import api from '../api.js'

/* ------------------------------------------------------------------ */
/* Property card — rendered inline inside the conversation, right under */
/* the LykAI reply that recommended it.                                 */
/* ------------------------------------------------------------------ */
function PropertyCard({ prop, index, onOpen }) {
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

  const highlights = String(prop.highlights || '')
    .split(/[;,]|\n/)
    .map((h) => h.trim())
    .filter((h) => h.length > 3)
    .slice(0, 2)

  return (
    <div className="pcard">
      <div className="pcard-top">
        <span className="pcard-emoji" aria-hidden="true">{emoji}</span>
        <div className="pcard-head">
          <div className="pcard-price">AED {price}</div>
          <div className="pcard-title">{type} · 📍 {loc}</div>
        </div>
        {index != null && <span className="pcard-num" title={`Recommendation ${index}`}>{index}</span>}
      </div>
      <div className="pcard-specs">
        <span>🛏 {beds} bd</span>
        <span>🛁 {baths} ba</span>
        <span>📐 {prop.area || '—'}</span>
      </div>
      {highlights.length > 0 && (
        <div className="pcard-high">{highlights.join(' · ')}</div>
      )}
      <button className="pcard-cta" onClick={() => onOpen(prop)}>
        View Property →
      </button>
    </div>
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
  const [searchParams] = useSearchParams()

  const [conversations, setConversations] = React.useState([])
  const [sideOpen, setSideOpen] = React.useState(false) // mobile drawer
  const [conversationId, setConversationId] = React.useState(
    routeConvId ? Number(routeConvId) : null,
  )
  const [messages, setMessages] = React.useState([])
  const [input, setInput] = React.useState('')
  const [typing, setTyping] = React.useState(false)
  const [error, setError] = React.useState(null)
  const [language, setLanguage] = React.useState('auto')
  const [customer, setCustomer] = React.useState(null)
  // Listing opened via "Ask LykAI about this property" (?ref=<id>) — keeps the
  // property in play so the customer never has to re-describe or give an id.
  const [focus, setFocus] = React.useState(null)

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

  /* -------- signed-in or guest? (sidebar sign-in nudge is guest-only) -------- */
  React.useEffect(() => {
    api.customerMe().then(setCustomer).catch(() => setCustomer(null))
  }, [])

  /* -------- arriving from a property page: ?ref=<id> becomes the focus -------- */
  React.useEffect(() => {
    const ref = Number(searchParams.get('ref'))
    if (ref > 0) {
      api
        .getProperty(ref)
        .then((p) => setFocus(p))
        .catch(() => setFocus({ property_id: ref }))
    }
  }, [searchParams])

  /* -------- resume the active conversation when opened without a URL id
       (e.g. "Ask LykAI about this property" lands on /chat?ref=…).
       Verified first — stale ids (other browser, deleted threads) are
       dropped so the customer always lands in a working conversation. -------- */
  React.useEffect(() => {
    if (routeConvId) return
    const saved = Number(sessionStorage.getItem('lyka_active_conv') || 0)
    if (saved > 0) {
      api
        .getConversation(saved)
        .then(() => {
          setConversationId(saved)
          navigate(`/chat/${saved}`, { replace: true })
        })
        .catch(() => sessionStorage.removeItem('lyka_active_conv'))
    }
  }, [routeConvId, navigate])

  /* -------- load a conversation's history -------- */
  React.useEffect(() => {
    if (!routeConvId) return
    const id = Number(routeConvId)
    setConversationId(id)
    sessionStorage.setItem('lyka_active_conv', String(id))
    api
      .getConversation(id)
      .then((conv) => {
        const recs = conv.property_recommendations || []
        const recById = new Map(recs.map((r) => [r.property_id, r]))
        const toCard = (r) => ({
          property_id: r.property_id,
          price: r.price,
          property_type: r.property_type,
          location: r.location,
          no__of__beds: r.bedrooms,
          no_of_baths: r.bathrooms,
          area: r.area,
          highlights: r.highlights,
        })

        const used = new Set()
        const hist = (conv.messages || []).map((m) => {
          let cards
          if (m.property_recommendation_ids?.length) {
            cards = m.property_recommendation_ids
              .map((pid) => recById.get(pid))
              .filter(Boolean)
              .map(toCard)
            cards.forEach((c) => used.add(c.property_id))
          }
          return {
            role: m.role,
            content: m.content,
            language: m.detected_language,
            at: m.created_at,
            properties: cards,
          }
        })

        // Older messages have no per-message ids — attach the leftover cards
        // to the last reply so history still shows what was recommended.
        const leftover = recs.filter((r) => !used.has(r.property_id)).map(toCard)
        if (leftover.length) {
          for (let i = hist.length - 1; i >= 0; i--) {
            if (hist[i].role === 'assistant') {
              hist[i].properties = [...(hist[i].properties || []), ...leftover]
              break
            }
          }
        }
        setMessages(hist)
      })
      .catch((e) => {
        // Foreign/stale thread (404) — fall back to a fresh chat so the
        // customer never gets stuck in a conversation they can't send to.
        if (e?.status === 404) {
          sessionStorage.removeItem('lyka_active_conv')
          setConversationId(null)
          setMessages([])
          navigate('/chat', { replace: true })
        }
      })
  }, [routeConvId, navigate])

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
    async (text, { fromVoice = false, propertyId = null } = {}) => {
      const msg = (text || '').trim()
      if (!msg) return
      setError(null)
      setInput('')
      setMessages((m) => [...m, { role: 'user', content: msg }])
      setTyping(true)

      // While a property is in focus (arrived from its details page), pass it
      // so LykAI can answer from the real dataset row — the customer just talks.
      const focusId = propertyId || focus?.property_id || null

      try {
        const res = await api.chat(msg, conversationId, focusId)
        setTyping(false)
        setConversationId(res.conversation_id)
        sessionStorage.setItem('lyka_active_conv', String(res.conversation_id))
        setMessages((m) => [
          ...m,
          {
            role: 'assistant',
            content: res.response,
            language: res.detected_language,
            // Cards render inline, directly under the reply that shared them
            properties: res.properties?.length ? res.properties : undefined,
          },
        ])
        // The listing's context now lives in the conversation itself
        if (focusId) setFocus(null)
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
        setError(e.message || 'Something went wrong talking to LykAI.')
        if (fromVoice) setVoiceState('idle')
      }
    },
    [conversationId, focus, muted, navigate, loadConversations],
  )

  /* -------- new conversation -------- */
  const newChat = () => {
    stopVoice()
    setSideOpen(false)
    sessionStorage.removeItem('lyka_active_conv')
    setConversationId(null)
    setMessages([])
    setFocus(null)
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
          <div className="side-label">Your conversations</div>
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

          {/* Guests: one quiet, non-blocking nudge (never a popup) */}
          {customer && !customer.authenticated && conversations.length > 0 && (
            <div className="side-keep">
              Want to keep your LykAI conversations?{' '}
              <Link to="/signin?next=/history">Sign in</Link>
            </div>
          )}
        </aside>

        {/* Main column */}
        <main className="chat-main">
          <div className="chat-head">
            <div className="who">
              <div className="avatar">LY</div>
              <div>
                <b>LykAI</b>
                <span>
                  AI Property Concierge by Lyka Realty
                  {currentConv
                    ? ` · #${currentConv.id} · ${currentConv.message_count ?? messages.length} messages`
                    : ''}
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
                  Hi! I'm LykAI, your AI Property Concierge from Lyka Realty.
                </b>
                Tell me what kind of property you're looking for, and I'll help you
                find the right match.
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
                  {m.role === 'user' ? '🙂' : 'LY'}
                </div>
                <div>
                  <div className="bubble">{m.content}</div>
                  {/* Property cards belong to this reply — part of the answer */}
                  {m.properties?.length > 0 && (
                    <div className="msg-cards">
                      {m.properties.map((p, j) => (
                        <PropertyCard
                          key={`${p.property_id}-${j}`}
                          index={j + 1}
                          prop={p}
                          onOpen={(prop) =>
                            prop.property_id && navigate(`/property/${prop.property_id}`)
                          }
                        />
                      ))}
                    </div>
                  )}
                  <div className="meta">
                    {m.language && m.language !== 'en' ? `${m.language} · ` : ''}
                    {m.at ? new Date(m.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
                  </div>
                </div>
              </div>
            ))}

            {typing && (
              <div className="msg assistant">
                <div className="avatar" style={{ width: 34, height: 34, fontSize: 13 }}>LY</div>
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

          {/* Listing in focus (came from its details page): one-tap follow-up */}
          {focus && (
            <div className="ref-chip">
              <span className="ref-chip__info">
                🏡 {focus.property_type || 'Property'}
                {focus.location ? ` · ${focus.location}` : ''} · Listing #{focus.property_id}
              </span>
              <button
                className="ref-chip__ask"
                onClick={() => send('Tell me more about this property.')}
                disabled={typing}
              >
                Tell me more about this property
              </button>
              <button
                className="ref-chip__x"
                aria-label="Dismiss property context"
                onClick={() => setFocus(null)}
              >
                ✕
              </button>
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
            {voiceState === 'listening' && 'LykAI is listening…'}
            {voiceState === 'processing' && 'LykAI is thinking…'}
            {voiceState === 'speaking' && 'LykAI is speaking…'}
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
                <b>{l.who === 'me' ? 'You' : 'LykAI'}:</b> {l.text}
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
            LykAI asks one question at a time and remembers your answers.
          </p>
        </div>
      )}
    </>
  )
}
