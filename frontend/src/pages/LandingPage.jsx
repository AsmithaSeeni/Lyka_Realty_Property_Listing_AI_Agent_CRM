import React from 'react'
import { Link, useNavigate } from 'react-router-dom'

const SERVICES = [
  {
    ic: '🎙️',
    gold: true,
    title: 'Talk to LykAI',
    body: 'Tell LykAI what you want — it asks one question at a time, searches our listings and shares matching property cards in the chat. English, Tamil or Tanglish.',
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
    body: 'Rental yield and ROI guidance with an assistant that remembers your goals across every conversation.',
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

const LANGUAGES = [
  { b: 'English', s: '“I need a 3-bed apartment in Downtown under 4 million.”' },
  { b: 'தமிழ் · Tamil', s: '“துபாயில் வில்லா வேணும், பட்ஜெட் 5 மில்லியன்.”' },
  { b: 'Tanglish', s: '“2 bedroom villa ah Dubai Marina-la kaaminga.”' },
]

export default function LandingPage() {
  const navigate = useNavigate()

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
              time and walks you to the right property. Voice or text, anytime.
            </p>

            <div className="hero-cta">
              <button className="btn gold" onClick={() => navigate('/chat')}>
                <span className="ico">→</span> Talk to LykAI
              </button>
              <button className="btn light" onClick={() => navigate('/properties')}>
                Explore Properties
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* ============ SERVICES ============ */}
      <section className="section soft">
        <div className="section-title">
          <span className="eyebrow center">What we do</span>
          <h2>Everything a great property agency does</h2>
          <p>
            Lyka Realty pairs hands-on Dubai market expertise with AI-assisted
            property search — so finding the right place moves at your pace.
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
              helps you decide.
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
