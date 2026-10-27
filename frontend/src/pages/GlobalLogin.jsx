import React from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext.jsx'
import api from '../api.js'

/* ------------------------------------------------------------------ */
/* GLOBAL LOGIN PORTAL (Phase 3) — the single sign-in entry point for  */
/* every Lyka Realty role: System Administrator, HR, Payroll, Agent,   */
/* Sales Manager, Operations, Finance, Property Manager, Support and   */
/* Customer.                                                           */
/*                                                                     */
/* One form authenticates either a STAFF account (email or username)   */
/* or a CUSTOMER account (email) — the backend resolves which world    */
/* the credential belongs to. The form deliberately has NO role         */
/* selector: identity, roles and permissions come from the database,   */
/* never from anything the user types or picks.                        */
/*                                                                     */
/* Customer REGISTRATION stays a separate, clearly-labelled mode — it  */
/* only ever creates a customer account (staff accounts are created by */
/* an authorised administrator).                                       */
/* ------------------------------------------------------------------ */

// Sanitize ?next= to a single-slash internal path (blocks open redirects).
function safeNext(raw) {
  const value = raw || '/chat'
  // Single leading slash only: blocks protocol-relative "//host" targets and
  // backslash variants that browsers normalise to "//" on reload.
  return value.startsWith('/') && !value.startsWith('//') && !value.includes('\\')
    ? value
    : '/chat'
}

