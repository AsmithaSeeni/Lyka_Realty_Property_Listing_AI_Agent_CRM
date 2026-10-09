import React from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../api.js'

const STATS = [
  { n: '300+', l: 'Clients served' },
  { n: '25,082', l: 'UAE listings' },
  { n: '10', l: 'Communities covered' },
  { n: '3', l: 'Languages supported' },
]

const SERVICES = [
  {
    ic: '🎙️',
    gold: true,
    title: 'Talk to LykAI',
    body: 'Tell LykAI what you want — it asks one question at a time, searches the full listing dataset and shares matching property cards in the chat. English, Tamil or Tanglish.',
  },
  {
    ic: '🏡',
    title: 'Buy property in Dubai',
    body: 'Off-plan and ready homes matched to your budget — LykAI finds them for you while you chat.',
  },
  {
    ic: '🔑',
    title: 'Rent property in Dubai',
    body: 'Short and long-term rentals across Dubai and the Northern Emirates — filtered by bedrooms, area and price.',
  },
  {
    ic: '📈',
    title: 'Investment advisory',
    body: 'Rental yield and ROI guidance with a consultant that remembers your goals across every conversation.',
  },
]

const COMMUNITIES = [
  'Dubai Marina',
  'Downtown Dubai',
  'Palm Jumeirah',
  'Jumeirah Village Circle',
  'Business Bay',
  'Dubai Hills Estate',
  'Dubai Creek Harbour',
  'Dubai Islands',
  'JLT',
  'Arabian Ranches',
]

const AI_FEATURES = [
  {
    ic: '🗣️',
    title: 'Multilingual by design',
    body: 'English, Tamil and Tanglish detected per message — the agent replies in the same language and style you use.',
  },
  {
    ic: '🧠',
    title: 'It remembers you',
    body: 'Budget, location, bedrooms and your contact details persist across the whole chat — and across visits.',
  },
  {
    ic: '⚖️',
    title: 'Never invents a thing',
    body: 'Every recommendation is pulled from the live listing dataset by deterministic search, not guessed by a language model.',
  },
  {
    ic: '💬',
    title: 'Natural follow-ups',
    body: '“Show me cheaper ones”, “what about 3 beds?” — the agent applies your new filter on top of what it already knows.',
  },
  {
    ic: '🎯',
    title: 'Lead capture, naturally',
    body: 'When you share a name and number, a structured CRM lead is created automatically — no forms to fill.',
  },
  {
    ic: '📂',
    title: 'Full conversation history',
    body: 'Every message is stored with timestamps and language. Reopen any chat and it continues with the same context.',
  },
]

const LANGUAGES = [
  { b: 'English', s: '“I need a 3-bed apartment in Downtown under 4 million.”' },
  { b: 'தமிழ் · Tamil', s: '“துபாயில் வில்லா வேணும், பட்ஜெட் 5 மில்லியன்.”' },
  { b: 'Tanglish', s: '“2 bedroom villa ah Dubai Marina-la kaaminga.”' },
]

