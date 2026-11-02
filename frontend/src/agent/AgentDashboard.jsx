import React, { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth, hasPerm } from '../auth/AuthContext.jsx'
import api from '../api.js'
import HotLeadsPriorityBoard from '../components/HotLeadsPriorityBoard.jsx'

function formatAed(val) {
  if (val === null || val === undefined || isNaN(val)) return '—'
  return new Intl.NumberFormat('en-AE', {
    style: 'currency',
    currency: 'AED',
    maximumFractionDigits: 0,
  }).format(val)
}

function when(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  const diff = (Date.now() - d.getTime()) / 60000
  if (diff < 1) return 'just now'
  if (diff < 60) return `${Math.round(diff)}m ago`
  if (diff < 1440) return `${Math.round(diff / 60)}h ago`
  return d.toLocaleDateString()
}

const PERIOD_OPTIONS = [
  { key: '7d', label: '7 Days' },
  { key: '30d', label: '30 Days' },
  { key: '90d', label: '90 Days' },
  { key: 'this_month', label: 'This Month' },
  { key: 'last_month', label: 'Last Month' },
  { key: 'all', label: 'All Time' },
]

export default function AgentDashboard() {
  const navigate = useNavigate()
  const { permissions, agent, roles } = useAuth()

  const canExecutive = hasPerm({ permissions }, 'reports.read_all')
  const canManager = canExecutive || hasPerm({ permissions }, 'leads.read_all')

  // Default active tab based on role
  const defaultTab = canExecutive ? 'executive' : canManager ? 'manager' : 'agent'
  const [activeTab, setActiveTab] = useState(defaultTab)

  // Period state
  const [period, setPeriod] = useState('30d')
  const [customRange, setCustomRange] = useState({ from: '', to: '' })
  const [isCustom, setIsCustom] = useState(false)

  // Data states
  const [execData, setExecData] = useState(null)
  const [mgrData, setMgrData] = useState(null)
  const [agentData, setAgentData] = useState(null)
  const [legacyData, setLegacyData] = useState(null)

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Agent search filter in Manager view
  const [agentSearch, setAgentSearch] = useState('')

  const fetchDashboardData = useCallback(() => {
    setLoading(true)
    setError(null)

    const params = {}
    if (isCustom && customRange.from && customRange.to) {
      params.date_from = customRange.from
      params.date_to = customRange.to
    } else {
      params.period = period
    }

    const promises = [
      api.agentDashboard().then(setLegacyData).catch(() => {}),
      api.analyticsAgent(params).then(setAgentData).catch((err) => {
        console.warn('Agent analytics load failed:', err)
      }),
    ]

    if (canExecutive) {
      promises.push(
        api.analyticsExecutive(params).then(setExecData).catch((err) => {
          console.warn('Executive analytics load failed:', err)
        })
      )
    }

    if (canManager) {
      promises.push(
        api.analyticsManager(params).then(setMgrData).catch((err) => {
          console.warn('Manager analytics load failed:', err)
        })
      )
    }

    Promise.all(promises)
      .then(() => setLoading(false))
      .catch((err) => {
        setError(err.message || 'Failed to load analytics dashboard')
        setLoading(false)
      })
  }, [period, isCustom, customRange, canExecutive, canManager])

  useEffect(() => {
    fetchDashboardData()
  }, [fetchDashboardData])

  const handlePeriodChange = (p) => {
    setIsCustom(false)
    setPeriod(p)
  }

  const handleApplyCustom = (e) => {
    e.preventDefault()
    if (!customRange.from || !customRange.to) {
      setError('Both start and end dates are required')
      return
    }
    if (customRange.from > customRange.to) {
      setError('Start date must be before end date')
      return
    }
    setIsCustom(true)
  }

  const exportAgentsCsv = () => {
    const params = {}
    if (isCustom && customRange.from && customRange.to) {
      params.date_from = customRange.from
      params.date_to = customRange.to
    } else {
      params.period = period
    }
    const url = api.analyticsExportAgentsUrl(params)
    window.location.href = url
  }

  return (
    <div style={{ maxWidth: 1440, margin: '0 auto', paddingBottom: 40 }}>
      {/* Top Controls: Tabs & Period Selector */}
      <div style={{
        display: 'flex',
        flexWrap: 'wrap',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: 16,
        marginBottom: 20,
        background: 'var(--white)',
        padding: '16px 20px',
        borderRadius: 14,
        border: '1px solid var(--line)',
        boxShadow: 'var(--shadow-sm)'
      }}>
        {/* Navigation Tabs */}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {canExecutive && (
            <button
              onClick={() => setActiveTab('executive')}
              className={`ax-chip ${activeTab === 'executive' ? 'active' : ''}`}
              style={{
                cursor: 'pointer',
                background: activeTab === 'executive' ? 'var(--maroon)' : 'var(--bone)',
                color: activeTab === 'executive' ? 'var(--cream)' : 'var(--ink)',
                border: 'none',
                padding: '8px 16px',
                fontSize: 13,
                fontWeight: 600,
                borderRadius: 8,
              }}
            >
              🏛 Executive Analytics
            </button>
          )}

          {canManager && (
            <button
              onClick={() => setActiveTab('manager')}
              className={`ax-chip ${activeTab === 'manager' ? 'active' : ''}`}
              style={{
                cursor: 'pointer',
                background: activeTab === 'manager' ? 'var(--maroon)' : 'var(--bone)',
                color: activeTab === 'manager' ? 'var(--cream)' : 'var(--ink)',
                border: 'none',
                padding: '8px 16px',
                fontSize: 13,
                fontWeight: 600,
                borderRadius: 8,
              }}
            >
              👥 Team & Manager View
            </button>
          )}

          <button
            onClick={() => setActiveTab('agent')}
            className={`ax-chip ${activeTab === 'agent' ? 'active' : ''}`}
            style={{
              cursor: 'pointer',
              background: activeTab === 'agent' ? 'var(--maroon)' : 'var(--bone)',
              color: activeTab === 'agent' ? 'var(--cream)' : 'var(--ink)',
              border: 'none',
              padding: '8px 16px',
              fontSize: 13,
              fontWeight: 600,
              borderRadius: 8,
            }}
          >
            👤 My Agent Overview
          </button>
        </div>

        {/* Period Filter Buttons */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase' }}>Period:</span>
          {PERIOD_OPTIONS.map((opt) => (
            <button
              key={opt.key}
              onClick={() => handlePeriodChange(opt.key)}
              style={{
                padding: '6px 12px',
                borderRadius: 6,
                fontSize: 12,
                fontWeight: 600,
                border: '1px solid var(--line)',
                background: !isCustom && period === opt.key ? 'var(--gold)' : 'var(--soft)',
                color: !isCustom && period === opt.key ? '#2c0a1f' : 'var(--ink)',
                cursor: 'pointer',
                transition: 'all 0.15s ease'
              }}
            >
              {opt.label}
            </button>
          ))}

          {/* Custom Date Form */}
          <form onSubmit={handleApplyCustom} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginLeft: 6 }}>
            <input
              type="date"
              className="ax-input"
              style={{ padding: '4px 8px', fontSize: 12 }}
              value={customRange.from}
              onChange={(e) => setCustomRange((prev) => ({ ...prev, from: e.target.value }))}
            />
            <span style={{ fontSize: 12, color: 'var(--muted)' }}>to</span>
            <input
              type="date"
              className="ax-input"
              style={{ padding: '4px 8px', fontSize: 12 }}
              value={customRange.to}
              onChange={(e) => setCustomRange((prev) => ({ ...prev, to: e.target.value }))}
            />
            <button
              type="submit"
              className="ax-btn"
              style={{
                padding: '6px 12px',
                fontSize: 12,
                background: isCustom ? 'var(--gold)' : 'var(--maroon)',
                color: isCustom ? '#2c0a1f' : 'var(--cream)',
                border: 'none',
                borderRadius: 6,
                cursor: 'pointer',
                fontWeight: 600
              }}
            >
              Apply
            </button>
          </form>

          <button
            onClick={fetchDashboardData}
            title="Refresh analytics data"
            style={{
              background: 'none',
              border: '1px solid var(--line)',
              borderRadius: 6,
              padding: '5px 9px',
              cursor: 'pointer',
              fontSize: 13
            }}
          >
            🔄
          </button>
        </div>
      </div>

      {error && (
        <div style={{
          background: '#ffebee',
          color: '#c62828',
          padding: '12px 16px',
          borderRadius: 8,
          marginBottom: 16,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <span>⚠ {error}</span>
          <button onClick={fetchDashboardData} style={{ background: 'none', border: 'none', color: '#c62828', textDecoration: 'underline', cursor: 'pointer' }}>
            Retry
          </button>
        </div>
      )}

      {loading && !execData && !mgrData && !agentData ? (
        <div className="ax-empty">
          <div className="ax-spin" /> Loading real-time business intelligence…
        </div>
      ) : (
        <>
          {/* ========================================================= */}
          {/* TAB 1: EXECUTIVE / COMPANY-WIDE ANALYTICS                  */}
          {/* ========================================================= */}
          {activeTab === 'executive' && execData && (
            <div>
              {/* Primary KPI Grid */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                gap: 14,
                marginBottom: 24
              }}>
                <div className="ax-stat" style={{ borderLeft: '4px solid var(--maroon)' }}>
                  <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600 }}>Total Inquiries in Period</span>
                  <b style={{ fontSize: 24, display: 'block', margin: '4px 0', color: 'var(--ink)', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>
                    {execData.kpis.total_leads}
                  </b>
                  <span style={{ fontSize: 12, color: 'var(--gold-deep)' }}>
                    {execData.kpis.new_leads} new inquiries
                  </span>
                </div>

                <div className="ax-stat" style={{ borderLeft: '4px solid var(--gold)' }}>
                  <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600 }}>Lead Qualification Rate</span>
                  <b style={{ fontSize: 24, display: 'block', margin: '4px 0', color: 'var(--ink)', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>
                    {execData.kpis.qualification_rate_pct}%
                  </b>
                  <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                    {execData.kpis.qualified_leads} qualified leads
                  </span>
                </div>

                <div className="ax-stat" style={{ borderLeft: '4px solid #2e7d32' }}>
                  <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600 }}>Viewing Conversion</span>
                  <b style={{ fontSize: 24, display: 'block', margin: '4px 0', color: 'var(--ink)', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>
                    {execData.kpis.lead_to_viewing_conversion_pct}%
                  </b>
                  <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                    {execData.appointments_summary.viewings} viewings scheduled
                  </span>
                </div>

                <div className="ax-stat" style={{ borderLeft: '4px solid #1565c0' }}>
                  <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600 }}>Offer Acceptance Rate</span>
                  <b style={{ fontSize: 24, display: 'block', margin: '4px 0', color: 'var(--ink)', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>
                    {execData.kpis.offer_acceptance_rate_pct}%
                  </b>
                  <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                    {execData.offers_summary.accepted} offers accepted
                  </span>
                </div>

                <div className="ax-stat" style={{ borderLeft: '4px solid #6a1b9a' }}>
                  <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600 }}>Active Pipeline Volume</span>
                  <b style={{ fontSize: 22, display: 'block', margin: '4px 0', color: 'var(--ink)', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>
                    {formatAed(execData.kpis.active_pipeline_value_aed)}
                  </b>
                  <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                    {execData.kpis.active_deals} active transactions
                  </span>
                </div>

                <div className="ax-stat" style={{ borderLeft: '4px solid #2e7d32' }}>
                  <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600 }}>Closed Deal Volume</span>
                  <b style={{ fontSize: 22, display: 'block', margin: '4px 0', color: '#185736', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>
                    {formatAed(execData.kpis.completed_deal_value_aed)}
                  </b>
                  <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                    {execData.kpis.completed_deals} completed transactions
                  </span>
                </div>

                {/* Strictly separated Estimated vs Verified Commission */}
                <div className="ax-stat" style={{ background: '#fff9e6', borderLeft: '4px solid #f57f17' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: 12, color: '#e65100', fontWeight: 700 }}>Estimated Commission</span>
                    <span style={{ fontSize: 10, background: '#ffe082', color: '#5d4037', padding: '2px 6px', borderRadius: 4, fontWeight: 700 }}>
                      PIPELINE PROJECTION
                    </span>
                  </div>
                  <b style={{ fontSize: 22, display: 'block', margin: '4px 0', color: '#8a5800', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>
                    {formatAed(execData.kpis.estimated_commission_aed)}
                  </b>
                  <span style={{ fontSize: 11, color: '#795548' }}>Subject to deal closing & verification</span>
                </div>

                <div className="ax-stat" style={{ background: '#e8f5e9', borderLeft: '4px solid #2e7d32' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: 12, color: '#1b5e20', fontWeight: 700 }}>Verified Commission</span>
                    <span style={{ fontSize: 10, background: '#a5d6a7', color: '#1b5e20', padding: '2px 6px', borderRadius: 4, fontWeight: 700 }}>
                      REALIZED REVENUE
                    </span>
                  </div>
                  <b style={{ fontSize: 22, display: 'block', margin: '4px 0', color: '#185736', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>
                    {formatAed(execData.kpis.verified_commission_aed)}
                  </b>
                  <span style={{ fontSize: 11, color: '#185736', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>Audit-approved closed revenue</span>
                </div>
              </div>

              {/* Conversion Funnel & Stage Breakdown */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))', gap: 18, marginBottom: 24 }}>
                {/* Conversion Funnel */}
                <div className="ax-panel">
                  <div className="ax-panel__head">
                    <div>
                      <h3 style={{ margin: 0 }}>Sales Conversion Funnel</h3>
                      <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                        Progression from initial inquiry to closed transaction
                      </span>
                    </div>
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 12 }}>
                    {execData.funnel.map((step, idx) => {
                      const barWidth = Math.max(12, Math.min(100, step.overall_conversion_pct || 12))
                      return (
                        <div key={step.stage} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                            <span style={{ fontWeight: 600, color: 'var(--ink)', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>
                              {idx + 1}. {step.stage}
                            </span>
                            <span style={{ color: 'var(--muted)' }}>
                              <b>{step.count}</b> ({step.overall_conversion_pct}% of total)
                            </span>
                          </div>
                          <div style={{ height: 16, background: 'var(--bone)', borderRadius: 8, overflow: 'hidden' }}>
                            <div
                              style={{
                                height: '100%',
                                width: `${barWidth}%`,
                                background: idx === 0 ? 'var(--maroon)' : idx === execData.funnel.length - 1 ? '#2e7d32' : 'var(--gold)',
                                borderRadius: 8,
                                transition: 'width 0.4s ease',
                              }}
                            />
                          </div>
                          <span style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>{step.description}</span>
                        </div>
                      )
                    })}
                  </div>
                </div>

                {/* Deal Stages Pipeline */}
                <div className="ax-panel">
                  <div className="ax-panel__head">
                    <div>
                      <h3 style={{ margin: 0 }}>Active Deal Pipeline by Stage</h3>
                      <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                        Distribution of in-progress transactions across lifecycle
                      </span>
                    </div>
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 12 }}>
                    {Object.entries(execData.deals_summary.by_stage).map(([stage, count]) => {
                      const stageLabel = stage.replace(/_/g, ' ')
                      const maxStageCount = Math.max(1, ...Object.values(execData.deals_summary.by_stage))
                      const barPct = Math.round((count / maxStageCount) * 100)
                      return (
                        <div key={stage} style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 12.5 }}>
                          <span style={{ width: 180, textTransform: 'capitalize', color: 'var(--ink-2)', fontWeight: 500 }}>
                            {stageLabel}
                          </span>
                          <div style={{ flex: 1, height: 12, background: 'var(--bone)', borderRadius: 6, overflow: 'hidden' }}>
                            <div
                              style={{
                                height: '100%',
                                width: `${barPct}%`,
                                background: count > 0 ? 'var(--maroon-soft)' : 'transparent',
                                borderRadius: 6,
                              }}
                            />
                          </div>
                          <b style={{ width: 36, textAlign: 'right', color: 'var(--ink)', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>{count}</b>
                        </div>
                      )
                    })}
                  </div>
                </div>
              </div>

              {/* Viewing Outcomes & Property Inventory Summary */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: 18 }}>
                {/* Viewing Outcomes */}
                <div className="ax-panel">
                  <div className="ax-panel__head">
                    <h3 style={{ margin: 0 }}>Viewing Feedback & Outcomes</h3>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 10 }}>
                    {Object.entries(execData.appointments_summary.by_outcome).map(([outcome, count]) => (
                      <div key={outcome} style={{ background: 'var(--soft)', padding: '10px 12px', borderRadius: 8 }}>
                        <span style={{ fontSize: 11.5, color: 'var(--muted)', textTransform: 'capitalize', display: 'block' }}>
                          {outcome.replace(/_/g, ' ')}
                        </span>
                        <b style={{ fontSize: 18, color: 'var(--ink)', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>{count}</b>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Property Inventory Status */}
                <div className="ax-panel">
                  <div className="ax-panel__head">
                    <h3 style={{ margin: 0 }}>Property Inventory Snapshot</h3>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 10, marginTop: 10 }}>
                    <div style={{ background: 'var(--soft)', padding: '10px 12px', borderRadius: 8 }}>
                      <span style={{ fontSize: 11, color: 'var(--muted)', display: 'block' }}>Approved & Available</span>
                      <b style={{ fontSize: 18, color: '#185736', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>{execData.inventory_summary.available}</b>
                    </div>
                    <div style={{ background: 'var(--soft)', padding: '10px 12px', borderRadius: 8 }}>
                      <span style={{ fontSize: 11, color: 'var(--muted)', display: 'block' }}>Reserved</span>
                      <b style={{ fontSize: 18, color: '#f57f17' }}>{execData.inventory_summary.reserved}</b>
                    </div>
                    <div style={{ background: 'var(--soft)', padding: '10px 12px', borderRadius: 8 }}>
                      <span style={{ fontSize: 11, color: 'var(--muted)', display: 'block' }}>Sold / Rented</span>
                      <b style={{ fontSize: 18, color: 'var(--maroon)' }}>{execData.inventory_summary.sold_or_rented}</b>
                    </div>
                    <div style={{ background: 'var(--soft)', padding: '10px 12px', borderRadius: 8 }}>
                      <span style={{ fontSize: 11, color: 'var(--muted)', display: 'block' }}>Total Listings</span>
                      <b style={{ fontSize: 18, color: 'var(--ink)', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>{execData.inventory_summary.total}</b>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ========================================================= */}
          {/* TAB 2: SALES MANAGER & TEAM PERFORMANCE                  */}
          {/* ========================================================= */}
          {activeTab === 'manager' && mgrData && (
            <div>
              {/* Workload Summary Cards */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 14, marginBottom: 20 }}>
                <div className="ax-stat" style={{ borderLeft: '4px solid var(--gold)' }}>
                  <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600 }}>Unassigned Lead Pool</span>
                  <b style={{ fontSize: 24, display: 'block', margin: '4px 0', color: 'var(--ink)', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>
                    {mgrData.workload.unassigned_leads}
                  </b>
                  <button
                    onClick={() => navigate('/agent/leads')}
                    className="ax-link"
                    style={{ fontSize: 12 }}
                  >
                    Assign leads →
                  </button>
                </div>

                <div className="ax-stat" style={{ borderLeft: '4px solid var(--maroon)' }}>
                  <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600 }}>Total Active Team Leads</span>
                  <b style={{ fontSize: 24, display: 'block', margin: '4px 0', color: 'var(--ink)', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>
                    {mgrData.workload.total_active_leads}
                  </b>
                  <span style={{ fontSize: 12, color: 'var(--muted)' }}>Across 20 agents</span>
                </div>

                <div className="ax-stat" style={{ borderLeft: '4px solid #d32f2f' }}>
                  <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600 }}>Overdue Team Follow-ups</span>
                  <b style={{ fontSize: 24, display: 'block', margin: '4px 0', color: '#8b1e3f', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>
                    {mgrData.workload.overdue_team_followups}
                  </b>
                  <span style={{ fontSize: 12, color: 'var(--muted)' }}>Action required</span>
                </div>

                <div className="ax-stat" style={{ borderLeft: '4px solid #1976d2' }}>
                  <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600 }}>Upcoming Team Appointments</span>
                  <b style={{ fontSize: 24, display: 'block', margin: '4px 0', color: '#1565c0', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>
                    {mgrData.workload.upcoming_team_appointments}
                  </b>
                  <button
                    onClick={() => navigate('/agent/appointments')}
                    className="ax-link"
                    style={{ fontSize: 12 }}
                  >
                    View schedule →
                  </button>
                </div>
              </div>

              {/* Agent Performance Table with CSV Export */}
              <div className="ax-panel" style={{ marginBottom: 24 }}>
                <div className="ax-panel__head" style={{ flexWrap: 'wrap', gap: 12 }}>
                  <div>
                    <h3 style={{ margin: 0 }}>Agent Performance & Workload Breakdown</h3>
                    <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                      Individual KPIs, pipeline progression and verified commission across sales team
                    </span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <input
                      type="text"
                      className="ax-input"
                      placeholder="Search agent name or email…"
                      value={agentSearch}
                      onChange={(e) => setAgentSearch(e.target.value)}
                      style={{ minWidth: 220, fontSize: 12.5 }}
                    />
                    {canExecutive && (
                      <button
                        onClick={exportAgentsCsv}
                        className="ax-btn"
                        style={{
                          background: 'var(--maroon)',
                          color: 'var(--cream)',
                          border: 'none',
                          padding: '8px 14px',
                          borderRadius: 6,
                          fontSize: 12.5,
                          fontWeight: 600,
                          cursor: 'pointer',
                        }}
                      >
                        📥 Export Performance (CSV)
                      </button>
                    )}
                  </div>
                </div>

                <div style={{ overflowX: 'auto', marginTop: 12 }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, textAlign: 'left' }}>
                    <thead>
                      <tr style={{ background: 'var(--soft)', borderBottom: '2px solid var(--line)' }}>
                        <th style={{ padding: '10px 12px' }}>Agent</th>
                        <th style={{ padding: '10px 12px' }}>Role</th>
                        <th style={{ padding: '10px 12px' }}>Assigned</th>
                        <th style={{ padding: '10px 12px' }}>Active</th>
                        <th style={{ padding: '10px 12px' }}>Qualified</th>
                        <th style={{ padding: '10px 12px' }}>Viewings</th>
                        <th style={{ padding: '10px 12px' }}>Offers</th>
                        <th style={{ padding: '10px 12px' }}>Active Deals</th>
                        <th style={{ padding: '10px 12px' }}>Closed Deals</th>
                        <th style={{ padding: '10px 12px' }}>Est. Comm</th>
                        <th style={{ padding: '10px 12px' }}>Verified Comm</th>
                        <th style={{ padding: '10px 12px' }}>Overdue</th>
                      </tr>
                    </thead>
                    <tbody>
                      {mgrData.agents
                        .filter(
                          (ag) =>
                            !agentSearch ||
                            ag.name.toLowerCase().includes(agentSearch.toLowerCase()) ||
                            ag.email.toLowerCase().includes(agentSearch.toLowerCase())
                        )
                        .map((ag) => (
                          <tr key={ag.agent_id} style={{ borderBottom: '1px solid var(--line)' }}>
                            <td style={{ padding: '10px 12px' }}>
                              <b>{ag.name}</b>
                              <span style={{ display: 'block', fontSize: 11, color: 'var(--muted)' }}>{ag.email}</span>
                            </td>
                            <td style={{ padding: '10px 12px' }}>
                              <span style={{ fontSize: 11, background: 'var(--bone)', padding: '2px 6px', borderRadius: 4 }}>
                                {ag.role}
                              </span>
                            </td>
                            <td style={{ padding: '10px 12px' }}>{ag.assigned_leads_in_period}</td>
                            <td style={{ padding: '10px 12px' }}>{ag.active_leads}</td>
                            <td style={{ padding: '10px 12px' }}>
                              {ag.qualified_leads} <span style={{ fontSize: 11, color: 'var(--muted)' }}>({ag.qualification_rate_pct}%)</span>
                            </td>
                            <td style={{ padding: '10px 12px' }}>{ag.viewings_conducted}</td>
                            <td style={{ padding: '10px 12px' }}>
                              {ag.offers_created} <span style={{ fontSize: 11, color: '#185736', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>({ag.offers_accepted} acc)</span>
                            </td>
                            <td style={{ padding: '10px 12px' }}>{ag.active_deals}</td>
                            <td style={{ padding: '10px 12px' }}>
                              <b>{ag.completed_deals}</b> <span style={{ fontSize: 11, color: 'var(--muted)' }}>({ag.closing_rate_pct}%)</span>
                            </td>
                            <td style={{ padding: '10px 12px', color: '#bf360c', fontWeight: 600 }}>
                              {formatAed(ag.estimated_commission_aed)}
                            </td>
                            <td style={{ padding: '10px 12px', color: '#1b5e20', fontWeight: 700 }}>
                              {formatAed(ag.verified_commission_aed)}
                            </td>
                            <td style={{ padding: '10px 12px' }}>
                              {ag.overdue_followups > 0 ? (
                                <span style={{ color: '#d32f2f', fontWeight: 700 }}>{ag.overdue_followups}</span>
                              ) : (
                                <span style={{ color: 'var(--muted)' }}>0</span>
                              )}
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Stalled Items & Approaching Deadlines */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))', gap: 18 }}>
                {/* Stalled Items */}
                <div className="ax-panel">
                  <div className="ax-panel__head">
                    <h3 style={{ margin: 0 }}>⚠️ Stalled Leads & Deals (&gt; 14 Days Inactive)</h3>
                  </div>

                  <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {mgrData.stalled_leads.length === 0 && mgrData.stalled_deals.length === 0 ? (
                      <div className="ax-muted">No stalled leads or transactions detected.</div>
                    ) : (
                      <>
                        {mgrData.stalled_leads.map((l) => (
                          <div
                            key={`lead-${l.id}`}
                            onClick={() => navigate(`/agent/leads/${l.id}`)}
                            style={{
                              display: 'flex',
                              justifyContent: 'space-between',
                              alignItems: 'center',
                              padding: '8px 12px',
                              background: 'var(--soft)',
                              borderRadius: 6,
                              cursor: 'pointer',
                            }}
                          >
                            <div>
                              <b>{l.name}</b>
                              <span style={{ fontSize: 11, color: 'var(--muted)', display: 'block' }}>
                                Assigned: {l.assigned_agent_name} · Stage: {l.status}
                              </span>
                            </div>
                            <span style={{ fontSize: 11, background: '#ffcdd2', color: '#b71c1c', padding: '3px 7px', borderRadius: 4, fontWeight: 700 }}>
                              {l.days_stalled}d inactive
                            </span>
                          </div>
                        ))}

                        {mgrData.stalled_deals.map((d) => (
                          <div
                            key={`deal-${d.id}`}
                            onClick={() => navigate('/agent/deals')}
                            style={{
                              display: 'flex',
                              justifyContent: 'space-between',
                              alignItems: 'center',
                              padding: '8px 12px',
                              background: 'var(--soft)',
                              borderRadius: 6,
                              cursor: 'pointer',
                            }}
                          >
                            <div>
                              <b>{d.deal_reference}</b> ({formatAed(d.agreed_amount)})
                              <span style={{ fontSize: 11, color: 'var(--muted)', display: 'block' }}>
                                Agent: {d.assigned_agent_name} · Stage: {d.status}
                              </span>
                            </div>
                            <span style={{ fontSize: 11, background: '#ffe0b2', color: '#e65100', padding: '3px 7px', borderRadius: 4, fontWeight: 700 }}>
                              {d.days_stalled}d inactive
                            </span>
                          </div>
                        ))}
                      </>
                    )}
                  </div>
                </div>

                {/* Approaching Deadlines */}
                <div className="ax-panel">
                  <div className="ax-panel__head">
                    <h3 style={{ margin: 0 }}>⏱ Deals Approaching Target Completion</h3>
                  </div>

                  <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {mgrData.approaching_deadlines.length === 0 ? (
                      <div className="ax-muted">No transactions approaching target closing within 30 days.</div>
                    ) : (
                      mgrData.approaching_deadlines.map((d) => (
                        <div
                          key={`deadline-${d.id}`}
                          onClick={() => navigate('/agent/deals')}
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            padding: '8px 12px',
                            background: 'var(--soft)',
                            borderRadius: 6,
                            cursor: 'pointer',
                          }}
                        >
                          <div>
                            <b>{d.deal_reference}</b> ({formatAed(d.agreed_amount)})
                            <span style={{ fontSize: 11, color: 'var(--muted)', display: 'block' }}>
                              Agent: {d.assigned_agent_name} · Target: {new Date(d.target_completion_date).toLocaleDateString()}
                            </span>
                          </div>
                          <span style={{
                            fontSize: 11,
                            background: d.days_remaining <= 7 ? '#ffcdd2' : '#e8f5e9',
                            color: d.days_remaining <= 7 ? '#b71c1c' : '#2e7d32',
                            padding: '3px 7px',
                            borderRadius: 4,
                            fontWeight: 700,
                          }}>
                            {d.days_remaining <= 0 ? 'Due now' : `${d.days_remaining}d left`}
                          </span>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ========================================================= */}
          {/* TAB 3: INDIVIDUAL AGENT OVERVIEW & ACTION ITEMS           */}
          {/* ========================================================= */}
          {activeTab === 'agent' && agentData && (
            <div>
              {/* Personal Action Items Grid */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 14, marginBottom: 20 }}>
                <div className="ax-stat" style={{ borderLeft: '4px solid #f57f17' }}>
                  <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600 }}>New Leads Requiring Action</span>
                  <b style={{ fontSize: 24, display: 'block', margin: '4px 0', color: 'var(--ink)', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>
                    {agentData.action_items.new_leads_requiring_action}
                  </b>
                  <button onClick={() => navigate('/agent/leads')} className="ax-link" style={{ fontSize: 12 }}>
                    Open lead queue →
                  </button>
                </div>

                <div className="ax-stat" style={{ borderLeft: '4px solid #1976d2' }}>
                  <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600 }}>Today's Appointments</span>
                  <b style={{ fontSize: 24, display: 'block', margin: '4px 0', color: '#1565c0', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>
                    {agentData.action_items.today_appointments_count}
                  </b>
                  <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                    {agentData.action_items.upcoming_appointments_count} upcoming
                  </span>
                </div>

                <div className="ax-stat" style={{ borderLeft: '4px solid #d32f2f' }}>
                  <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600 }}>Follow-ups Overdue</span>
                  <b style={{ fontSize: 24, display: 'block', margin: '4px 0', color: '#8b1e3f', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>
                    {agentData.action_items.overdue_followups_count}
                  </b>
                  <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                    {agentData.action_items.due_today_followups_count} due today
                  </span>
                </div>

                <div className="ax-stat" style={{ background: '#fff9e6', borderLeft: '4px solid #f57f17' }}>
                  <span style={{ fontSize: 12, color: '#e65100', fontWeight: 700 }}>My Pipeline Commission</span>
                  <b style={{ fontSize: 22, display: 'block', margin: '4px 0', color: '#8a5800', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>
                    {formatAed(agentData.pipeline.estimated_commission_aed)}
                  </b>
                  <span style={{ fontSize: 11, color: '#795548' }}>Estimated in progress</span>
                </div>

                <div className="ax-stat" style={{ background: '#e8f5e9', borderLeft: '4px solid #2e7d32' }}>
                  <span style={{ fontSize: 12, color: '#1b5e20', fontWeight: 700 }}>My Verified Commission</span>
                  <b style={{ fontSize: 22, display: 'block', margin: '4px 0', color: '#185736', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>
                    {formatAed(agentData.pipeline.verified_commission_aed)}
                  </b>
                  <span style={{ fontSize: 11, color: '#185736', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>Earned on closed deals</span>
                </div>
              </div>

              {/* Viewings Awaiting Feedback & Offers Awaiting Action */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))', gap: 18, marginBottom: 24 }}>
                {/* Viewings Awaiting Outcome */}
                <div className="ax-panel">
                  <div className="ax-panel__head">
                    <h3 style={{ margin: 0 }}>Viewings Awaiting Outcome Feedback</h3>
                    <button onClick={() => navigate('/agent/appointments')} className="ax-link">
                      All Appointments →
                    </button>
                  </div>

                  <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {agentData.action_items.viewings_awaiting_feedback.length === 0 ? (
                      <div className="ax-muted">All past viewings have outcomes recorded.</div>
                    ) : (
                      agentData.action_items.viewings_awaiting_feedback.map((v) => (
                        <div
                          key={v.id}
                          onClick={() => navigate('/agent/appointments')}
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            padding: '10px 12px',
                            background: 'var(--soft)',
                            borderRadius: 8,
                            cursor: 'pointer',
                          }}
                        >
                          <div>
                            <b>{v.property_title || `Viewing #${v.id}`}</b>
                            <span style={{ fontSize: 11.5, color: 'var(--muted)', display: 'block' }}>
                              Lead #{v.lead_id} · {new Date(v.start_at).toLocaleString()}
                            </span>
                          </div>
                          <span style={{ fontSize: 11, background: '#ffe0b2', color: '#e65100', padding: '3px 8px', borderRadius: 4, fontWeight: 700 }}>
                            Feedback needed
                          </span>
                        </div>
                      ))
                    )}
                  </div>
                </div>

                {/* Offers Awaiting Response */}
                <div className="ax-panel">
                  <div className="ax-panel__head">
                    <h3 style={{ margin: 0 }}>Offers Awaiting Response</h3>
                    <button onClick={() => navigate('/agent/deals')} className="ax-link">
                      Deals & Offers →
                    </button>
                  </div>

                  <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {agentData.action_items.offers_awaiting_response.length === 0 ? (
                      <div className="ax-muted">No pending submitted offers awaiting response.</div>
                    ) : (
                      agentData.action_items.offers_awaiting_response.map((o) => (
                        <div
                          key={o.id}
                          onClick={() => navigate('/agent/deals')}
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            padding: '10px 12px',
                            background: 'var(--soft)',
                            borderRadius: 8,
                            cursor: 'pointer',
                          }}
                        >
                          <div>
                            <b>Offer #{o.id}: {formatAed(o.current_price || o.offered_price)}</b>
                            <span style={{ fontSize: 11.5, color: 'var(--muted)', display: 'block' }}>
                              Lead #{o.lead_id} · Status: {o.status}
                            </span>
                          </div>
                          <span style={{ fontSize: 11, background: '#e3f2fd', color: '#1565c0', padding: '3px 8px', borderRadius: 4, fontWeight: 700 }}>
                            {o.status}
                          </span>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>

              {/* Personal Conversion Rates & Active Stages */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: 18, marginBottom: 24 }}>
                <div className="ax-panel">
                  <div className="ax-panel__head">
                    <h3 style={{ margin: 0 }}>My Conversion Performance</h3>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 10 }}>
                    <div style={{ background: 'var(--soft)', padding: '12px 14px', borderRadius: 8 }}>
                      <span style={{ fontSize: 12, color: 'var(--muted)', display: 'block' }}>Qualification Rate</span>
                      <b style={{ fontSize: 22, color: 'var(--maroon)' }}>{agentData.pipeline.qualification_rate_pct}%</b>
                    </div>
                    <div style={{ background: 'var(--soft)', padding: '12px 14px', borderRadius: 8 }}>
                      <span style={{ fontSize: 12, color: 'var(--muted)', display: 'block' }}>Deal Closing Rate</span>
                      <b style={{ fontSize: 22, color: '#185736', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>{agentData.pipeline.closing_rate_pct}%</b>
                    </div>
                  </div>
                </div>

                <div className="ax-panel">
                  <div className="ax-panel__head">
                    <h3 style={{ margin: 0 }}>My Active Deals by Stage</h3>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 10 }}>
                    {Object.entries(agentData.pipeline.deals_by_stage).map(([stg, count]) => (
                      <div key={stg} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, borderBottom: '1px solid var(--line)', paddingBottom: 4 }}>
                        <span style={{ textTransform: 'capitalize', color: 'var(--ink)', fontFamily: 'var(--display)', fontVariantNumeric: 'tabular-nums' }}>{stg.replace(/_/g, ' ')}</span>
                        <b>{count}</b>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Recent Leads & Recent Conversations from Legacy CRM Home */}
              {legacyData && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))', gap: 18 }}>
                  {/* Recent Leads */}
                  <div className="ax-panel">
                    <div className="ax-panel__head">
                      <h3 style={{ margin: 0 }}>Recent Leads</h3>
                      <button onClick={() => navigate('/agent/leads')} className="ax-link">
                        All Leads →
                      </button>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
                      {(legacyData.recent_leads || []).slice(0, 5).map((l) => (
                        <div
                          key={l.id}
                          onClick={() => navigate(`/agent/leads/${l.id}`)}
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            padding: '8px 10px',
                            background: 'var(--soft)',
                            borderRadius: 6,
                            cursor: 'pointer',
                          }}
                        >
                          <div>
                            <b>{l.name || 'Anonymous Lead'}</b>
                            <span style={{ fontSize: 11, color: 'var(--muted)', display: 'block' }}>
                              {l.phone || l.email || 'No contact'} · {l.status}
                            </span>
                          </div>
                          <span style={{ fontSize: 11, color: 'var(--muted)' }}>{when(l.last_interaction_at || l.created_at)}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Recent Conversations */}
                  <div className="ax-panel">
                    <div className="ax-panel__head">
                      <h3 style={{ margin: 0 }}>Recent Conversations</h3>
                      <button onClick={() => navigate('/agent/conversations')} className="ax-link">
                        All Chats →
                      </button>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
                      {(legacyData.recent_conversations || []).slice(0, 5).map((c) => (
                        <div
                          key={c.id}
                          onClick={() => navigate('/agent/conversations')}
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            padding: '8px 10px',
                            background: 'var(--soft)',
                            borderRadius: 6,
                            cursor: 'pointer',
                          }}
                        >
                          <div style={{ minWidth: 0, flex: 1, marginRight: 10 }}>
                            <b>{c.customer_name || `Chat #${c.id}`}</b>
                            <span
                              style={{
                                fontSize: 11,
                                color: 'var(--muted)',
                                display: 'block',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                              }}
                            >
                              {c.last_message_preview || 'No messages'}
                            </span>
                          </div>
                          <span style={{ fontSize: 11, color: 'var(--muted)', whiteSpace: 'nowrap' }}>{when(c.updated_at)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
