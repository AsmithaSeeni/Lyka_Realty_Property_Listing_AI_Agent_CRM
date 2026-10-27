import React from 'react'
import { Link, useNavigate, useLocation, useSearchParams } from 'react-router-dom'
import api from '../api.js'

/* Optional customer sign-in (/login) and registration (/register).
   Guests never need this to chat — it only unlocks keeping conversations,
   saved properties and history across visits. The visible mode follows the
   route; legacy ?mode= links on /signin still work. */
export default function CustomerAuth() {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  // Only allow same-app redirects (must start with a single '/'): blocks
  // protocol-relative ("//evil.example") or absolute URLs from the query.
  const rawNext = searchParams.get('next') || '/chat'
  const next =
    rawNext.startsWith('/') && !rawNext.startsWith('//') ? rawNext : '/chat'
  const nextQs = next ? `?next=${encodeURIComponent(next)}` : ''
  const initialMode =
    location.pathname === '/register' || searchParams.get('mode') === 'register'
      ? 'register'
      : 'login'

  const [mode, setMode] = React.useState(initialMode)
  const [email, setEmail] = React.useState('')
  const [password, setPassword] = React.useState('')
  const [confirm, setConfirm] = React.useState('')
  const [name, setName] = React.useState('')
  const [error, setError] = React.useState(null)
  const [busy, setBusy] = React.useState(false)

  /* Switch between login/register. `keepError` preserves a message across the
     switch — without it, the duplicate-account (409) notice set in submit()
     was immediately wiped by setError(null) and the user saw a silent form. */
  const switchMode = (m, keepError = null) => {
    setMode(m)
    setError(keepError)
    setConfirm('') // confirm-password only exists while registering
    // Keep the URL truthful (/login <-> /register) while preserving ?next=
    const target = m === 'register' ? `/register${nextQs}` : `/login${nextQs}`
    if (location.pathname !== target.split('?')[0]) navigate(target)
  }

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    const mail = email.trim().toLowerCase()
    if (!mail.includes('@') || mail.length < 5) {
      setError('Enter a valid email address.')
      return
    }
    if (password.length < 6 && mode === 'register') {
      setError('Password must be at least 6 characters.')
      return
    }
    if (mode === 'register') {
      if (!confirm) {
        setError('Please confirm your password.')
        return
      }
      if (confirm !== password) {
        setError('Passwords do not match.')
        return
      }
    }
    setBusy(true)
    try {
      if (mode === 'register') {
        await api.customerRegister(mail, password, name.trim(), confirm)
      } else {
        await api.customerLogin(mail, password)
      }
      // Let the header pick up the new signed-in state immediately
      window.dispatchEvent(new Event('lyka:customer'))
      navigate(next, { replace: true })
    } catch (err) {
      if (err.status === 409) {
        // Duplicate registration: switch to the sign-in form AND keep the
        // explanation visible (email + password are kept for convenience).
        switchMode(
          'login',
          'An account already exists with this email — sign in instead.',
        )
      } else {
        setError(err.message || 'Could not sign you in. Please try again.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page ca-wrap">
      <div className="ca-card">
        <span className="eyebrow">LykAI · Lyka Realty</span>
        <h1>{mode === 'register' ? 'Create your account' : 'Welcome back'}</h1>
        <p className="ca-sub">
          {mode === 'register'
            ? 'Keep your LykAI conversations and saved properties — your current chats will be linked automatically.'
            : 'Sign in to pick up your conversations and saved properties where you left off.'}
        </p>

        <form onSubmit={submit} className="ca-form">
          {mode === 'register' && (
            <label>
              <span>Name <em>(optional)</em></span>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your name"
                autoComplete="name"
              />
            </label>
          )}
          <label>
            <span>Email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
              required
            />
          </label>
          <label>
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={mode === 'register' ? 'At least 6 characters' : 'Your password'}
              autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
              required
            />
          </label>

          {mode === 'register' && (
            <label>
              <span>Confirm Password</span>
              <input
                type="password"
                value={confirm}
                onChange={(e) => {
                  setConfirm(e.target.value)
                  if (error === 'Passwords do not match.') setError(null)
                }}
                placeholder="Re-enter your password"
                autoComplete="new-password"
                required
              />
            </label>
          )}

          {error && <div className="notice">⚠️ {error}</div>}

          <button className="btn gold btn-block" type="submit" disabled={busy}>
            {busy ? 'Please wait…' : mode === 'register' ? 'Create Account' : 'Sign In'}
          </button>
        </form>

        <div className="ca-switch">
          {mode === 'register' ? (
            <>Already have an account?{' '}
              <button type="button" onClick={() => switchMode('login')}>Sign In</button>
            </>
          ) : (
            <>New here?{' '}
              <button type="button" onClick={() => switchMode('register')}>Create Account</button>
            </>
          )}
        </div>

        <Link className="ca-guest" to="/chat">
          Continue as Guest → chat with LykAI now
        </Link>
      </div>
    </div>
  )
}
