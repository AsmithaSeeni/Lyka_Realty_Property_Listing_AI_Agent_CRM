import React from 'react'
import { useNavigate, useParams, useSearchParams, Link } from 'react-router-dom'
import api from '../api.js'

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */
const TAMIL_SCRIPT = /[஀-௿]/

/* TTS voice choice uses only voices the backend already supports:
   Tamil-script text gets the Tamil neural female voice, everything else
   (English / Tanglish latin) stays on the server default. */
function pickTtsVoice(text) {
  return TAMIL_SCRIPT.test(String(text || '')) ? 'ta-IN-PallaviNeural' : null
}

function pickTtsLanguage(text) {
  return TAMIL_SCRIPT.test(String(text || '')) ? 'ta-IN' : 'en-IN'
}

const LANG_LABEL = { en: 'English', ta: 'தமிழ்', 'ta-Latn': 'Tanglish', mixed: 'Mixed' }

function fmtTime(iso) {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return null
  }
}

/* ------------------------------------------------------------------ */
/* Property card — rendered inline inside the conversation, right under */
/* the LykAI reply that recommended it. Shows ONLY fields the backend   */
/* actually returned — never invented data.                             */
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

  const clickable = Boolean(prop.property_id || prop.property_record_id)

  return (
    <div className="pcard">
      <div className="pcard-top">
        <span className="pcard-emoji" aria-hidden="true">{emoji}</span>
        <div className="pcard-head">
          <div className="pcard-price">
            {price != null && price !== '' ? `AED ${price}` : 'Price on request'}
          </div>
          <div className="pcard-title">{type}{loc ? ` · ${loc}` : ''}</div>
        </div>
        {index != null && (
          <span className="pcard-num" title={`Recommendation ${index}`}>{index}</span>
        )}
      </div>
      <div className="pcard-specs">
        <span>Bedrooms {beds}</span>
        <span>Bathrooms {baths}</span>
        <span>{prop.area ? `Area ${prop.area}` : 'Area —'}</span>
      </div>
      {highlights.length > 0 && (
        <div className="pcard-high">{highlights.join(' · ')}</div>
      )}
      {clickable && (
        <button className="pcard-cta" onClick={() => onOpen(prop)}>
          View property details
        </button>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Suggested prompts                                                   */
/* ------------------------------------------------------------------ */
const SUGGESTIONS = [
  'Find a villa near Dubai Marina',
  'Show properties within my budget',
  'I want to rent an apartment',
  'Speak with a property consultant',
  'Dubai-la 2 BHK apartment venum, sea view oda',
  'Rent-kaaga 1 BHK apartment venum, furnished',
]

/* ------------------------------------------------------------------ */
/* Speech helpers (browser Web Speech API for STT)                     */
/* ------------------------------------------------------------------ */
const SpeechRecognition =
  typeof window !== 'undefined' &&
  (window.SpeechRecognition || window.webkitSpeechRecognition)

/* ------------------------------------------------------------------ */
/* Audio playback — one shared element with a stoppable controller.    */
/* Any awaited playback can be interrupted (Stop button / voice mode   */
/* exit) and its promise still resolves, so state never gets stuck.    */
/* ------------------------------------------------------------------ */
let sharedAudio = null
let activePlayback = null // { audio, stop } — playback currently in flight

function getAudioElement() {
  if (!sharedAudio && typeof window !== 'undefined') {
    sharedAudio = new Audio()
  }
  return sharedAudio
}

function stopActivePlayback() {
  if (activePlayback) activePlayback.stop()
}

function playAudioSrc(src, { revokeUrl = false } = {}) {
  const audio = getAudioElement()
  if (!audio) return Promise.resolve(false)
  audio.pause()
  audio.src = src
  return new Promise((resolve) => {
    let settled = false
    const finish = (ok) => {
      if (settled) return
      settled = true
      audio.onended = null
      audio.onerror = null
      if (activePlayback && activePlayback.audio === audio) activePlayback = null
      if (revokeUrl) URL.revokeObjectURL(src)
      resolve(ok)
    }
    audio.onended = () => finish(true)
    audio.onerror = () => finish(false)
    activePlayback = {
      audio,
      stop: () => {
        try { audio.pause() } catch { /* noop */ }
        finish(false)
      },
    }
    audio.play().catch(() => finish(false))
  })
}

function unlockAudio() {
  try {
    const audio = getAudioElement()
    if (audio && !audio.src) {
      audio.src = 'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA'
      audio.play().then(() => audio.pause()).catch(() => { })
    }
  } catch {
    /* noop */
  }
}

async function playBase64Audio(base64Data, format = 'mp3') {
  if (!base64Data) return false
  return playAudioSrc(`data:audio/${format};base64,${base64Data}`)
}

/* Server-synthesized audio (neural voices via the backend). */
async function playBackendAudio(text, lang = 'en-IN', voice = null) {
  try {
    stopActivePlayback()
    const res = await api.synthesize(text, lang, voice)
    if (!res || !res.ok) return false
    const blob = await res.blob()
    if (!blob || blob.size < 300) return false
    const url = URL.createObjectURL(blob)
    return playAudioSrc(url, { revokeUrl: true })
  } catch {
    return false
  }
}

/* Clean speech text: strip internal notes, markdown and emoji. */
function cleanSpeechText(text) {
  return String(text || '')
    .replace(/\[internal[^\]]*\]/gi, '')
    .replace(/[*_#`~>\[\]\(\)]/g, ' ')
    .replace(/[\u{1F600}-\u{1F64F}\u{1F300}-\u{1F5FF}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/gu, '')
    .replace(/\s+/g, ' ')
    .trim()
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
  const [customer, setCustomer] = React.useState(null)
  // Listing opened via "Ask LykAI about this property" (?ref=<id>) — keeps the
  // property in play so the customer never has to re-describe or give an id.
  const [focus, setFocus] = React.useState(null)

  // Truthful connection state: backendUp comes from a real health check,
  // online from the browser's own connectivity events.
  const [backendUp, setBackendUp] = React.useState(null)
  const [online, setOnline] = React.useState(
    typeof navigator === 'undefined' ? true : navigator.onLine !== false,
  )

  // Voice state — kept separate from chat state.
  const [voiceMode, setVoiceMode] = React.useState(false)
  const [voiceState, setVoiceState] = React.useState('idle') // idle|listening|processing|speaking
  const [liveTranscript, setLiveTranscript] = React.useState('')
  const [muted, setMuted] = React.useState(false)
  const [voiceLog, setVoiceLog] = React.useState([])
  const [micBlocked, setMicBlocked] = React.useState(false) // permission denied
  const [speakingKey, setSpeakingKey] = React.useState(null) // message currently being read aloud
  const [hasLastReply, setHasLastReply] = React.useState(false)

  const recognitionRef = React.useRef(null)
  const stopVoiceRef = React.useRef(false)
  // voiceSessionRef increments per listen session, so a stale recognition's
  // onresult/onend can never fire into a newer session (that race used to
  // send the same audio segment twice). voiceSendingRef is true while a
  // voice send is in flight, so duplicate final results send exactly once.
  const voiceSessionRef = React.useRef(0)
  const voiceSendingRef = React.useRef(false)
  // Last spoken assistant reply — used by "Replay last reply".
  const lastReplyRef = React.useRef(null)

  const scrollRef = React.useRef(null)
  const inputRef = React.useRef(null)

  /* -------- load conversation list -------- */
  const loadConversations = React.useCallback(() => {
    api.listConversations().then(setConversations).catch(() => { })
  }, [])

  React.useEffect(loadConversations, [loadConversations])

  /* -------- signed-in or guest? (sidebar sign-in nudge is guest-only) -------- */
  React.useEffect(() => {
    api.customerMe().then(setCustomer).catch(() => setCustomer(null))
  }, [])

  /* -------- truthful backend status (health check, refreshed quietly) ---- */
  React.useEffect(() => {
    let alive = true
    const check = () =>
      api
        .health()
        .then(() => alive && setBackendUp(true))
        .catch(() => alive && setBackendUp(false))
    check()
    const t = setInterval(check, 60000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  /* -------- browser connectivity -------- */
  React.useEffect(() => {
    const goOnline = () => setOnline(true)
    const goOffline = () => setOnline(false)
    window.addEventListener('online', goOnline)
    window.addEventListener('offline', goOffline)
    return () => {
      window.removeEventListener('online', goOnline)
      window.removeEventListener('offline', goOffline)
    }
  }, [])

  /* -------- arriving from a property page: ?ref=<id> becomes the focus.
       ?src=record marks a DB-backed listing (the /properties/:id browse
       pages); without it the id refers to a UAE dataset listing (legacy).
       The id spaces are different, so the source must round-trip with the
       focus or the wrong listing would be discussed. -------- */
  React.useEffect(() => {
    const ref = Number(searchParams.get('ref'))
    if (ref <= 0) return
    const src = searchParams.get('src') === 'record' ? 'record' : 'dataset'
    const req = src === 'record' ? api.getPropertyRecord(ref) : api.getProperty(ref)
    req
      .then((p) =>
        setFocus(src === 'record' ? { ...p, property_id: p.id, source: 'record' } : p),
      )
      .catch(() => setFocus({ property_id: ref, source: src }))
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
          // DB-backed recommendations carry their own record id — keep it so
          // the card links to /properties/:id instead of the dataset space.
          property_record_id: r.property_record_id || null,
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

  /* -------- open a recommended listing (record space wins when present) --- */
  const openProperty = React.useCallback(
    (p) => {
      if (p.property_record_id) navigate(`/properties/${p.property_record_id}`)
      else if (p.property_id) navigate(`/property/${p.property_id}`)
    },
    [navigate],
  )

  /* -------- speak a reply through the server's neural voices ----------- */
  const speakMessage = React.useCallback(async (text, key) => {
    if (speakingKey === key) {
      // second click on the same message = Stop
      stopActivePlayback()
      if (window.speechSynthesis) window.speechSynthesis.cancel()
      setSpeakingKey(null)
      return false
    }
    stopActivePlayback()
    if (window.speechSynthesis) window.speechSynthesis.cancel()
    unlockAudio()
    const cleanText = cleanSpeechText(text)
    if (!cleanText) return false
    setSpeakingKey(key)
    const lang = pickTtsLanguage(cleanText)
    let ok = await playBackendAudio(cleanText, lang, pickTtsVoice(cleanText))
    if (!ok && window.speechSynthesis) {
      try {
        window.speechSynthesis.cancel()
        const utterance = new SpeechSynthesisUtterance(cleanText)
        utterance.lang = lang
        ok = await new Promise((resolve) => {
          utterance.onend = () => resolve(true)
          utterance.onerror = () => resolve(false)
          window.speechSynthesis.speak(utterance)
        })
      } catch { /* noop */ }
    }
    setSpeakingKey(null)
    return ok
  }, [speakingKey])

  /* -------- send a text or voice message -------- */
  const send = React.useCallback(
    async (text, { fromVoice = false, propertyId = null } = {}) => {
      const msg = (text || '').trim()
      if (!msg) return
      // Stop any active speech/audio playback to prevent overlap
      stopActivePlayback()
      if (window.speechSynthesis) window.speechSynthesis.cancel()
      setSpeakingKey(null)
      unlockAudio()
      setError(null)
      setInput('')
      if (inputRef.current) inputRef.current.style.height = 'auto'
      const sentAt = new Date().toISOString()
      setMessages((m) => [...m, { role: 'user', content: msg, at: sentAt }])
      setTyping(true)

      const focusId = propertyId || focus?.property_id || null
      const focusSource = focus?.source || null
      const isVoice = fromVoice || voiceMode

      try {
        let res
        if (fromVoice) {
          // Dedicated voice turn: casual reply + synthesized neural audio in 1 trip.
          res = await api.voiceRespond(msg, conversationId, !muted)
        } else {
          res = await api.chat(msg, conversationId, focusId, focusSource, isVoice ? 'voice' : 'text')
        }

        setTyping(false)
        setConversationId(res.conversation_id)
        sessionStorage.setItem('lyka_active_conv', String(res.conversation_id))
        setMessages((m) => [
          ...m,
          {
            role: 'assistant',
            content: res.response,
            language: res.detected_language,
            at: new Date().toISOString(),
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

        // Voice mode: speak the reply (server-synthesized neural audio)
        if (fromVoice && res.response) {
          lastReplyRef.current = {
            text: res.response,
            base64: res.audio_base64 || null,
            format: res.audio_format || 'mp3',
          }
          setHasLastReply(true)
          if (!muted) {
            setVoiceState('speaking')
            setVoiceLog((l) => [...l, { who: 'ai', text: res.response }])
            let played = false
            if (res.audio_base64) {
              played = await playBase64Audio(res.audio_base64, res.audio_format || 'mp3')
            }
            if (!played) {
              const cleanText = cleanSpeechText(res.response)
              if (cleanText) {
                const lang = pickTtsLanguage(cleanText)
                played = await playBackendAudio(cleanText, lang, pickTtsVoice(cleanText))
                if (!played && window.speechSynthesis) {
                  try {
                    window.speechSynthesis.cancel()
                    const utterance = new SpeechSynthesisUtterance(cleanText)
                    utterance.lang = lang
                    await new Promise((resolve) => {
                      utterance.onend = () => resolve(true)
                      utterance.onerror = () => resolve(false)
                      window.speechSynthesis.speak(utterance)
                    })
                  } catch { /* noop */ }
                }
              }
            }
            setVoiceState('idle')
          }
        }
      } catch (e) {
        setTyping(false)
        // Honest failure feedback; the message stays in the thread so the
        // customer can see what was attempted and simply type again.
        setError(e.message || 'Something went wrong talking to LykAI.')
        if (fromVoice) setVoiceState('idle')
      }
    },
    [conversationId, focus, muted, navigate, loadConversations, voiceMode],
  )

  /* -------- stop voice mode (exits cleanly, interrupts any speech) ---- */
  const stopVoice = React.useCallback(() => {
    stopVoiceRef.current = true
    voiceSessionRef.current += 1 // invalidate any in-flight recognition
    try { recognitionRef.current?.stop() } catch { /* noop */ }
    try { recognitionRef.current?.abort() } catch { /* noop */ }
    stopActivePlayback()
    if (window.speechSynthesis) window.speechSynthesis.cancel()
    setVoiceState('idle')
    setLiveTranscript('')
    setSpeakingKey(null)
  }, [])

  const listenOnce = React.useCallback(() => {
    if (!SpeechRecognition) return // guarded by startVoice
    // Retire any previous recognizer before starting a fresh session, so the
    // mic is never live twice (stale onend restarts used to cause this).
    try { recognitionRef.current?.abort() } catch { /* noop */ }

    const session = ++voiceSessionRef.current
    const rec = new SpeechRecognition()
    recognitionRef.current = rec
    // Tanglish speech recognition: 'en-IN' (Indian English) transcribes Tanglish
    // speech into English letters. Pure Tamil script uses 'ta-IN'.
    const lastMsg = [...messages].reverse().find((m) => m.role === 'user')?.content || ''
    rec.lang = TAMIL_SCRIPT.test(lastMsg) ? 'ta-IN' : 'en-IN'
    rec.interimResults = true
    rec.continuous = false
    rec.maxAlternatives = 1

    rec.onresult = (event) => {
      if (session !== voiceSessionRef.current) return // stale session
      if (voiceSendingRef.current) return // a send is already in flight
      let interim = ''
      let final = ''
      for (const result of event.results) {
        if (result.isFinal) final += result[0].transcript
        else interim += result[0].transcript
      }
      setLiveTranscript(final || interim)
      if (final) {
        voiceSendingRef.current = true
        setVoiceLog((l) => [...l, { who: 'me', text: final }])
        setVoiceState('processing')
        const done = () => {
          voiceSendingRef.current = false
          // After the reply, listen again for a natural loop — but only while
          // this session is still the current one.
          if (!stopVoiceRef.current && session === voiceSessionRef.current) {
            setTimeout(() => listenOnce(), 400)
          }
        }
        send(final, { fromVoice: true }).then(done, done)
      }
    }
    rec.onerror = (event) => {
      if (session !== voiceSessionRef.current) return // stale session
      if (event.error === 'no-speech') {
        setLiveTranscript("I didn't catch that — please speak again.")
        if (!stopVoiceRef.current) setTimeout(() => listenOnce(), 300)
        return
      }
      if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
        setMicBlocked(true)
        setError('Microphone access was denied. Allow the microphone in your browser settings to use voice mode.')
        setVoiceState('idle')
        return
      }
      if (event.error === 'aborted') return // deliberate stop — no retry
      // other errors: retry gently
      if (!stopVoiceRef.current) setTimeout(() => listenOnce(), 400)
    }
    rec.onend = () => {
      if (session !== voiceSessionRef.current) return // stale session
      if (stopVoiceRef.current || voiceSendingRef.current) return
      // Recognition ended on its own (e.g. silence) — resume with a FRESH
      // recognizer instead of restarting this one (avoids double sessions).
      setTimeout(() => {
        if (session === voiceSessionRef.current && !voiceSendingRef.current && !stopVoiceRef.current) {
          listenOnce()
        }
      }, 250)
    }

    try {
      stopVoiceRef.current = false
      setVoiceState('listening')
      setLiveTranscript('')
      rec.start()
    } catch {
      setVoiceState('idle')
    }
  }, [messages, send])

  const startVoice = () => {
    if (!SpeechRecognition) {
      setError('Speech recognition is not supported in this browser. Try Chrome or Edge, or keep typing.')
      return
    }
    unlockAudio()
    setMicBlocked(false)
    setVoiceMode(true)
    setVoiceLog([])
    setError(null)
    listenOnce()
  }

  const endVoice = () => {
    stopVoice()
    setVoiceMode(false)
  }

  /* Stop just the speech, keep the conversation going (voice-mode Stop). */
  const stopSpeaking = () => {
    stopActivePlayback()
    if (window.speechSynthesis) window.speechSynthesis.cancel()
    setSpeakingKey(null)
    if (voiceMode) setVoiceState('idle')
  }

  /* Replay the most recent voice reply (server audio when we have it). */
  const replayLastReply = async () => {
    const last = lastReplyRef.current
    if (!last) return
    stopActivePlayback()
    if (window.speechSynthesis) window.speechSynthesis.cancel()
    unlockAudio()
    setVoiceState('speaking')
    let played = false
    if (last.base64) {
      played = await playBase64Audio(last.base64, last.format)
    }
    if (!played) {
      const cleanText = cleanSpeechText(last.text)
      if (cleanText) {
        const lang = pickTtsLanguage(cleanText)
        played = await playBackendAudio(cleanText, lang, pickTtsVoice(cleanText))
        if (!played && window.speechSynthesis) {
          try {
            window.speechSynthesis.cancel()
            const utterance = new SpeechSynthesisUtterance(cleanText)
            utterance.lang = lang
            await new Promise((resolve) => {
              utterance.onend = () => resolve(true)
              utterance.onerror = () => resolve(false)
              window.speechSynthesis.speak(utterance)
            })
          } catch { /* noop */ }
        }
      }
    }
    setVoiceState('idle')
  }

  /* Escape closes the voice overlay (keyboard accessibility). */
  React.useEffect(() => {
    if (!voiceMode) return
    const onKey = (e) => {
      if (e.key === 'Escape') endVoice()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [voiceMode]) // eslint-disable-line react-hooks/exhaustive-deps

  /* -------- textarea auto-grow -------- */
  const resizeComposer = (el) => {
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 150)}px`
  }

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

  /* -------- render -------- */
  const currentConv = conversations.find((c) => c.id === conversationId)
  const sendDisabled = typing || !input.trim() || !online

  return (
    <>
      <div className="chat-shell">
        {/* Mobile: dim background behind the conversation drawer */}
        {sideOpen && (
          <div className="side-backdrop" onClick={() => setSideOpen(false)} aria-hidden="true" />
        )}

        {/* Sidebar: conversation list (off-canvas drawer on mobile) */}
        <aside className={`chat-side${sideOpen ? ' open' : ''}`} aria-label="Your conversations">
          <button className="btn btn-dark btn-sm btn-block" onClick={newChat}>
            + New conversation
          </button>
          <div className="side-label">Your conversations</div>
          {conversations.length === 0 && (
            <div className="side-empty">
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
              <Link to="/login?next=/history">Sign In</Link>
            </div>
          )}
        </aside>

        {/* Main column */}
        <main className="chat-main">
          <header className="chat-head">
            <div className="who">
              <div className="avatar" aria-hidden="true">
                LY
                <i className={`lyk-dot ${backendUp === true ? 'on' : backendUp === false ? 'off' : ''}`} />
              </div>
              <div>
                <b>LykAI</b>
                <span>
                  AI Property Concierge · Lyka Realty
                  {currentConv
                    ? ` · #${currentConv.id} · ${currentConv.message_count ?? messages.length} messages`
                    : ''}
                </span>
                {backendUp !== null && (
                  <em className={`lyk-live ${backendUp ? 'on' : 'off'}`}>
                    {backendUp ? 'Online' : 'Reconnecting…'}
                  </em>
                )}
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
              <button
                className={`icon-btn ${voiceMode ? 'active' : ''}`}
                title={voiceMode ? 'End voice mode' : 'Start voice mode'}
                aria-label={voiceMode ? 'End voice mode' : 'Start voice mode'}
                aria-pressed={voiceMode}
                onClick={() => (voiceMode ? endVoice() : startVoice())}
              >
                {voiceMode ? '📵' : '🎙️'}
              </button>
              <button className="icon-btn" title="New chat" aria-label="Start a new chat" onClick={newChat}>
                ✏️
              </button>
            </div>
          </header>

          {/* Connection banners — only shown when actually true */}
          {(!online || backendUp === false) && (
            <div className={`lyk-banner warn ${!online ? 'offline' : ''}`} role="status">
              {!online
                ? 'You appear to be offline — messages will fail until your connection returns.'
                : 'Reconnecting to LykAI… you can keep typing; sending may fail briefly.'}
            </div>
          )}
          {error && (
            <div className="lyk-banner error" role="alert">
              <span>⚠️ {error}</span>
              <button className="lyk-banner__x" aria-label="Dismiss message" onClick={() => setError(null)}>
                ✕
              </button>
            </div>
          )}

          {/* Messages */}
          <div className="chat-scroll" ref={scrollRef} role="log" aria-live="polite" aria-label="Conversation with LykAI">
            {messages.length === 0 && !typing && (
              <div className="empty lyk-empty">
                <div className="avatar lyk-empty__avatar" aria-hidden="true">LY</div>
                <b className="lyk-empty__title">
                  Vanakkam! I’m LykAI, your AI Property Concierge from Lyka Realty.
                </b>
                <p className="lyk-empty__sub">
                  Dubai-la enna maadhiri property thedureenga? Sollunga — unga budget and
                  requirements-ku match aagura super properties thedi tharen!
                </p>
                <div className="suggestions lyk-suggestions">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} className="suggestion" onClick={() => send(s)} disabled={typing}>
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m, i) => (
              <div key={i} className={`msg ${m.role}`}>
                <div className="avatar msg-avatar" aria-hidden="true">
                  {m.role === 'user' ? 'You' : 'LY'}
                </div>
                <div className="msg-body">
                  <div className="bubble">{m.content}</div>
                  {/* Property cards belong to this reply — part of the answer */}
                  {m.properties?.length > 0 && (
                    <div className="msg-cards">
                      {m.properties.map((p, j) => (
                        <PropertyCard
                          key={`${p.property_id ?? p.property_record_id ?? 'x'}-${j}`}
                          index={j + 1}
                          prop={p}
                          onOpen={openProperty}
                        />
                      ))}
                    </div>
                  )}
                  <div className="meta">
                    {m.language && m.language !== 'en' && (
                      <span className="meta-lang">{LANG_LABEL[m.language] || m.language}</span>
                    )}
                    {m.at && <span>{fmtTime(m.at)}</span>}
                    {m.role === 'assistant' && (
                      <button
                        type="button"
                        className={`voice-play-btn ${speakingKey === `m-${i}` ? 'playing' : ''}`}
                        title={speakingKey === `m-${i}` ? 'Stop playback' : 'Listen to this reply'}
                        aria-label={speakingKey === `m-${i}` ? 'Stop audio playback' : 'Listen to this reply'}
                        onClick={() => speakMessage(m.content, `m-${i}`)}
                      >
                        {speakingKey === `m-${i}` ? '◼ Stop' : '🔊 Listen'}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}

            {typing && (
              <div className="msg assistant">
                <div className="avatar msg-avatar" aria-hidden="true">LY</div>
                <div className="bubble typing-bubble">
                  <span className="typing" aria-hidden="true"><i /><i /><i /></span>
                  <span className="typing-label">LykAI is thinking…</span>
                </div>
              </div>
            )}
          </div>

          {/* Suggestions (visible once a conversation has started) */}
          {messages.length > 0 && messages.length < 3 && (
            <div className="suggestions lyk-suggestions">
              {SUGGESTIONS.slice(0, 3).map((s) => (
                <button key={s} className="suggestion" onClick={() => send(s)} disabled={typing}>
                  {s}
                </button>
              ))}
            </div>
          )}

          {/* Listing in focus (came from its details page): one-tap follow-up */}
          {focus && (
            <div className="ref-chip">
              <span className="ref-chip__info">
                {focus.property_type || 'Property'}
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
              <textarea
                ref={inputRef}
                rows={1}
                value={input}
                placeholder="Ask about properties…"
                aria-label="Message LykAI"
                onChange={(e) => {
                  setInput(e.target.value)
                  resizeComposer(e.target)
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    if (!sendDisabled) send(input)
                  }
                }}
                disabled={typing}
              />
              <button
                className={`icon-btn ${voiceState === 'listening' ? 'recording' : ''}`}
                title={SpeechRecognition ? 'Voice mode' : 'Voice mode unavailable in this browser'}
                aria-label={voiceMode ? 'End voice mode' : 'Start voice mode'}
                onClick={() => (voiceMode ? endVoice() : startVoice())}
                disabled={typing || !SpeechRecognition}
              >
                {voiceState === 'listening' ? '⏹' : '🎤'}
              </button>
              <button
                className="icon-btn send-btn"
                title="Send message"
                aria-label="Send message"
                onClick={() => send(input)}
                disabled={sendDisabled}
              >
                ➤
              </button>
            </div>
            {liveTranscript && voiceMode && (
              <div className="transcript" aria-live="polite">You: {liveTranscript}</div>
            )}
          </div>
        </main>
      </div>

      {/* Voice overlay */}
      {voiceMode && (
        <div className="voice-stage lyk-voice" role="dialog" aria-modal="true" aria-label="LykAI voice mode">
          <button className="lyk-voice__close" aria-label="End voice mode" onClick={endVoice}>
            ✕
          </button>

          <div className="voice-status" aria-live="polite">
            {voiceState === 'listening' && 'Listening… speak in Tanglish or English'}
            {voiceState === 'processing' && 'Thinking…'}
            {voiceState === 'speaking' && 'Speaking…'}
            {voiceState === 'idle' && (micBlocked ? 'Microphone blocked' : 'Voice mode ready')}
          </div>

          <div className="lyk-orb-wrap">
            <div
              className={`voice-orb ${voiceState === 'listening' ? 'listening' : voiceState === 'speaking' ? 'speaking' : ''}`}
              aria-hidden="true"
            >
              {voiceState === 'speaking' ? '🔊' : voiceState === 'processing' ? '🧠' : '🎙️'}
            </div>
            {/* Waveform — only while actually listening or speaking */}
            {(voiceState === 'listening' || voiceState === 'speaking') && (
              <div className="lyk-wave" aria-hidden="true">
                <i /><i /><i /><i /><i /><i /><i />
              </div>
            )}
          </div>

          <div className="voice-transcript-live" aria-live="polite">
            {liveTranscript ||
              (voiceState === 'listening'
                ? 'Go ahead — I’m listening…'
                : voiceState === 'processing'
                  ? 'One moment…'
                  : '…')}
          </div>

          {micBlocked && (
            <div className="lyk-voice__notice" role="alert">
              <b>Microphone access was denied.</b>
              <span>
                Open your browser’s site settings (the icon near the address bar), allow the
                microphone for this site, then try again — or keep typing instead.
              </span>
              <button
                className="voice-btn"
                onClick={() => { setMicBlocked(false); setError(null); listenOnce() }}
              >
                Try listening again
              </button>
            </div>
          )}

          {!SpeechRecognition && (
            <div className="lyk-voice__notice" role="alert">
              <b>Speech recognition isn’t supported in this browser.</b>
              <span>Use Chrome or Edge for voice input — or keep typing. Replies can still be read aloud.</span>
            </div>
          )}

          <div className="voice-log" role="log" aria-label="Voice conversation log">
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
                setMuted((mo) => !mo)
                if (!muted) stopSpeaking()
              }}
              aria-pressed={muted}
            >
              {muted ? '🔇 Unmute replies' : '🔊 Mute replies'}
            </button>
            {voiceState === 'speaking' && (
              <button className="voice-btn danger" onClick={stopSpeaking}>
                ⏹ Stop speaking
              </button>
            )}
            {hasLastReply && voiceState !== 'speaking' && (
              <button className="voice-btn" onClick={replayLastReply}>
                🔁 Replay last reply
              </button>
            )}
            <button
              className="voice-btn"
              onClick={() => {
                stopVoice()
                setTimeout(listenOnce, 300)
              }}
              disabled={!SpeechRecognition || micBlocked}
            >
              ↻ Restart listening
            </button>
            <button className="voice-btn gold" onClick={endVoice}>
              Done — back to text
            </button>
          </div>

          <p className="voice-hint">
            Speak casually in Tanglish or English — e.g. “Dubai Marina-la 2 BHK apartment venum,
            rent 85,000 AED”. Press Escape or “Done” to return to text chat.
          </p>
        </div>
      )}
    </>
  )
}
