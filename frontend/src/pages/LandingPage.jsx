import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'

const COMMUNITIES = [
  {
    name: 'Dubai Marina',
    badge: 'Waterfront & High Yield',
    roi: '7.6% Gross ROI',
    startPrice: 'From AED 1,450,000',
    type: 'High-rise waterfront residences with direct yacht club and beach access.',
    img: 'https://images.unsplash.com/photo-1512453979798-5ea266f8880c?auto=format&fit=crop&w=800&q=80',
  },
  {
    name: 'Downtown Dubai',
    badge: 'Iconic Luxury Living',
    roi: '6.8% Gross ROI',
    startPrice: 'From AED 2,100,000',
    type: 'Residences adjacent to Burj Khalifa, Dubai Mall and the Dubai Opera.',
    img: 'https://images.unsplash.com/photo-1580674684081-7617fbf3d745?auto=format&fit=crop&w=800&q=80',
  },
  {
    name: 'Palm Jumeirah',
    badge: 'Ultra-Prime Beachfront',
    roi: '6.4% Gross ROI',
    startPrice: 'From AED 4,750,000',
    type: 'Private beachfront villas, branded residences and panoramic penthouses.',
    img: 'https://images.unsplash.com/photo-1546412414-e1885259563a?auto=format&fit=crop&w=800&q=80',
  },
  {
    name: 'Dubai Hills Estate',
    badge: 'Golf Community & Greenery',
    roi: '7.1% Gross ROI',
    startPrice: 'From AED 1,850,000',
    type: 'Championship 18-hole golf course, expansive parks & King’s College Hospital.',
    img: 'https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=800&q=80',
  },
  {
    name: 'Business Bay',
    badge: 'High Rental Demand',
    roi: '8.2% Gross ROI',
    startPrice: 'From AED 1,200,000',
    type: 'Dubai Canal waterfront living, bustling commercial towers and boutique apartments.',
    img: 'https://images.unsplash.com/photo-1526495124232-a04e1849168c?auto=format&fit=crop&w=800&q=80',
  },
  {
    name: 'Dubai Creek Harbour',
    badge: 'The Next Downtown',
    roi: '7.8% Gross ROI',
    startPrice: 'From AED 1,550,000',
    type: 'Emaar waterfront masterplan overlooking the Ras Al Khor sanctuary and Dubai skyline.',
    img: 'https://images.unsplash.com/photo-1578683010236-d716f9a3f461?auto=format&fit=crop&w=800&q=80',
  },
]

const PILLARS = [
  {
    num: '01',
    title: 'RERA Certified & Regulated',
    desc: 'Fully licensed brokerage under the Dubai Land Department (DLD). Every transaction adheres to Law No. 8 escrow mandates.',
    ico: '🏛️',
  },
  {
    num: '02',
    title: 'Zero Brokerage on Off-Plan',
    desc: 'Direct developer pricing from Emaar, Sobha, Damac, Nakheel, and Ellington with zero buyer agency fees.',
    ico: '💎',
  },
  {
    num: '03',
    title: '10-Year UAE Golden Visa',
    desc: 'Turnkey investor residency processing for qualifying property acquisitions of AED 2,000,000 or greater.',
    ico: '🛂',
  },
  {
    num: '04',
    title: 'Global NRI & Remote Purchase',
    desc: 'Seamless remote transactions for overseas buyers: RBI LRS compliance, POA representation, and digital DLD title transfers.',
    ico: '🌐',
  },
]

const SAMPLE_QUESTIONS = [
  '“Dubai Marina-la 2 BHK apartment under 2 Million AED venum.”',
  '“Show me off-plan villas with 80/20 post-handover payment plans.”',
  '“What are the DLD transfer fees and escrow account rules in Dubai?”',
  '“Can an NRI purchase a villa in Palm Jumeirah remotely from India?”',
]

