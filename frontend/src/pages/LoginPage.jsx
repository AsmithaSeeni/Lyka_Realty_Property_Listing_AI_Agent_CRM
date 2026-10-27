import React from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api.js'

/**
 * /agent/login — dedicated staff entry point for the internal Lyka Realty CRM
 * (kept fully separate from the customer /login). A subtle "Staff login" link
 * in the customer footer is the only site-wide way in. Already-authenticated
 * agents bounce straight to /agent/dashboard. Never displays credentials.
 */
export default function LoginPage() {
  const navigate = useNavigate()
  const [username, setUsername] = React.useState('')
  const [password, setPassword] = React.useState('')
  const [error, setError] = React.useState(null)
  const [busy, setBusy] = React.useState(false)
  const [checked, setChecked] = React.useState(false)

  // Already signed in? Go to the dashboard.
  // Bounded check: if /api/auth/me hangs (backend down / network stall),
  // unlock the form after 4s instead of leaving the button disabled forever.
  React.useEffect(() => {
    let alive = true
    const unlock = setTimeout(() => {
      if (alive) setChecked(true)
    }, 4000)
    api
      .me()
      .then(() => {
        if (alive) navigate('/agent/dashboard', { replace: true })
      })
      .catch(() => {
        if (alive) setChecked(true)
      })
      .finally(() => clearTimeout(unlock))
    return () => {
      alive = false
      clearTimeout(unlock)
    }
  }, [navigate])

  const submit = async (e) => {
    e.preventDefault()
    if (!username.trim() || !password) return
    setBusy(true)
    setError(null)
    try {
      await api.login(username.trim(), password)
      navigate('/agent/dashboard', { replace: true })
    } catch (err) {
      setError(
        err.status === 401
          ? 'Invalid username or password.'
          : err.message || 'Sign-in failed. Check your connection and try again.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="lg">
      {/* Brand panel */}
      <aside className="lg-brand">
        <img
          src="/lyka_logo.png"
          alt="Lyka Realty"
          className="lg-brand__logo"
          onError={(e) => { e.currentTarget.style.display = 'none' }}
        />
        <div className="lg-brand__body">
          <span className="eyebrow">Internal · Authorized agents only</span>
          <h1>The deals behind every conversation.</h1>
          <p>
            Sign in to review AI-captured leads, read full customer conversations
            and move prospects through the pipeline.
          </p>
          <div className="lg-brand__stats">
            <div><b>25,082</b><span>Listings indexed</span></div>
            <div><b>3</b><span>Languages handled</span></div>
            <div><b>24/7</b><span>AI qualification</span></div>
          </div>
        </div>
        <div className="lg-brand__foot">Lyka Realty · Barsha Heights – Tecom, Dubai, UAE</div>
      </aside>

      {/* Form panel */}
      <main className="lg-form">
        <form onSubmit={submit} className="lg-card" autoComplete="on">
          <span className="eyebrow">Internal Lyka Realty CRM</span>
          <h2>Staff sign in</h2>
          <p className="lg-card__sub">Use your Lyka Realty CRM credentials.</p>

          {error && <div className="lg-error">⚠ {error}</div>}

          <label className="lg-field">
            <span>Email or username</span>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="you@lykarealty.ae"
              autoComplete="username"
              autoFocus
              required
            />
          </label>

          <label className="lg-field">
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="current-password"
              required
            />
          </label>

          <button className="btn btn-block lg-submit" type="submit" disabled={busy || !checked}>
            {busy ? 'Signing in…' : 'Sign in to CRM'}
          </button>

          <a className="lg-back" href="/">← Back to public site</a>
        </form>
      </main>
    </div>
  )
}
