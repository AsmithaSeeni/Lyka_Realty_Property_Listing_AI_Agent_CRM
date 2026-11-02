import React, { useState, useEffect } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import api from '../api.js'
import ViewingRequestModal from './ViewingRequestModal.jsx'

export default function CustomerDashboard() {
  const { customer } = useOutletContext()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedPropForViewing, setSelectedPropForViewing] = useState(null)

  const loadDashboard = () => {
    setLoading(true)
    api.customerDashboard()
      .then(setData)
      .catch((err) => setError(err.message || 'Failed to load dashboard'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadDashboard()
  }, [])

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '60px 20px', color: '#a8a29e' }}>
        <div style={{ width: 32, height: 32, border: '2px solid rgba(217,119,6,0.3)', borderTopColor: '#f59e0b', borderRadius: '50%', animation: 'spin 1s linear infinite', margin: '0 auto 12px' }} />
        Loading your overview...
      </div>
    )
  }

  if (error || !data) {
    return (
      <div style={{ padding: 24, borderRadius: 16, background: 'rgba(159, 18, 57, 0.2)', border: '1px solid rgba(225, 29, 72, 0.3)', color: '#fecdd3', textAlign: 'center' }}>
        <p style={{ fontSize: 13 }}>{error || 'Unable to display dashboard'}</p>
        <button
          onClick={loadDashboard}
          className="portal-btn-ghost"
          style={{ marginTop: 12 }}
        >
          Try Again
        </button>
      </div>
    )
  }

  const { metrics, recent_saved, upcoming_viewings, recent_notifications } = data
  const completionPct = metrics.profile_completion_pct || 0

  return (
    <div className="space-y-8">
      {/* Welcome & Profile Completion Banner */}
      <div className="portal-banner">
        <div style={{ display: 'flex', flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 24, position: 'relative', zIndex: 2 }}>
          <div style={{ maxWidth: 640 }}>
            <span style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.12em', color: '#f59e0b', fontWeight: 700 }}>
              Client Portal Overview
            </span>
            <h1 style={{ fontSize: 26, fontFamily: 'Playfair Display, Georgia, serif', color: '#ffffff', margin: '6px 0 8px 0' }}>
              Welcome back, {customer?.name || 'Valued Client'}
            </h1>
            <p style={{ fontSize: 13, color: '#a8a29e', lineHeight: 1.6, margin: 0 }}>
              Track your scheduled property viewings, manage your bookmarked luxury residences, and communicate directly with your dedicated property advisor.
            </p>
          </div>

          <div style={{ background: 'rgba(20, 18, 17, 0.85)', border: '1px solid #292524', borderRadius: 14, padding: 16, minWidth: 260 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 8 }}>
              <span style={{ color: '#d6d3d1', fontWeight: 600 }}>Profile Completion</span>
              <span style={{ color: '#f59e0b', fontWeight: 700 }}>{completionPct}%</span>
            </div>
            <div style={{ width: '100%', background: '#292524', height: 8, borderRadius: 999, overflow: 'hidden' }}>
              <div
                style={{
                  background: 'linear-gradient(90deg, #d97706, #f59e0b)',
                  height: '100%',
                  width: `${completionPct}%`,
                  borderRadius: 999,
                  transition: 'width 0.6s ease',
                }}
              />
            </div>
            <div style={{ marginTop: 10, textAlign: 'right' }}>
              <Link
                to="/portal/profile"
                style={{ fontSize: 11, color: '#f59e0b', textDecoration: 'none', fontWeight: 600 }}
              >
                {completionPct < 100 ? 'Complete missing preferences →' : 'Edit preferences →'}
              </Link>
            </div>
          </div>
        </div>
      </div>

      {/* KPI Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16 }}>
        {[
          {
            label: 'Saved Residences',
            value: metrics.saved_count,
            icon: '❤️',
            link: '/portal/saved',
            linkText: 'View shortlist',
          },
          {
            label: 'Active Viewings',
            value: metrics.upcoming_viewings_count,
            icon: '📅',
            link: '/portal/appointments',
            linkText: 'Manage schedule',
          },
          {
            label: 'Unread Alerts',
            value: metrics.unread_notifications_count,
            icon: '🔔',
            link: '/portal/notifications',
            linkText: 'Notification center',
          },
          {
            label: 'Concierge Messages',
            value: data.recent_communications?.length || 0,
            icon: '💬',
            link: '/portal/messages',
            linkText: 'Open dialogue',
          },
        ].map((m, i) => (
          <div key={i} className="portal-kpi-card">
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="portal-kpi-lbl">{m.label}</span>
                <span style={{ fontSize: 18 }}>{m.icon}</span>
              </div>
              <div className="portal-kpi-val">{m.value}</div>
            </div>
            <div style={{ marginTop: 14 }}>
              <Link
                to={m.link}
                style={{ fontSize: 11.5, color: '#f59e0b', textDecoration: 'none', fontWeight: 600 }}
              >
                {m.linkText} →
              </Link>
            </div>
          </div>
        ))}
      </div>

      {/* Two Column Layout: Upcoming Viewings & Saved Residences */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: 24 }}>
        {/* Left Column: Upcoming Viewings */}
        <div className="portal-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, borderBottom: '1px solid rgba(120, 113, 108, 0.15)', paddingBottom: 10 }}>
            <h2 style={{ fontSize: 16, margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
              <span>📅</span> Upcoming Property Viewings
            </h2>
            <Link
              to="/portal/appointments"
              style={{ fontSize: 12, color: '#f59e0b', textDecoration: 'none', fontWeight: 600 }}
            >
              All viewings ({upcoming_viewings.length}) →
            </Link>
          </div>

          {upcoming_viewings.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '36px 16px', color: '#78716c' }}>
              <span style={{ fontSize: 32, display: 'block', marginBottom: 8, opacity: 0.5 }}>📅</span>
              <p style={{ fontSize: 13, color: '#a8a29e', margin: '0 0 10px 0' }}>No upcoming viewings scheduled.</p>
              <Link to="/properties" className="portal-btn-gold" style={{ fontSize: 12, padding: '7px 16px' }}>
                Browse properties to book a viewing
              </Link>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {upcoming_viewings.map((v) => (
                <div
                  key={v.id}
                  style={{
                    background: '#141211',
                    border: '1px solid #292524',
                    borderRadius: 12,
                    padding: 14,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 8,
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <h3 style={{ fontSize: 14, color: '#ffffff', margin: 0 }}>
                        {v.property_title || `Property #${v.property_id || ''}`}
                      </h3>
                      <p style={{ fontSize: 11.5, color: '#a8a29e', marginTop: 3 }}>
                        📍 {v.location_or_link || 'Location details in confirmation'}
                      </p>
                    </div>
                    <span
                      className={`portal-pill ${
                        v.status === 'confirmed'
                          ? 'portal-pill-confirmed'
                          : v.status === 'cancelled'
                          ? 'portal-pill-cancelled'
                          : 'portal-pill-pending'
                      }`}
                    >
                      {v.status}
                    </span>
                  </div>

                  <div style={{ fontSize: 12, color: '#d6d3d1', display: 'flex', gap: 14, flexWrap: 'wrap' }}>
                    <span>🕒 {v.start_at ? new Date(v.start_at).toLocaleString('en-AE', { dateStyle: 'medium', timeStyle: 'short' }) : 'Pending confirmation'}</span>
                    <span>👤 {v.agent_name || 'Assigned Property Advisor'}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right Column: Saved Shortlist & Alerts */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          {/* Saved Shortlist */}
          <div className="portal-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, borderBottom: '1px solid rgba(120, 113, 108, 0.15)', paddingBottom: 10 }}>
              <h2 style={{ fontSize: 16, margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
                <span>❤️</span> Bookmarked Residences
              </h2>
              <Link
                to="/portal/saved"
                style={{ fontSize: 12, color: '#f59e0b', textDecoration: 'none', fontWeight: 600 }}
              >
                View all ({metrics.saved_count}) →
              </Link>
            </div>

            {recent_saved.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '30px 16px', color: '#78716c', fontSize: 12 }}>
                You haven't saved any listings yet.
                <div style={{ marginTop: 8 }}>
                  <Link to="/properties" style={{ color: '#f59e0b', textDecoration: 'none' }}>
                    Explore available properties →
                  </Link>
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {recent_saved.map((prop) => {
                  const pid = prop.property_id || prop.id
                  return (
                    <div
                      key={pid}
                      style={{
                        background: '#141211',
                        border: '1px solid #292524',
                        borderRadius: 12,
                        padding: 12,
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        gap: 12,
                      }}
                    >
                      <div style={{ minWidth: 0 }}>
                        <h4 style={{ fontSize: 13, color: '#ffffff', margin: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {prop.title || prop.property_type || 'Property'}
                        </h4>
                        <p style={{ fontSize: 11, color: '#a8a29e', margin: '2px 0 0 0' }}>📍 {prop.location}</p>
                        {prop.price && (
                          <p style={{ fontSize: 12, fontWeight: 700, color: '#f59e0b', margin: '3px 0 0 0' }}>
                            AED {Number(prop.price).toLocaleString()}
                          </p>
                        )}
                      </div>
                      <button
                        onClick={() => setSelectedPropForViewing(prop)}
                        className="portal-btn-ghost"
                        style={{ fontSize: 11, padding: '5px 10px', flexShrink: 0 }}
                      >
                        Request Viewing
                      </button>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* Recent Alerts Feed */}
          <div className="portal-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <h2 style={{ fontSize: 14, margin: 0, display: 'flex', alignItems: 'center', gap: 6 }}>
                <span>🔔</span> Recent Notifications
              </h2>
              <Link to="/portal/notifications" style={{ fontSize: 11, color: '#a8a29e', textDecoration: 'none' }}>
                All alerts →
              </Link>
            </div>

            {recent_notifications.length === 0 ? (
              <p style={{ fontSize: 12, color: '#78716c', fontStyle: 'italic', margin: 0 }}>No new notifications.</p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {recent_notifications.slice(0, 3).map((n) => (
                  <div
                    key={n.id}
                    style={{
                      padding: 10,
                      borderRadius: 8,
                      background: '#141211',
                      border: '1px solid #292524',
                      fontSize: 12,
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 600, color: '#ffffff', marginBottom: 3 }}>
                      <span>{n.title}</span>
                      <span style={{ fontSize: 10, color: '#78716c' }}>
                        {n.created_at ? new Date(n.created_at).toLocaleDateString() : ''}
                      </span>
                    </div>
                    <p style={{ color: '#a8a29e', margin: 0, fontSize: 11.5 }}>{n.message}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Viewing Request Modal */}
      {selectedPropForViewing && (
        <ViewingRequestModal
          property={selectedPropForViewing}
          isOpen={true}
          onClose={() => setSelectedPropForViewing(null)}
          onSuccess={() => {
            loadDashboard()
          }}
        />
      )}
    </div>
  )
}