export default function GlobalLogin() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [searchParams] = useSearchParams()
  const { login, isStaff, isCustomer, landing } = useAuth()

  const next = safeNext(searchParams.get('next'))
  // The URL is the single source of truth for which form is shown: opening
  // /register directly (or refreshing it) must land on the registration form,
  // while /login and the legacy /signin alias stay on sign-in. The query
  // param is kept as a compatibility override for older links.
  const registerMode = pathname === '/register' || searchParams.get('mode') === 'register'
  const initialMode = registerMode ? 'register' : 'signin'

  const [mode, setMode] = React.useState(initialMode)
  const [identifier, setIdentifier] = React.useState('')
  const [password, setPassword] = React.useState('')
  const [confirm, setConfirm] = React.useState('')
  const [name, setName] = React.useState('')
  const [showPw, setShowPw] = React.useState(false)
  const [error, setError] = React.useState(null)
  const [busy, setBusy] = React.useState(false)

  // Already signed in? Bounce to the right place (staff -> CRM, customer -> site).
  React.useEffect(() => {
    if (isStaff) navigate(landing || '/agent/dashboard', { replace: true })
    else if (isCustomer) navigate(next, { replace: true })
  }, [isStaff, isCustomer, landing, next, navigate])

  // Follow the URL when it changes from outside the form (browser back/
  // forward, direct edits). After switchMode() the URL and state already
  // agree, so this just re-derives the same value.
  React.useEffect(() => {
    setMode(pathname === '/register' || searchParams.get('mode') === 'register' ? 'register' : 'signin')
  }, [pathname, searchParams])

  const switchMode = (m, keepError = null) => {
    setMode(m)
    setError(keepError)
    setConfirm('')
    const target = m === 'register' ? `/register?next=${encodeURIComponent(next)}` : `/login?next=${encodeURIComponent(next)}`
    navigate(target)
  }

  const submit = async (e) => {
    e.preventDefault()
    setError(null)

    if (mode === 'register') {
      // Client-side mirror of the backend rules (server re-validates all).
      const mail = identifier.trim().toLowerCase()
      if (!mail.includes('@') || mail.length < 5) {
        setError('Enter a valid email address.')
        return
      }
      if (password.length < 6) {
        setError('Password must be at least 6 characters.')
        return
      }
      if (!confirm) {
        setError('Please confirm your password.')
        return
      }
      if (confirm !== password) {
        setError('Passwords do not match.')
        return
      }
      setBusy(true)
      try {
        // Registration is CUSTOMER-only (never staff).
        await api.customerRegister(mail, password, name.trim(), confirm)
        window.dispatchEvent(new Event('lyka:customer'))
        window.dispatchEvent(new Event('lyka:auth'))
        navigate(next, { replace: true })
      } catch (err) {
        if (err.status === 409) {
          switchMode('signin', err.message || 'An account already exists — sign in instead.')
        } else {
          setError(err.message || 'Registration failed. Please try again.')
        }
      } finally {
        setBusy(false)
      }
      return
    }

    // ---- sign-in (staff OR customer) ----
    const ident = identifier.trim()
    if (!ident || !password) {
      setError('Enter your email (or username) and password.')
      return
    }
    setBusy(true)
    try {
      const fresh = await login(ident, password)
      window.dispatchEvent(new Event('lyka:customer'))
      const dest =
        fresh && fresh.kind === 'staff'
          ? fresh.landing || '/agent/dashboard'
          : next
      navigate(dest, { replace: true })
    } catch (err) {
      setError(
        err.status === 401
          ? 'Invalid email or password.'
          : err.message || 'Sign-in failed. Check your connection and try again.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="gl">
      {/* Brand panel */}
      <aside className="gl-brand">
        <img
          src="/lyka_logo.png"
          alt="Lyka Realty"
          className="gl-brand__logo"
          onError={(e) => { e.currentTarget.style.display = 'none' }}
        />
        <div className="gl-brand__body">
          <span className="eyebrow">Lyka Realty · Your property journey</span>
          <h1>Your next property move starts here.</h1>
          <p>
            Sign in to continue your conversations, revisit saved properties, and
            manage your property journey with Lyka Realty.
          </p>
          <div className="gl-brand__stats">
            <div><b>Private by design</b><span>Secure account access</span></div>
            <div><b>Your journey, connected</b><span>Chats and saved properties</span></div>
            <div><b>Access that fits your role</b><span>Permissions managed securely</span></div>
          </div>
        </div>
        <div className="gl-brand__foot">Lyka Realty · Barsha Heights – Tecom, Dubai, UAE</div>
      </aside>

      {/* Form panel */}
      <main className="gl-form">
        <form onSubmit={submit} className="gl-card" autoComplete="on" noValidate>
          <span className="eyebrow">
            {mode === 'register' ? 'Create your customer account' : 'Welcome back'}
          </span>
          <h2>
            {mode === 'register'
              ? 'Welcome to Lyka Realty'
              : 'Continue your property journey.'}
          </h2>
          <p className="gl-card__sub">
            {mode === 'register'
              ? 'Create an account to save properties, keep your conversations, and return to your search whenever you’re ready.'
              : 'Sign in to revisit your saved properties and conversations.'}
          </p>

          {error && (
            <div className="gl-error" role="alert" aria-live="polite">
              ⚠ {error}
            </div>
          )}

          <label className="gl-field">
            <span>{mode === 'register' ? 'Email address' : 'Email or username'}</span>
            <input
              type="text"
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              placeholder={mode === 'register' ? 'you@example.com' : 'you@lykarealty.ae'}
              autoComplete={mode === 'register' ? 'email' : 'username'}
              autoFocus
              required
            />
          </label>

          {mode === 'register' && (
            <label className="gl-field">
              <span>Full name (optional)</span>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your name"
                autoComplete="name"
                maxLength={120}
              />
            </label>
          )}

          <label className="gl-field">
            <span>Password</span>
            <div className="gl-pw">
              <input
                type={showPw ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
                required
              />
              <button
                type="button"
                className="gl-pw__toggle"
                onClick={() => setShowPw((s) => !s)}
                aria-label={showPw ? 'Hide password' : 'Show password'}
                tabIndex={0}
              >
                {showPw ? 'Hide' : 'Show'}
              </button>
            </div>
          </label>

          {mode === 'register' && (
            <label className="gl-field">
              <span>Confirm password</span>
              <input
                type={showPw ? 'text' : 'password'}
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                placeholder="••••••••"
                autoComplete="new-password"
                required
              />
            </label>
          )}

          <button className="btn btn-block gl-submit" type="submit" disabled={busy}>
            {busy
              ? mode === 'register'
                ? 'Creating account…'
                : 'Signing in…'
              : mode === 'register'
                ? 'Create account'
                : 'Sign in'}
          </button>

          <div className="gl-switch">
            {mode === 'register' ? (
              <>
                Already have an account?{' '}
                <button type="button" className="gl-link" onClick={() => switchMode('signin')}>
                  Sign in
                </button>
              </>
            ) : (
              <>
                New to Lyka Realty?{' '}
                <button type="button" className="gl-link" onClick={() => switchMode('register')}>
                  Create a customer account
                </button>
              </>
            )}
          </div>

          <a className="gl-back" href="/">← Back to public site</a>
          <p className="gl-note">
            Staff accounts are created by an administrator. Password recovery for
            staff is handled by your administrator.
          </p>
        </form>
      </main>
    </div>
  )
}