export default function LandingPage() {
  const navigate = useNavigate()
  const [health, setHealth] = React.useState(null)

  React.useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ status: 'offline' }))
  }, [])

  return (
    <>
      {/* ============ HERO ============ */}
      <section className="hero">
        <div className="hero__bg" aria-hidden="true" />
        <div className="hero-inner">
          <div>
            <span className="eyebrow">Dubai Real Estate · Est. 2024</span>
            <h1>
              Buy, rent &amp; lease property in Dubai —{' '}
              <em>just tell LykAI what you need.</em>
            </h1>
            <p className="lead">
              Describe what you want — location, budget, bedrooms — in English, Tamil
              or Tanglish. LykAI, your AI property concierge, asks one question at a
              time, searches 25,000+ listings and walks you to the right property.
              Voice or text, anytime.
            </p>

            <div className="hero-cta">
              <button className="btn gold" onClick={() => navigate('/chat')}>
                <span className="ico">→</span> Talk to LykAI
              </button>
              <button className="btn light" onClick={() => navigate('/properties')}>
                Explore Properties
              </button>
            </div>

            <div className="trustchip">
              <span className="stars">★★★★★</span>
              <span>Trusted by 300+ clients across Dubai</span>
            </div>

            <div className="hero-stats">
              {STATS.map((s) => (
                <div className="stat" key={s.l}>
                  <div className="n">{s.n}</div>
                  <div className="l">{s.l}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Live preview card */}
          <aside className="hero-card">
            <h3>Live preview</h3>
            <div className="sub">How a typical conversation flows</div>
            <div className="hero-mini-msg user">
              Hi, I need a villa in Dubai, budget 5 million
            </div>
            <div className="hero-mini-msg agent">
              Great choice! Are you looking to <b>buy or rent</b>?
            </div>
            <div className="hero-mini-msg user">Buying. 4 bedrooms.</div>
            <div className="hero-mini-msg agent">
              I found <b>20 matching villas</b> — here are the top picks:
            </div>
            <div className="hero-mini-msg agent" style={{ fontSize: 13 }}>
              🏡 4 Bed Villa · DAMAC Hills 2 · <b>AED 10,70,000</b>
              <br />4 baths · 1,208 sqft
            </div>
            <button
              className="btn gold btn-block"
              style={{ marginTop: 16 }}
              onClick={() => navigate('/chat')}
            >
              <span className="ico">→</span> Talk to LykAI
            </button>
            <div
              className="sub"
              style={{
                marginTop: 12,
                textAlign: 'center',
                color: health?.status === 'healthy' ? 'var(--gold-soft)' : '#fffcf58c',
              }}
            >
              {health?.status === 'healthy'
                ? '● LykAI is online — live property search'
                : '○ LykAI is offline — please try again soon'}
            </div>
          </aside>
        </div>
      </section>

      {/* ============ SERVICES ============ */}
      <section className="section soft">
        <div className="section-title">
          <span className="eyebrow center">What we do</span>
          <h2>Everything a great property agency does — instantly</h2>
          <p>
            Lyka Realty combines hands-on Dubai market expertise with an AI desk that
            never sleeps, so your search moves at your pace.
          </p>
        </div>
        <div className="features">
          {SERVICES.map((f) => (
            <article className="feature" key={f.title}>
              <div className={`ico${f.gold ? ' gold' : ''}`}>{f.ic}</div>
              <h3>{f.title}</h3>
              <p>{f.body}</p>
            </article>
          ))}
        </div>
      </section>

      {/* ============ COMMUNITIES ============ */}
      <section className="section cream">
        <div className="section-title">
          <span className="eyebrow center">Where we work</span>
          <h2>Communities we cover</h2>
          <p>Ask LykAI about any of these — plus every other corner of the UAE.</p>
        </div>
        <div className="communities">
          {COMMUNITIES.map((c) => (
            <Link
              key={c}
              to="/chat"
              className="pill"
              style={{ justifyContent: 'center', padding: '12px 18px' }}
            >
              <span className="dot" />
              {c}
            </Link>
          ))}
        </div>
      </section>

      {/* ============ AI CAPABILITIES (on maroon) ============ */}
      <section className="section on-maroon">
        <div className="section-title">
          <span className="eyebrow center">The LykAI difference</span>
          <h2>A consultant that remembers every word</h2>
          <p>
            Built like a production real-estate desk: deterministic search,
            conversation memory, lead capture and a full CRM behind every chat.
          </p>
        </div>
        <div className="features">
          {AI_FEATURES.map((f) => (
            <article className="card" key={f.title}>
              <div className="ic">{f.ic}</div>
              <h3>{f.title}</h3>
              <p>{f.body}</p>
            </article>
          ))}
        </div>
      </section>

      {/* ============ LANGUAGES ============ */}
      <section className="section soft">
        <div className="section-title">
          <span className="eyebrow center">Speak your language</span>
          <h2>English · Tamil · Tanglish</h2>
          <p>
            The agent detects the language and style of every message — and matches
            it naturally.
          </p>
        </div>
        <div className="lang-strip">
          {LANGUAGES.map((l) => (
            <div className="lang-chip" key={l.b}>
              <b>{l.b}</b>
              <span>{l.s}</span>
            </div>
          ))}
        </div>
      </section>

      {/* ============ CTA ============ */}
      <section className="section cream">
        <div className="container">
          <div className="cta-card">
            <span className="eyebrow center">Ready when you are</span>
            <h2>Tell LykAI what you’re looking for.</h2>
            <p>
              One conversation — LykAI understands, finds matching properties and
              helps you decide. No pressure, no confusion.
            </p>
            <div
              style={{
                display: 'flex',
                gap: 14,
                justifyContent: 'center',
                flexWrap: 'wrap',
              }}
            >
              <button className="btn gold" onClick={() => navigate('/chat')}>
                <span className="ico">→</span> Talk to LykAI
              </button>
              <a
                className="btn light"
                href="https://wa.me/971523485758"
                target="_blank"
                rel="noreferrer"
              >
                WhatsApp us
              </a>
            </div>
          </div>
        </div>
      </section>
    </>
  )
}
