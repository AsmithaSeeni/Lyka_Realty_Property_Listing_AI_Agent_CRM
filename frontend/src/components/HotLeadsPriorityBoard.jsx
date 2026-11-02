import React, { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api.js'
import { useAuth, hasPerm } from '../auth/AuthContext.jsx'

export default function HotLeadsPriorityBoard() {
  const navigate = useNavigate()
  const { permissions, agent } = useAuth()
  const canReadAll = hasPerm({ permissions }, 'leads.read_all') || agent?.role === 'admin'

  const [hotLeads, setHotLeads] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filterMode, setFilterMode] = useState('all') // 'all' | 'mine' | 'unassigned'

  const fetchHotLeads = useCallback(async () => {
    try {
      setLoading(true)
      setError('')
      const params = {
        temperature: 'hot',
        limit: 20,
        sort: 'newest',
      }
      if (filterMode === 'mine' && agent?.id) {
        params.assigned_agent_id = agent.id
      } else if (filterMode === 'unassigned') {
        params.unassigned = true
      }
      const res = await api.agentLeads(params)
      setHotLeads(res.results || [])
      setTotal(res.total || (res.results ? res.results.length : 0))
    } catch (err) {
      setError(err.message || 'Failed to load hot leads')
    } finally {
      setLoading(false)
    }
  }, [filterMode, agent?.id])

  useEffect(() => {
    fetchHotLeads()
  }, [fetchHotLeads])

  const claimLead = async (e, leadId) => {
    e.stopPropagation()
    try {
      await api.assignAgentLead(leadId, { mode: 'claim' })
      fetchHotLeads()
    } catch (err) {
      alert('Failed to claim lead: ' + err.message)
    }
  }

  return (
    <div style={{
      background: 'linear-gradient(135deg, #fff5f5 0%, #fff 60%)',
      borderRadius: 12,
      border: '1.5px solid #fecaca',
      padding: '20px 24px',
      marginBottom: 24,
      boxShadow: '0 4px 12px rgba(239, 68, 68, 0.08)'
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 20 }}>🔥</span>
            <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: '#991b1b', letterSpacing: 0.2 }}>
              HOT LEADS PRIORITY BOARD
            </h2>
            <span style={{
              background: '#dc2626',
              color: '#fff',
              fontSize: 11,
              fontWeight: 700,
              padding: '2px 8px',
              borderRadius: 12,
              letterSpacing: 0.5
            }}>
              {total} URGENT
            </span>
          </div>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: '#7f1d1d' }}>
            High-intent luxury buyers and viewing requests requiring immediate same-day attention.
          </p>
        </div>

        {/* Filter Tabs */}
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <button
            type="button"
            className="btn btn-sm"
            style={{
              background: filterMode === 'all' ? '#dc2626' : '#fff',
              color: filterMode === 'all' ? '#fff' : '#7f1d1d',
              border: '1px solid #fca5a5',
              fontWeight: 600
            }}
            onClick={() => setFilterMode('all')}
          >
            All Hot ({total})
          </button>
          <button
            type="button"
            className="btn btn-sm"
            style={{
              background: filterMode === 'mine' ? '#dc2626' : '#fff',
              color: filterMode === 'mine' ? '#fff' : '#7f1d1d',
              border: '1px solid #fca5a5',
              fontWeight: 600
            }}
            onClick={() => setFilterMode('mine')}
          >
            My Assigned
          </button>
          <button
            type="button"
            className="btn btn-sm"
            style={{
              background: filterMode === 'unassigned' ? '#dc2626' : '#fff',
              color: filterMode === 'unassigned' ? '#fff' : '#7f1d1d',
              border: '1px solid #fca5a5',
              fontWeight: 600
            }}
            onClick={() => setFilterMode('unassigned')}
          >
            🏊 Unassigned Pool
          </button>
          <button
            type="button"
            className="btn btn-sm btn-ghost"
            style={{ color: '#991b1b' }}
            onClick={fetchHotLeads}
            title="Refresh hot leads"
          >
            ↻
          </button>
        </div>
      </div>

      {error && (
        <div style={{ padding: 10, background: '#fee2e2', color: '#991b1b', borderRadius: 6, fontSize: 13, marginBottom: 12 }}>
          ⚠ {error}
        </div>
      )}

      {/* Leads Grid */}
      {loading && (
        <div style={{ padding: 24, textAlign: 'center', color: '#991b1b' }}>
          <div className="ax-spin" style={{ margin: '0 auto 8px' }} />
          Scanning hot leads pipeline…
        </div>
      )}

      {!loading && hotLeads.length === 0 && (
        <div style={{
          padding: 24,
          textAlign: 'center',
          background: 'rgba(255,255,255,0.7)',
          borderRadius: 8,
          border: '1px dashed #fca5a5',
          color: '#15803d'
        }}>
          ✨ <b>All caught up!</b> No unattended hot leads currently matching this filter.
        </div>
      )}

      {!loading && hotLeads.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 14 }}>
          {hotLeads.map((l) => {
            const isUnassigned = l.assigned_agent_id == null
            const isMine = l.assigned_agent_id === agent?.id

            return (
              <div
                key={l.id}
                role="button"
                tabIndex={0}
                onClick={() => navigate(`/agent/leads/${l.id}`)}
                style={{
                  background: '#fff',
                  borderRadius: 8,
                  padding: 14,
                  border: '1px solid #fecaca',
                  boxShadow: '0 2px 6px rgba(0,0,0,0.03)',
                  cursor: 'pointer',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'space-between',
                  transition: 'transform 0.15s ease, box-shadow 0.15s ease'
                }}
              >
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
                    <div>
                      <span style={{ fontWeight: 700, fontSize: 14, color: '#0f172a' }}>
                        #{l.id} {l.name || 'Anonymous Prospect'}
                      </span>
                      <div style={{ fontSize: 12, color: '#64748b' }}>
                        {l.phone || l.email || 'No direct contact info'}
                      </div>
                    </div>
                    <span style={{
                      fontSize: 11,
                      fontWeight: 700,
                      background: '#fee2e2',
                      color: '#dc2626',
                      padding: '2px 6px',
                      borderRadius: 4
                    }}>
                      🔥 HOT {l.lead_score ? `· ${Math.round(l.lead_score)}` : ''}
                    </span>
                  </div>

                  <div style={{ fontSize: 12, color: '#334155', marginBottom: 6 }}>
                    📍 <b>{l.location || 'UAE Preferred'}</b> · {l.property_type || 'Residential'}
                    {l.bedrooms != null && ` · ${l.bedrooms} Bed`}
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11, color: '#64748b', marginBottom: 10 }}>
                    <span>Budget: <b style={{ color: '#0f172a' }}>{l.budget || 'Inquire'}</b></span>
                    <span style={{
                      fontWeight: 600,
                      color: isMine ? '#16a34a' : isUnassigned ? '#ea580c' : '#64748b'
                    }}>
                      {isMine ? '👤 Assigned to you' : isUnassigned ? '🏊 Unassigned pool' : `👤 ${l.assigned_agent_name}`}
                    </span>
                  </div>
                </div>

                {/* Action CTAs */}
                <div style={{ display: 'flex', gap: 6, borderTop: '1px solid #f1f5f9', paddingTop: 10, marginTop: 4 }}>
                  <button
                    type="button"
                    className="btn btn-sm"
                    style={{ flex: 1, fontSize: 11, background: '#fee2e2', color: '#991b1b', border: '1px solid #fca5a5' }}
                    onClick={(e) => {
                      e.stopPropagation()
                      navigate(`/agent/leads/${l.id}`)
                    }}
                  >
                    View Lead →
                  </button>
                  {isUnassigned && (
                    <button
                      type="button"
                      className="btn btn-sm btn-primary"
                      style={{ fontSize: 11, background: '#dc2626', borderColor: '#dc2626' }}
                      onClick={(e) => claimLead(e, l.id)}
                    >
                      Claim
                    </button>
                  )}
                  {l.phone && (
                    <a
                      href={`tel:${l.phone}`}
                      onClick={(e) => e.stopPropagation()}
                      className="btn btn-sm btn-ghost"
                      style={{ fontSize: 11, padding: '4px 8px' }}
                      title={`Call ${l.phone}`}
                    >
                      📞
                    </a>
                  )}
                  {l.phone && (
                    <a
                      href={`https://wa.me/${l.phone.replace(/[^0-9]/g, '')}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="btn btn-sm btn-ghost"
                      style={{ fontSize: 11, padding: '4px 8px', color: '#16a34a' }}
                      title="Open WhatsApp"
                    >
                      💬
                    </a>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

