import React from 'react'
import { Routes, Route, NavLink, Link, useLocation } from 'react-router-dom'
import LandingPage from './pages/LandingPage.jsx'
import ChatPage from './pages/ChatPage.jsx'
import CRMDashboard from './pages/CRMDashboard.jsx'
import ConversationHistory from './pages/ConversationHistory.jsx'
import PropertyDetails from './pages/PropertyDetails.jsx'

function Logo({ light = true }) {
  const [failed, setFailed] = React.useState(false)
  if (failed) return <span className="brand-fallback">L</span>
  return (
    <img
      src="/lyka_logo.png"
      alt="Lyka Realty"
      onError={() => setFailed(true)}
      style={light ? undefined : { filter: 'none' }}
    />
  )
}

/* Fixed brand header: transparent scrim over the hero, frosted maroon on scroll */
function Header() {
  const location = useLocation()
  const [scrolled, setScrolled] = React.useState(false)
  const isHome = location.pathname === '/'

  React.useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  // On inner pages the header must always read as solid (light content behind it)
  const solid = !isHome || scrolled

  return (
    <header className={`header${solid ? ' solid' : ''}${scrolled ? ' scrolled' : ''}`}>
      <div className="header__bar">
        <Link to="/" className="brand" aria-label="Lyka Realty home">
          <Logo />
        </Link>
        <nav className="nav-links" aria-label="Main">
          <NavLink to="/chat" className={({ isActive }) => (isActive ? 'active' : '')}>
            AI Agent
          </NavLink>
          <NavLink to="/history" className={({ isActive }) => (isActive ? 'active' : '')}>
            Conversations
          </NavLink>
          <NavLink to="/crm" className={({ isActive }) => (isActive ? 'active' : '')}>
            CRM
          </NavLink>
        </nav>
      </div>
    </header>
  )
}

function Footer() {
  return (
    <footer className="footer">
      <div className="footer__grid">
        <div className="footer__brand">
          <Link to="/" className="brand">
            <Logo />
          </Link>
          <p>
            Helping people buy, rent and invest in Dubai property with clarity and
            care — no pressure, no confusion. Founded 2024, 300+ clients served.
          </p>
        </div>

        <div className="footer__col">
          <div className="footer__title">Services</div>
          <Link to="/chat">Buy property in Dubai</Link>
          <Link to="/chat">Rent property in Dubai</Link>
          <Link to="/chat">Investment advisory</Link>
          <Link to="/chat">AI property concierge</Link>
        </div>

        <div className="footer__col">
          <div className="footer__title">Communities</div>
          <Link to="/chat">Dubai Marina</Link>
          <Link to="/chat">Downtown Dubai</Link>
          <Link to="/chat">Palm Jumeirah</Link>
          <Link to="/chat">Jumeirah Village Circle</Link>
        </div>

        <div className="footer__col">
          <div className="footer__title">Contact</div>
          <a href="tel:+971523485758">Phone / WhatsApp: +971 52 348 5758</a>
          <a href="mailto:admin@lykarealty.ae">admin@lykarealty.ae</a>
          <p style={{ marginTop: 10 }}>
            Office 1002, Damac Executive Heights,
            <br />
            Barsha Heights – Tecom, Dubai, UAE
          </p>
          <Link to="/chat" className="btn gold btn-sm">
            <span className="ico">→</span> Talk to our AI
          </Link>
        </div>
      </div>

      <div className="footer__bottom">
        <span>© {new Date().getFullYear()} Lyka Realty. All rights reserved.</span>
        <span>RERA · Dubai, UAE · AI Agent + CRM demo</span>
      </div>
    </footer>
  )
}

/* Slim footer for chat routes: keeps brand + contact visible while the chat
   stays viewport-locked (header + chat + this strip = exactly one screen). */
function ChatFooter() {
  return (
    <footer className="chat-foot">
      <div className="chat-foot__in">
        <span className="chat-foot__copy">
          © {new Date().getFullYear()} Lyka Realty
          <span className="chat-foot__addr"> · Office 1002, Damac Executive Heights, Barsha Heights – Tecom, Dubai</span>
        </span>
        <nav className="chat-foot__links" aria-label="Contact">
          <a href="tel:+971523485758">📞 +971 52 348 5758</a>
          <a className="chat-foot__mail" href="mailto:admin@lykarealty.ae">✉ admin@lykarealty.ae</a>
        </nav>
      </div>
    </footer>
  )
}

export default function App() {
  const location = useLocation()
  // Chat is a full-screen app view: slim pinned footer so the composer and
  // footer are both always visible. Every other page gets the full footer.
  const isChat = location.pathname.startsWith('/chat')

  // Fresh pages always start at the top (skips smooth-scroll for instant jump)
  React.useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' })
  }, [location.pathname])

  return (
    <>
      <Header />
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/chat/:conversationId" element={<ChatPage />} />
        <Route path="/crm" element={<CRMDashboard />} />
        <Route path="/history" element={<ConversationHistory />} />
        <Route path="/property/:id" element={<PropertyDetails />} />
        <Route path="*" element={<LandingPage />} />
      </Routes>
      {isChat ? <ChatFooter /> : <Footer />}
    </>
  )
}
