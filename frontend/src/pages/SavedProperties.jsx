import React from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../api.js'
import SavedGrid from '../components/SavedGrid.jsx'

/* /saved — the signed-in customer's saved properties.
   Guests get the same friendly, optional sign-in prompt as My Chats. */
export default function SavedProperties() {
  const navigate = useNavigate()
  const [customer, setCustomer] = React.useState(null) // null = still checking
  const [guestViewed, setGuestViewed] = React.useState(false)
  const [saved, setSaved] = React.useState([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState(null)

  React.useEffect(() => {
    api.customerMe().then(setCustomer).catch(() => setCustomer(null))
  }, [])

  React.useEffect(() => {
    if (customer === null) return
    if (customer.authenticated) {
      api.savedProperties()
        .then((r) => setSaved(r.results || []))
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false))
    } else {
      setLoading(false) // guests never call the saved endpoint
    }
  }, [customer])

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
          <span className="eyebrow">Saved properties</span>
          <h2>Want to keep your LykAI conversations and saved properties?</h2>
          <p>
            Saving properties is a free, optional account feature — LykAI and
            browsing work without signing in. Sign in to keep the listings you
            like across visits.
          </p>
          <div className="keep-prompt__btns">
            <Link className="btn gold" to="/login?next=/saved">
              Sign In
            </Link>
            <Link className="btn dark" to="/register?next=/saved">
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
            <h1>Saved properties</h1>
            <p>
              {customer.authenticated
                ? `Signed in as ${customer.email}. Listings you save are kept with your account.`
                : 'Saved properties are available when you sign in — browsing and LykAI keep working as a guest.'}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button className="btn ghost btn-sm" onClick={() => navigate('/history')}>
              My Chats
            </button>
            <button className="btn gold btn-sm" onClick={() => navigate('/chat')}>
              <span className="ico">→</span> Talk to LykAI
            </button>
            {customer.authenticated && (
              <button className="btn dark btn-sm" onClick={signOut}>Sign out</button>
            )}
          </div>
        </div>
      </div>

      {error && <div className="notice">⚠️ {error}</div>}

      {loading && <div className="empty">Loading saved properties…</div>}

      {!loading && !error && customer.authenticated && saved.length === 0 && (
        <div className="empty">
          <div className="big">🔖</div>
          Nothing saved yet — open a property and hit Save, or ask LykAI to shortlist for you.
          <div style={{ marginTop: 18 }}>
            <button className="btn gold btn-sm" onClick={() => navigate('/chat')}>
              Talk to LykAI
            </button>
          </div>
        </div>
      )}

      {!loading && customer.authenticated && saved.length > 0 && (
        <>
          <div className="subhead">{saved.length} saved</div>
          <SavedGrid items={saved} />
        </>
      )}
    </div>
  )
}
