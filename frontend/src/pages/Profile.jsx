import React from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../api.js'

/* /profile — lightweight customer profile: who you are signed in as, quick
   links to personal areas, and sign out. Guests see the optional sign-in
   prompt (never a blocker). */
export default function Profile() {
  const navigate = useNavigate()
  const [customer, setCustomer] = React.useState(null) // null = still checking
  const [guestViewed, setGuestViewed] = React.useState(false)
  const [counts, setCounts] = React.useState({ chats: null, saved: null })

  React.useEffect(() => {
    api.customerMe().then(setCustomer).catch(() => setCustomer(null))
  }, [])

  React.useEffect(() => {
    if (!customer?.authenticated) return
    let alive = true
    Promise.allSettled([
      api.listConversations(),
      api.savedProperties(),
    ]).then(([chats, saved]) => {
      if (!alive) return
      setCounts({
        chats: chats.status === 'fulfilled' ? chats.value.length : null,
        saved: saved.status === 'fulfilled' ? (saved.value.results || []).length : null,
      })
    })
    return () => { alive = false }
  }, [customer?.authenticated])

  const signOut = async () => {
    try {
      await api.customerLogout()
    } catch { /* cookie is gone either way */ }
    window.dispatchEvent(new Event('lyka:customer'))
    navigate('/chat', { replace: true })
  }

  /* -------- still checking identity -------- */
  if (customer === null) {
    return (
      <div className="page">
        <div className="empty">Loading…</div>
      </div>
    )
  }

  /* -------- guest: the optional sign-in explanation first -------- */
  if (!customer.authenticated && !guestViewed) {
    return (
      <div className="page">
        <div className="keep-prompt keep-prompt--page">
          <span className="eyebrow">Your profile</span>
          <h2>Want to keep your LykAI conversations and saved properties?</h2>
          <p>
            A free account is optional — it keeps your chats and saved listings
            across visits. Your profile shows what’s saved to your account.
          </p>
          <div className="keep-prompt__btns">
            <Link className="btn gold" to="/login?next=/profile">
              Sign In
            </Link>
            <Link className="btn dark" to="/register?next=/profile">
              Create Account
            </Link>
            <button className="btn ghost" onClick={() => setGuestViewed(true)}>
              Continue as Guest
            </button>
          </div>
          <Link className="keep-prompt__chat" to="/chat">
            ← Back to LykAI
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <div className="page-head">
        <div className="row">
          <div>
            <span className="eyebrow">Your account</span>
            <h1>{customer.name || 'My profile'}</h1>
            <p>Signed in as {customer.email}.</p>
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button className="btn gold btn-sm" onClick={() => navigate('/chat')}>
              <span className="ico">→</span> Talk to LykAI
            </button>
            <button className="btn dark btn-sm" onClick={signOut}>Sign out</button>
          </div>
        </div>
      </div>

      <div className="notice" style={{ background: 'var(--gold-soft, #f7e7c4)' }}>
        🔒 This is your personal Lyka Realty customer profile — separate from
        Lyka Realty’s internal staff CRM.
      </div>

      <div className="subhead">Your stuff</div>
      <div className="history-item" style={{ cursor: 'default' }}>
        <div>
          <b>Conversations</b>
          <div className="sub">
            {counts.chats === null ? '—' : `${counts.chats} chat${counts.chats === 1 ? '' : 's'}`} with LykAI
          </div>
        </div>
        <div style={{ display: 'flex', gap: 9, flexShrink: 0 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => navigate('/history')}>
            My Chats →
          </button>
        </div>
      </div>
      <div className="history-item" style={{ cursor: 'default' }}>
        <div>
          <b>Saved properties</b>
          <div className="sub">
            {counts.saved === null ? '—' : `${counts.saved} saved`} · real listings from our dataset
          </div>
        </div>
        <div style={{ display: 'flex', gap: 9, flexShrink: 0 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => navigate('/saved')}>
            View saved →
          </button>
        </div>
      </div>
    </div>
  )
}
