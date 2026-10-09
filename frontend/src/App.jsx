import React from 'react'
import { Routes, Route, NavLink, Link, useLocation, Navigate } from 'react-router-dom'
import LandingPage from './pages/LandingPage.jsx'
import ChatPage from './pages/ChatPage.jsx'
import ConversationHistory from './pages/ConversationHistory.jsx'
import PropertyDetails from './pages/PropertyDetails.jsx'
import PropertiesPage from './pages/PropertiesPage.jsx'
import CustomerAuth from './pages/CustomerAuth.jsx'
import LoginPage from './pages/LoginPage.jsx'
import { RequireAgent } from './agent/AgentAuth.jsx'
import AgentShell from './agent/AgentShell.jsx'
import AgentDashboard from './agent/AgentDashboard.jsx'
import AgentLeads from './agent/AgentLeads.jsx'
import AgentLeadDetail from './agent/AgentLeadDetail.jsx'
import AgentConversations from './agent/AgentConversations.jsx'
import { trackPath } from './nav.js'
import api from './api.js'

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

/* Fixed brand header: transparent scrim over the hero, frosted maroon on scroll.
   Customer nav is deliberately minimal — LykAI is the primary experience:
   Home (logo) | Properties | LykAI | Sign In (or History once signed in). */
function Header() {
  const location = useLocation()
  const [scrolled, setScrolled] = React.useState(false)
  const [customer, setCustomer] = React.useState(null) // null = unknown yet
  const isHome = location.pathname === '/'

  React.useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  // Signed-in state (drives "Sign In" vs "My Chats"); refreshes when the
  // sign-in/out pages broadcast a change.
  React.useEffect(() => {
    let alive = true
    const load = () =>
      api.customerMe().then((m) => alive && setCustomer(m)).catch(() => alive && setCustomer(null))
    load()
    const onAuth = () => load()
    window.addEventListener('lyka:customer', onAuth)
    return () => {
      alive = false
      window.removeEventListener('lyka:customer', onAuth)
    }
  }, [location.pathname])

  // On inner pages the header must always read as solid (light content behind it)
  const solid = !isHome || scrolled

  return (
    <header className={`header${solid ? ' solid' : ''}${scrolled ? ' scrolled' : ''}`}>
      <div className="header__bar">
        <Link to="/" className="brand" aria-label="Lyka Realty home">
          <Logo />
        </Link>
        <nav className="nav-links" aria-label="Main">
          <NavLink to="/properties" className={({ isActive }) => (isActive ? 'active' : '')}>
            Properties
          </NavLink>
          <NavLink to="/chat" className={({ isActive }) => `nav-lykai${isActive ? ' active' : ''}`}>
            LykAI
          </NavLink>
          {customer?.authenticated ? (
            <NavLink to="/history" className={({ isActive }) => (isActive ? 'active' : '')}>
              My Chats
            </NavLink>
          ) : (
            <NavLink to="/signin" className={({ isActive }) => (isActive ? 'active' : '')}>
              Sign In
            </NavLink>
          )}
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
          <Link to="/chat">LykAI concierge</Link>
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
            <span className="ico">→</span> Talk to LykAI
          </Link>
        </div>
      </div>

      <div className="footer__bottom">
        <span>© {new Date().getFullYear()} Lyka Realty. All rights reserved.</span>
        <span>
          RERA · Dubai, UAE · <Link to="/login" style={{ textDecoration: 'underline' }}>Agent login</Link>
        </span>
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
  // footer are both always visible. Every other public page gets the full footer.
  const isChat = location.pathname.startsWith('/chat')
  // The agent CRM and login page have their own dedicated chrome — the
  // public marketing header/footer must never wrap internal screens.
  const isAgentArea =
    location.pathname.startsWith('/agent') || location.pathname === '/login'

  // Fresh pages always start at the top (skips smooth-scroll for instant jump)
  React.useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' })
  }, [location.pathname])

  // Record route changes so "Back" buttons know whether a real history entry
  // exists in this tab (works after new-tab opens / refreshes too)
  React.useEffect(() => {
    trackPath(location.pathname)
  }, [location.pathname])

  return (
    <>
      {!isAgentArea && <Header />}
      <Routes>
        {/* ---------- Public customer flow ---------- */}
        <Route path="/" element={<LandingPage />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/chat/:conversationId" element={<ChatPage />} />
        <Route path="/history" element={<ConversationHistory />} />
        <Route path="/properties" element={<PropertiesPage />} />
        <Route path="/property/:id" element={<PropertyDetails />} />
        <Route path="/properties/:id" element={<PropertyDetails />} />
        <Route path="/signin" element={<CustomerAuth />} />

        {/* ---------- Agent flow (login + protected CRM) ---------- */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/crm" element={<Navigate to="/login" replace />} />
        <Route path="/agent" element={<RequireAgent />}>
          <Route index element={<Navigate to="/agent/dashboard" replace />} />
          <Route path="dashboard" element={<AgentShell />}>
            <Route index element={<AgentDashboard />} />
          </Route>
          <Route path="leads" element={<AgentShell />}>
            <Route index element={<AgentLeads />} />
            <Route path=":id" element={<AgentLeadDetail />} />
          </Route>
          <Route path="conversations" element={<AgentShell />}>
            <Route index element={<AgentConversations />} />
          </Route>
        </Route>

        <Route path="*" element={<LandingPage />} />
      </Routes>
      {!isAgentArea && (isChat ? <ChatFooter /> : <Footer />)}
    </>
  )
}
