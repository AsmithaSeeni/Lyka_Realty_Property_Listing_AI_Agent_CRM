import React, { useState, useEffect } from 'react'
import { NavLink, Outlet, Link, useNavigate, useLocation } from 'react-router-dom'
import api from '../api.js'
import './portal.css'

export default function CustomerShell() {
  const navigate = useNavigate()
  const location = useLocation()
  const [customer, setCustomer] = useState(null)
  const [unreadCount, setUnreadCount] = useState(0)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true
    api.customerProfile()
      .then((data) => {
        if (!alive) return
        setCustomer(data)
        api.customerNotifications()
          .then((nData) => {
            if (alive) setUnreadCount(nData.unread_count || 0)
          })
          .catch(() => {})
      })
      .catch(() => {
        if (alive) {
          navigate('/login?next=' + encodeURIComponent(location.pathname), { replace: true })
        }
      })
      .finally(() => {
        if (alive) setLoading(false)
      })

    return () => { alive = false }
  }, [location.pathname, navigate])

  const handleSignOut = async () => {
    try {
      await api.customerLogout()
    } catch {
      // cookie is cleared either way
    }
    window.dispatchEvent(new Event('lyka:customer'))
    navigate('/login', { replace: true })
  }

  if (loading) {
    return (
      <div className="portal-root flex items-center justify-center">
        <div style={{ textAlign: 'center', padding: '60px 20px' }}>
          <div style={{ width: 32, height: 32, border: '2px solid rgba(217, 119, 6, 0.3)', borderTopColor: '#f59e0b', borderRadius: '50%', animation: 'spin 1s linear infinite', margin: '0 auto 12px' }} />
          <p style={{ fontSize: 12, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#a8a29e' }}>Loading Client Portal...</p>
        </div>
      </div>
    )
  }

  const navItems = [
    { to: '/portal', label: 'Overview', end: true },
    { to: '/portal/appointments', label: 'My Viewings' },
    { to: '/portal/saved', label: 'Saved Properties' },
    { to: '/portal/messages', label: 'Messages' },
    {
      to: '/portal/notifications',
      label: 'Notifications',
      badge: unreadCount > 0 ? unreadCount : null,
    },
    { to: '/portal/profile', label: 'Profile & Preferences' },
  ]

  return (
    <div className="portal-root">
      {/* Top Brand Bar */}
      <header className="portal-header">
        <div className="portal-brand">
          <Link to="/" style={{ display: 'flex', alignItems: 'center', gap: 10, textDecoration: 'none' }}>
            <span className="portal-brand-logo">L</span>
            <div>
              <span className="portal-brand-title">LYKA REALTY</span>
              <span className="portal-brand-sub">Client Portal</span>
            </div>
          </Link>

          <div className="portal-links-quick">
            <Link to="/properties">Browse Listings</Link>
            <span>•</span>
            <Link to="/chat">LykAI Concierge</Link>
          </div>
        </div>

        <div className="portal-user-meta">
          <div style={{ textAlign: 'right' }}>
            <p style={{ fontSize: 13, fontWeight: 600, color: '#ffffff', margin: 0 }}>{customer?.name || 'Valued Client'}</p>
            <p style={{ fontSize: 11, color: '#a8a29e', margin: 0 }}>{customer?.email}</p>
          </div>

          <div className="portal-avatar">
            {(customer?.name || customer?.email || 'C')[0].toUpperCase()}
          </div>

          <button onClick={handleSignOut} className="portal-btn-signout">
            Sign Out
          </button>
        </div>
      </header>

      {/* Navigation Sub-bar */}
      <nav className="portal-nav">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => (isActive ? 'active' : '')}
          >
            <span>{item.label}</span>
            {item.badge && (
              <span className="portal-badge-count">
                {item.badge}
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Main Content Area */}
      <main className="portal-main">
        <Outlet context={{ customer, setCustomer, setUnreadCount }} />
      </main>
    </div>
  )
}