export default function LandingPage() {
  const navigate = useNavigate()
  const [purpose, setPurpose] = useState('buy')
  const [community, setCommunity] = useState('')
  const [propType, setPropType] = useState('')
  const [budget, setBudget] = useState('')

  const handleQuickSearch = (e) => {
    e.preventDefault()
    const queryParts = []
    if (community) queryParts.push(community)
    if (propType) queryParts.push(propType)
    if (purpose === 'buy') queryParts.push('for sale')
    else if (purpose === 'rent') queryParts.push('for rent')
    else if (purpose === 'offplan') queryParts.push('off-plan')
    if (budget) queryParts.push(`budget ${budget}`)

    const searchStr = queryParts.join(' ')
    navigate(`/properties${searchStr ? `?search=${encodeURIComponent(searchStr)}` : ''}`)
  }

  return (
    <div style={{ background: '#faf9f6', color: '#0f172a', minHeight: '100vh', fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif" }}>
      {/* ============ HERO SECTION ============ */}
      <section
        style={{
          position: 'relative',
          minHeight: '82vh',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          padding: '120px 24px 70px',
          background: 'radial-gradient(1100px 650px at 80% 12%, rgba(232, 189, 104, 0.22), transparent 70%), radial-gradient(800px 500px at 15% 85%, rgba(68, 16, 47, 0.45), transparent 70%), linear-gradient(160deg, #1f0514 0%, #350c25 50%, #15030e 100%)',
          color: '#ffffff',
          overflow: 'hidden',
        }}
      >
        {/* Subtle Luxury Geometry Overlay */}
        <div
          style={{
            position: 'absolute',
            inset: 0,
            backgroundImage: 'linear-gradient(rgba(232, 189, 104, 0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(232, 189, 104, 0.04) 1px, transparent 1px)',
            backgroundSize: '54px 54px',
            pointerEvents: 'none',
          }}
        />

        <div style={{ maxWidth: 1180, margin: '0 auto', width: '100%', position: 'relative', zIndex: 2 }}>
          {/* Top Trust Badge */}
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
              padding: '6px 14px',
              borderRadius: 30,
              background: 'rgba(232, 189, 104, 0.15)',
              border: '1px solid rgba(232, 189, 104, 0.38)',
              color: '#f6dfa9',
              fontSize: 12,
              fontWeight: 700,
              letterSpacing: '0.07em',
              textTransform: 'uppercase',
              marginBottom: 22,
            }}
          >
            <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: '#22c55e', boxShadow: '0 0 8px #22c55e' }} />
            Dubai Land Department (DLD) &amp; RERA Licensed Brokerage #31289
          </div>

          {/* Hero Main Heading with Explicit White Typography */}
          <h1
            style={{
              fontSize: 'clamp(2.5rem, 5.2vw, 4.3rem)',
              fontFamily: "'Playfair Display', Georgia, serif",
              lineHeight: 1.12,
              fontWeight: 700,
              margin: '0 0 20px',
              maxWidth: 950,
              letterSpacing: '-0.02em',
              color: '#ffffff',
            }}
          >
            Find Your Signature Residence in Dubai.{' '}
            <span style={{ color: '#f5d38a', fontStyle: 'italic', fontWeight: 400, display: 'block', marginTop: 4 }}>
              &amp; AI Property Advisory.
            </span>
          </h1>

          {/* Hero Subtitle */}
          <p
            style={{
              fontSize: 'clamp(1.05rem, 1.8vw, 1.25rem)',
              lineHeight: 1.65,
              color: '#f1f5f9',
              maxWidth: 720,
              margin: '0 0 34px',
              fontWeight: 300,
            }}
          >
            Access over 25,000 verified freehold residences, luxury off-plan launches, and high-yield investment properties across Dubai. Speak with licensed Dubai advisors or our conversational concierge in English, தமிழ், or Tanglish.
          </p>

          {/* Unified Luxury Property Search Bar */}
          <form
            onSubmit={handleQuickSearch}
            style={{
              background: 'rgba(255, 255, 255, 0.98)',
              borderRadius: 16,
              padding: '14px 18px',
              boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)',
              display: 'flex',
              flexWrap: 'wrap',
              gap: 12,
              alignItems: 'center',
              maxWidth: 1040,
              border: '1px solid rgba(232, 189, 104, 0.4)',
            }}
          >
            {/* Purpose tabs */}
            <div style={{ display: 'flex', background: '#f1f5f9', borderRadius: 10, padding: 4 }}>
              {[
                { k: 'buy', l: 'Buy' },
                { k: 'rent', l: 'Rent' },
                { k: 'offplan', l: 'Off-Plan' },
              ].map((t) => (
                <button
                  type="button"
                  key={t.k}
                  onClick={() => setPurpose(t.k)}
                  style={{
                    padding: '8px 18px',
                    borderRadius: 8,
                    border: 'none',
                    fontWeight: 700,
                    fontSize: 13,
                    cursor: 'pointer',
                    background: purpose === t.k ? '#3b0a27' : 'transparent',
                    color: purpose === t.k ? '#f5d38a' : '#475569',
                    transition: 'all 0.15s ease',
                  }}
                >
                  {t.l}
                </button>
              ))}
            </div>

            {/* Community selector */}
            <select
              value={community}
              onChange={(e) => setCommunity(e.target.value)}
              style={{
                flex: 1,
                minWidth: 170,
                padding: '10px 14px',
                borderRadius: 8,
                border: '1px solid #cbd5e1',
                background: '#ffffff',
                fontSize: 13.5,
                color: '#0f172a',
                fontWeight: 600,
                outline: 'none',
              }}
            >
              <option value="">All Prime Communities</option>
              <option value="Dubai Marina">Dubai Marina</option>
              <option value="Downtown Dubai">Downtown Dubai</option>
              <option value="Palm Jumeirah">Palm Jumeirah</option>
              <option value="Business Bay">Business Bay</option>
              <option value="Dubai Hills Estate">Dubai Hills Estate</option>
              <option value="Dubai Creek Harbour">Dubai Creek Harbour</option>
              <option value="Jumeirah Village Circle">Jumeirah Village Circle (JVC)</option>
              <option value="Emaar Beachfront">Emaar Beachfront</option>
            </select>

            {/* Property Type selector */}
            <select
              value={propType}
              onChange={(e) => setPropType(e.target.value)}
              style={{
                flex: 1,
                minWidth: 140,
                padding: '10px 14px',
                borderRadius: 8,
                border: '1px solid #cbd5e1',
                background: '#ffffff',
                fontSize: 13.5,
                color: '#0f172a',
                fontWeight: 600,
                outline: 'none',
              }}
            >
              <option value="">All Types</option>
              <option value="Apartment">Apartment</option>
              <option value="Villa">Villa</option>
              <option value="Penthouse">Penthouse</option>
              <option value="Townhouse">Townhouse</option>
            </select>

            {/* Budget selector */}
            <select
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
              style={{
                flex: 1,
                minWidth: 160,
                padding: '10px 14px',
                borderRadius: 8,
                border: '1px solid #cbd5e1',
                background: '#ffffff',
                fontSize: 13.5,
                color: '#0f172a',
                fontWeight: 600,
                outline: 'none',
              }}
            >
              <option value="">Budget (AED)</option>
              <option value="1500000">Up to AED 1.5M</option>
              <option value="2000000">AED 2.0M (Golden Visa)</option>
              <option value="3500000">AED 2M – 3.5M</option>
              <option value="6000000">AED 3.5M – 6M</option>
              <option value="10000000">Ultra-Luxury (AED 10M+)</option>
            </select>

            {/* Search Submit Button */}
            <button
              type="submit"
              style={{
                padding: '11px 24px',
                borderRadius: 8,
                background: 'linear-gradient(135deg, #e8bd68 0%, #c59733 100%)',
                color: '#2b081c',
                border: 'none',
                fontWeight: 800,
                fontSize: 14,
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 8,
                boxShadow: '0 4px 14px rgba(232, 189, 104, 0.4)',
              }}
            >
              <span>Explore Listings</span>
              <span style={{ fontSize: 16 }}>→</span>
            </button>
          </form>

          {/* Quick Voice Prompt Pill */}
          <div style={{ marginTop: 26, display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
            <button
              onClick={() => navigate('/chat')}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 10,
                padding: '10px 22px',
                borderRadius: 30,
                background: 'rgba(255, 255, 255, 0.1)',
                color: '#ffffff',
                border: '1px solid rgba(232, 189, 104, 0.5)',
                fontWeight: 700,
                fontSize: 13.5,
                cursor: 'pointer',
                backdropFilter: 'blur(8px)',
                transition: 'all 0.2s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'rgba(232, 189, 104, 0.25)'
                e.currentTarget.style.borderColor = '#f5d38a'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'rgba(255, 255, 255, 0.1)'
                e.currentTarget.style.borderColor = 'rgba(232, 189, 104, 0.5)'
              }}
            >
              <span style={{ fontSize: 16 }}>🎙️</span>
              <span>Ask LykAI Voice Concierge</span>
              <span style={{ fontSize: 10, padding: '2px 7px', borderRadius: 10, background: '#22c55e', color: '#ffffff', fontWeight: 800 }}>LIVE</span>
            </button>

            <span style={{ fontSize: 13, color: '#f6dfa9', fontWeight: 500 }}>
              Speak naturally in English, தமிழ் (Tamil), or Tanglish
            </span>
          </div>
        </div>
      </section>

      {/* ============ STATS BAR ============ */}
      <section style={{ background: '#1c0512', color: '#ffffff', borderTop: '1px solid rgba(232,189,104,0.2)', borderBottom: '1px solid rgba(232,189,104,0.15)', padding: '28px 24px' }}>
        <div style={{ maxWidth: 1180, margin: '0 auto', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 24, textAlign: 'center' }}>
          <div>
            <div style={{ fontSize: 32, fontWeight: 700, color: '#f5d38a', fontFamily: "'Playfair Display', serif" }}>AED 1.2B+</div>
            <div style={{ fontSize: 12.5, color: '#e2e8f0', marginTop: 4, textTransform: 'uppercase', letterSpacing: '0.07em', fontWeight: 600 }}>Transactions Closed</div>
          </div>
          <div>
            <div style={{ fontSize: 32, fontWeight: 700, color: '#f5d38a', fontFamily: "'Playfair Display', serif" }}>25,125</div>
            <div style={{ fontSize: 12.5, color: '#e2e8f0', marginTop: 4, textTransform: 'uppercase', letterSpacing: '0.07em', fontWeight: 600 }}>Verified UAE Listings</div>
          </div>
          <div>
            <div style={{ fontSize: 32, fontWeight: 700, color: '#f5d38a', fontFamily: "'Playfair Display', serif" }}>0% Tax</div>
            <div style={{ fontSize: 12.5, color: '#e2e8f0', marginTop: 4, textTransform: 'uppercase', letterSpacing: '0.07em', fontWeight: 600 }}>Capital Gains &amp; Rental Tax</div>
          </div>
          <div>
            <div style={{ fontSize: 32, fontWeight: 700, color: '#f5d38a', fontFamily: "'Playfair Display', serif" }}>10-Year</div>
            <div style={{ fontSize: 12.5, color: '#e2e8f0', marginTop: 4, textTransform: 'uppercase', letterSpacing: '0.07em', fontWeight: 600 }}>UAE Golden Visa Advisory</div>
          </div>
        </div>
      </section>

      {/* ============ SIGNATURE DUBAI COMMUNITIES ============ */}
      <section style={{ maxWidth: 1180, margin: '0 auto', padding: '80px 24px' }}>
        <div style={{ textAlign: 'center', marginBottom: 50 }}>
          <span style={{ fontSize: 12, fontWeight: 800, letterSpacing: '0.12em', textTransform: 'uppercase', color: '#b45309' }}>
            Exclusive Freehold Portfolio
          </span>
          <h2 style={{ fontSize: 'clamp(2rem, 3.4vw, 2.7rem)', fontFamily: "'Playfair Display', Georgia, serif", margin: '10px 0 14px', color: '#1e1b4b' }}>
            Prime Dubai Neighborhoods
          </h2>
          <p style={{ color: '#475569', maxWidth: 640, margin: '0 auto', fontSize: 15.5, lineHeight: 1.6 }}>
            Handpicked master-developments offering exceptional capital appreciation, high rental yields, and luxury waterfront living.
          </p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(330px, 1fr))', gap: 26 }}>
          {COMMUNITIES.map((c) => (
            <div
              key={c.name}
              style={{
                borderRadius: 16,
                overflow: 'hidden',
                background: '#ffffff',
                border: '1px solid #e2e8f0',
                boxShadow: '0 10px 30px -8px rgba(0, 0, 0, 0.08)',
                transition: 'transform 0.25s ease, box-shadow 0.25s ease',
                display: 'flex',
                flexDirection: 'column',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.transform = 'translateY(-4px)'
                e.currentTarget.style.boxShadow = '0 18px 36px -10px rgba(0, 0, 0, 0.14)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.transform = 'translateY(0)'
                e.currentTarget.style.boxShadow = '0 10px 30px -8px rgba(0, 0, 0, 0.08)'
              }}
            >
              <div style={{ height: 210, position: 'relative', overflow: 'hidden' }}>
                <img
                  src={c.img}
                  alt={c.name}
                  style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                  loading="lazy"
                />
                <div style={{ position: 'absolute', top: 14, right: 14, padding: '4px 10px', borderRadius: 20, background: 'rgba(27, 4, 18, 0.88)', color: '#f5d38a', fontSize: 11, fontWeight: 700, backdropFilter: 'blur(6px)' }}>
                  {c.roi}
                </div>
                <div style={{ position: 'absolute', bottom: 12, left: 14, padding: '4px 10px', borderRadius: 6, background: 'rgba(255,255,255,0.95)', color: '#1e1b4b', fontSize: 11.5, fontWeight: 800 }}>
                  {c.badge}
                </div>
              </div>

              <div style={{ padding: 22, display: 'flex', flexDirection: 'column', flex: 1 }}>
                <h3 style={{ margin: '0 0 6px', fontSize: 20, fontFamily: "'Playfair Display', serif", color: '#0f172a', fontWeight: 700 }}>
                  {c.name}
                </h3>
                <div style={{ fontSize: 14, fontWeight: 800, color: '#b45309', marginBottom: 10 }}>
                  {c.startPrice}
                </div>
                <p style={{ margin: '0 0 20px', color: '#475569', fontSize: 13.5, lineHeight: 1.55, flex: 1 }}>
                  {c.type}
                </p>
                <div style={{ display: 'flex', gap: 10 }}>
                  <button
                    onClick={() => navigate(`/properties?search=${encodeURIComponent(c.name)}`)}
                    style={{
                      flex: 1,
                      padding: '9px 14px',
                      borderRadius: 8,
                      background: '#f8fafc',
                      border: '1px solid #cbd5e1',
                      color: '#0f172a',
                      fontWeight: 700,
                      fontSize: 13,
                      cursor: 'pointer',
                      transition: 'background 0.15s ease',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = '#f1f5f9')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = '#f8fafc')}
                  >
                    View Properties
                  </button>
                  <button
                    onClick={() => navigate(`/chat`)}
                    style={{
                      padding: '9px 16px',
                      borderRadius: 8,
                      background: '#350c25',
                      border: 'none',
                      color: '#f5d38a',
                      fontWeight: 700,
                      fontSize: 13,
                      cursor: 'pointer',
                      transition: 'opacity 0.15s ease',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.opacity = '0.9')}
                    onMouseLeave={(e) => (e.currentTarget.style.opacity = '1')}
                    title="Inquire with LykAI"
                  >
                    Ask LykAI
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ============ WHY LYKA REALTY PILLARS ============ */}
      <section style={{ background: '#ffffff', padding: '80px 24px', borderTop: '1px solid #e2e8f0', borderBottom: '1px solid #e2e8f0' }}>
        <div style={{ maxWidth: 1180, margin: '0 auto' }}>
          <div style={{ textAlign: 'center', marginBottom: 48 }}>
            <span style={{ fontSize: 12, fontWeight: 800, letterSpacing: '0.12em', textTransform: 'uppercase', color: '#b45309' }}>
              Institutional Integrity &amp; Transparency
            </span>
            <h2 style={{ fontSize: 'clamp(2rem, 3.4vw, 2.7rem)', fontFamily: "'Playfair Display', Georgia, serif", margin: '10px 0 14px', color: '#0f172a' }}>
              Why Global Investors Choose Lyka Realty
            </h2>
            <p style={{ color: '#475569', maxWidth: 640, margin: '0 auto', fontSize: 15.5, lineHeight: 1.6 }}>
              Navigating Dubai real estate with regulatory clarity, escrow protection, and specialized international buyer support.
            </p>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 24 }}>
            {PILLARS.map((p) => (
              <div
                key={p.num}
                style={{
                  background: '#f8fafc',
                  padding: 28,
                  borderRadius: 16,
                  border: '1px solid #e2e8f0',
                  boxShadow: '0 4px 12px rgba(0, 0, 0, 0.03)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                  <span style={{ fontSize: 32 }}>{p.ico}</span>
                  <span style={{ fontSize: 14, fontWeight: 800, color: '#b45309', fontFamily: "'Playfair Display', serif" }}>{p.num}</span>
                </div>
                <h3 style={{ margin: '0 0 10px', fontSize: 18, color: '#0f172a', fontWeight: 700 }}>
                  {p.title}
                </h3>
                <p style={{ margin: 0, fontSize: 14, color: '#475569', lineHeight: 1.6 }}>
                  {p.desc}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ============ LYKAI AI CONCIERGE SPOTLIGHT ============ */}
      <section style={{ maxWidth: 1180, margin: '0 auto', padding: '80px 24px' }}>
        <div
          style={{
            background: 'radial-gradient(900px 450px at 90% 10%, rgba(232, 189, 104, 0.28), transparent 70%), linear-gradient(145deg, #350c25 0%, #15030e 100%)',
            borderRadius: 24,
            padding: '50px 40px',
            color: '#ffffff',
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
            gap: 40,
            alignItems: 'center',
            boxShadow: '0 30px 60px -15px rgba(27, 4, 18, 0.4)',
            border: '1px solid rgba(232, 189, 104, 0.3)',
          }}
        >
          <div>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '4px 12px', borderRadius: 20, background: 'rgba(232,189,104,0.18)', color: '#f5d38a', fontSize: 12, fontWeight: 700, textTransform: 'uppercase', marginBottom: 16 }}>
              🎙️ Conversational Real Estate Intelligence
            </div>
            <h2
              style={{
                fontSize: 'clamp(2rem, 3.2vw, 2.6rem)',
                fontFamily: "'Playfair Display', serif",
                margin: '0 0 16px',
                lineHeight: 1.15,
                color: '#ffffff',
              }}
            >
              Meet LykAI: Your 24/7 Dubai Property Concierge
            </h2>
            <p style={{ color: '#e2e8f0', fontSize: 15.5, lineHeight: 1.6, margin: '0 0 28px' }}>
              Experience effortless property search. Instead of clicking endless filter checkboxes, speak casually in English, Tamil, or Tanglish. LykAI cross-references 25,000+ live listings, verifies DLD escrow accounts, explains mortgage eligibility, and books private viewings.
            </p>

            <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
              <button
                onClick={() => navigate('/chat')}
                style={{
                  padding: '13px 28px',
                  borderRadius: 10,
                  background: 'linear-gradient(135deg, #e8bd68 0%, #c59733 100%)',
                  color: '#2b081c',
                  border: 'none',
                  fontWeight: 800,
                  fontSize: 15,
                  cursor: 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 10,
                  boxShadow: '0 4px 16px rgba(232, 189, 104, 0.4)',
                }}
              >
                <span>Chat with LykAI</span>
                <span style={{ fontSize: 18 }}>→</span>
              </button>
              <a
                href="https://wa.me/971523485758"
                target="_blank"
                rel="noreferrer"
                style={{
                  padding: '13px 24px',
                  borderRadius: 10,
                  background: 'rgba(255,255,255,0.1)',
                  color: '#ffffff',
                  border: '1px solid rgba(255,255,255,0.3)',
                  fontWeight: 700,
                  fontSize: 15,
                  textDecoration: 'none',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 8,
                }}
              >
                <span>WhatsApp Advisor</span>
              </a>
            </div>
          </div>

          {/* Interactive Chat Sample Preview Chips */}
          <div style={{ background: 'rgba(255, 255, 255, 0.07)', border: '1px solid rgba(232, 189, 104, 0.28)', borderRadius: 16, padding: 24, backdropFilter: 'blur(12px)' }}>
            <div style={{ fontSize: 12.5, fontWeight: 800, color: '#f5d38a', marginBottom: 14, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
              💬 Click to ask LykAI:
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {SAMPLE_QUESTIONS.map((q, idx) => (
                <div
                  key={idx}
                  onClick={() => navigate(`/chat?prompt=${encodeURIComponent(q.replace(/[“”]/g, ''))}`)}
                  style={{
                    background: 'rgba(255, 255, 255, 0.08)',
                    padding: '12px 16px',
                    borderRadius: 10,
                    fontSize: 13.5,
                    color: '#ffffff',
                    cursor: 'pointer',
                    border: '1px solid rgba(255,255,255,0.12)',
                    transition: 'all 0.15s ease',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'rgba(232, 189, 104, 0.25)'
                    e.currentTarget.style.borderColor = '#f5d38a'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'rgba(255, 255, 255, 0.08)'
                    e.currentTarget.style.borderColor = 'rgba(255,255,255,0.12)'
                  }}
                >
                  {q}
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ============ NRI & INTERNATIONAL BUYER GUIDE ============ */}
      <section style={{ maxWidth: 1180, margin: '0 auto', padding: '0 24px 80px' }}>
        <div style={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 20, padding: 36, boxShadow: '0 6px 20px rgba(0,0,0,0.04)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 24 }}>
            <div style={{ maxWidth: 700 }}>
              <span style={{ fontSize: 12, fontWeight: 800, color: '#b45309', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                International Investor Support
              </span>
              <h3 style={{ fontSize: 24, fontFamily: "'Playfair Display', serif", color: '#0f172a', margin: '8px 0 10px', fontWeight: 700 }}>
                Buying Dubai Real Estate from India &amp; Overseas
              </h3>
              <p style={{ color: '#475569', fontSize: 14.5, lineHeight: 1.6, margin: 0 }}>
                Under Law No. 7 of 2006, foreign nationals and Indian NRIs enjoy full freehold property ownership rights in designated Dubai districts. You do not need to be physically present: contracts, DLD registration, escrow remittances via RBI LRS, and Power of Attorney (POA) can be completed 100% remotely.
              </p>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 230, borderLeft: '2px solid #e2e8f0', paddingLeft: 20 }}>
              <div style={{ fontSize: 12.5, color: '#64748b', fontWeight: 700, textTransform: 'uppercase' }}>Direct Dubai Line:</div>
              <a href="tel:+971523485758" style={{ fontSize: 16, fontWeight: 800, color: '#350c25', textDecoration: 'none' }}>+971 52 348 5758</a>
              <div style={{ fontSize: 12.5, color: '#64748b', fontWeight: 700, textTransform: 'uppercase', marginTop: 8 }}>Headquarters:</div>
              <span style={{ fontSize: 13, color: '#334155', lineHeight: 1.45, fontWeight: 500 }}>
                Office 1002, DAMAC Executive Heights,<br />
                Barsha Heights – TECOM, Dubai, UAE
              </span>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}
