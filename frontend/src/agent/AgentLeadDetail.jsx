import React from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import api from '../api.js'
import { useAuth, hasPerm } from '../auth/AuthContext.jsx'
import { STATUSES, statusLabel, priorityLabel, fmtDate, temperatureLabel } from './AgentLeads.jsx'
import { adaptProperty } from '../utils/propertyAdapter.js'
import ErrorBoundary from '../components/ui/ErrorBoundary.jsx'

/**
 * Safely format audit log event detail for display.
 * Handles plain text, JSON strings, JSON objects, arrays, and null/empty.
 * Guarantees zero character-indexing artifacts and masks sensitive values.
 */
export function formatAuditDetail(detail) {
  if (!detail) return null

  const isSensitive = (k) => /password|token|secret|hash|authorization|cookie|session/i.test(String(k))

  let parsed = detail
  if (typeof detail === 'string') {
    const trimmed = detail.trim()
    if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
      try {
        parsed = JSON.parse(trimmed)
      } catch {
        parsed = detail
      }
    } else {
      parsed = detail
    }
  }

  if (typeof parsed === 'string') {
    if (isSensitive(parsed)) return '[REDACTED]'
    return parsed
  }

  if (Array.isArray(parsed)) {
    return parsed
      .map((item) => (typeof item === 'object' && item !== null ? JSON.stringify(item) : String(item)))
      .join(', ')
  }

  if (typeof parsed === 'object' && parsed !== null) {
    const entries = Object.entries(parsed).filter(([k]) => !isSensitive(k))
    if (entries.length === 0) return null
    return entries
      .map(([k, v]) => {
        let displayVal
        if (v === null || v === undefined) {
          displayVal = '—'
        } else if (typeof v === 'object') {
          displayVal = JSON.stringify(v)
        } else {
          displayVal = String(v)
        }
        return `${k}: ${displayVal}`
      })
      .join(', ')
  }

  return String(parsed)
}

const INTENTS = [['buy', 'Buy'], ['rent', 'Rent'], ['lease', 'Lease'], ['unknown', 'Unknown']]
const PERIODS = [
  ['', '— none —'], ['monthly', 'Per month'], ['yearly', 'Per year'],
  ['one_time', 'One time'],
]
const EMIRATES = [
  ['', '— none —'], ['Dubai', 'Dubai'], ['Abu Dhabi', 'Abu Dhabi'],
  ['Sharjah', 'Sharjah'], ['Ajman', 'Ajman'], ['Ras Al Khaimah', 'Ras Al Khaimah'],
  ['Fujairah', 'Fujairah'], ['Umm Al Quwain', 'Umm Al Quwain'],
]
const INVESTMENT_PURPOSES = [
  ['', '— none —'],
  ['end_use', 'End use / Family living'],
  ['investment', 'Investment / Rental yield'],
  ['holiday_home', 'Holiday home'],
  ['commercial', 'Commercial'],
]
const FINANCING_TYPES = [
  ['', '— none —'],
  ['cash', 'Cash buyer'],
  ['mortgage_preapproved', 'Mortgage (pre-approved)'],
  ['mortgage_needed', 'Mortgage (needs assistance)'],
  ['payment_plan', 'Developer payment plan'],
  ['undecided', 'Undecided'],
]

function propEmoji(type) {
  const t = String(type || '')
  if (/villa/i.test(t)) return '🏡'
  if (/townhouse/i.test(t)) return '🏘️'
  if (/penthouse/i.test(t)) return '🌆'
  if (/plot|land/i.test(t)) return '🗺️'
  return '🏢'
}

function MsgBubble({ m }) {
  const time = m.created_at ? new Date(m.created_at).toLocaleString([], {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
  }) : ''
  const isUser = m.role === 'user'
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: isUser ? 'flex-end' : 'flex-start',
        marginBottom: 16,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4, fontSize: 12, color: '#64748b' }}>
        <b style={{ color: isUser ? '#1e293b' : '#5a1645' }}>{isUser ? 'Customer' : 'LykAI Concierge'}</b>
        <span>{time}</span>
        {m.message_type === 'voice' && <span style={{ color: '#0284c7', fontWeight: 600 }}>🎙 Voice</span>}
        {m.detected_language && m.detected_language !== 'en' && (
          <span style={{ background: '#f1f5f9', padding: '1px 6px', borderRadius: 4 }}>{m.detected_language}</span>
        )}
      </div>
      <div
        style={{
          maxWidth: '75%',
          padding: '12px 18px',
          borderRadius: 14,
          fontSize: 13.5,
          lineHeight: 1.55,
          background: isUser ? '#2c0f20' : '#ffffff',
          color: isUser ? '#ffffff' : '#1e293b',
          border: isUser ? 'none' : '1px solid #e2e8f0',
          borderLeft: isUser ? 'none' : '3px solid #d4af37',
          boxShadow: '0 2px 8px -2px rgba(0,0,0,0.06)',
          whiteSpace: 'pre-wrap',
        }}
      >
        {m.content}
      </div>
    </div>
  )
}

/** lead row → editable form values (strings for inputs) */
function formFromLead(l) {
  const s = (v) => (v == null || v === 'Not provided' ? '' : String(v))
  return {
    name: l.name === 'Not provided' ? '' : (l.name || ''),
    phone: l.phone === 'Not provided' ? '' : (l.phone || ''),
    email: l.email === 'Not provided' ? '' : (l.email || ''),
    preferred_language: s(l.preferred_language),
    intent: l.buy_rent && l.buy_rent !== 'Not provided' ? l.buy_rent : 'unknown',
    emirate: s(l.emirate),
    location: l.location === 'Not provided' ? '' : (l.location || ''),
    property_type: l.property_type === 'Not provided' ? '' : (l.property_type || ''),
    bedrooms: s(l.bedrooms),
    bathrooms: s(l.bathrooms),
    budget_min: s(l.budget_min),
    budget_max: s(l.budget_max),
    budget_currency: l.budget_currency || '',
    budget_period: l.budget_period || '',
    investment_purpose: s(l.investment_purpose),
    financing_type: s(l.financing_type),
    preferred_viewing_time: s(l.preferred_viewing_time),
    next_action: s(l.next_action),
    amenities: (l.amenities || []).join(', '),
    preferences: (l.preferences || []).join(', '),
    timeline: l.timeline === 'Not provided' ? '' : (l.timeline || ''),
    timeline_days: s(l.timeline_days),
  }
}

function ValueOrEmpty({ value, placeholder = 'Not yet specified' }) {
  if (!value || value === 'Not provided' || value === '— none —') {
    return <span style={{ color: '#94a3b8', fontStyle: 'italic', fontSize: 13 }}>{placeholder}</span>
  }
  return <span style={{ color: '#1e293b', fontWeight: 600 }}>{String(value)}</span>
}

function AgentLeadDetailView() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { permissions, agent: currentAgent } = useAuth()
  const canAssign = hasPerm({ permissions }, 'leads.assign') || currentAgent?.role === 'admin'
  const [tempBusy, setTempBusy] = React.useState(false)

  // Tab navigation state: 'overview' | 'activity' | 'properties' | 'conversations'
  const [activeTab, setActiveTab] = React.useState('overview')

  const [data, setData] = React.useState(null)
  const [error, setError] = React.useState(null)
  const [notes, setNotes] = React.useState('')
  const [savingNotes, setSavingNotes] = React.useState(false)
  const [status, setStatus] = React.useState('new')

  // Edit lead modal
  const [edit, setEdit] = React.useState(null)
  const [editOpen, setEditOpen] = React.useState(false)
  const [savingEdit, setSavingEdit] = React.useState(false)
  const [editError, setEditError] = React.useState('')

  // Sales agents
  const [salesAgents, setSalesAgents] = React.useState([])
  const [assignBusy, setAssignBusy] = React.useState(false)
  const [selectedAgentId, setSelectedAgentId] = React.useState('')

  // Follow-up modal
  const [fuForm, setFuForm] = React.useState({ type: 'call', due: '', priority: 'normal', notes: '' })
  const [fuBusy, setFuBusy] = React.useState(false)

  // Matching
  const [matching, setMatching] = React.useState(false)
  const [matchResult, setMatchResult] = React.useState(null)
  const [matchError, setMatchError] = React.useState('')

  // Property linking
  const [propQuery, setPropQuery] = React.useState('')
  const [propOptions, setPropOptions] = React.useState([])
  const [propPickId, setPropPickId] = React.useState('')
  const [linkingProp, setLinkingProp] = React.useState(false)
  const [propLinkMsg, setPropLinkMsg] = React.useState('')

  const [mergingId, setMergingId] = React.useState(null)

  const inFlightLeadRef = React.useRef(false)

  const load = React.useCallback((silent = false) => {
    if (!silent) setError(null)
    return api
      .agentLead(id)
      .then((d) => {
        setData(d)
        setNotes(d.lead.notes || '')
        setStatus(d.lead.status)
        setEdit(formFromLead(d.lead))
        setSelectedAgentId(d.lead.assigned_agent_id ? String(d.lead.assigned_agent_id) : '')
      })
      .catch((e) => {
        if (!silent) setError(e.message)
      })
  }, [id])

  React.useEffect(() => {
    load()
  }, [load])

  // Real-time incremental synchronization: poll when document is visible
  React.useEffect(() => {
    const interval = setInterval(async () => {
      if (document.hidden || inFlightLeadRef.current) return
      inFlightLeadRef.current = true
      try {
        await load(true)
      } finally {
        inFlightLeadRef.current = false
      }
    }, 3500)
    return () => clearInterval(interval)
  }, [load])

  React.useEffect(() => {
    api.agentSalesAgents().then((r) => setSalesAgents(r.results || [])).catch(() => {})
  }, [])

  const searchProperties = React.useCallback((qText = '') => {
    api
      .agentProperties({
        is_approved: true,
        availability: 'available',
        q: qText,
        limit: 20,
      })
      .then((r) => setPropOptions(r.results || r.items || []))
      .catch(() => {})
  }, [])

  React.useEffect(() => {
    searchProperties('')
  }, [searchProperties])

  const changeTemperature = async (newTemp) => {
    setTempBusy(true)
    try {
      const res = await api.updateAgentLead(id, { temperature: newTemp })
      if (res && res.lead) {
        setData((prev) => (prev ? { ...prev, lead: res.lead } : prev))
        setEdit((prev) => (prev ? { ...prev, ...formFromLead(res.lead) } : prev))
      }
    } catch (e) {
      alert('Failed to update temperature: ' + (e?.message || 'Server error'))
    } finally {
      setTempBusy(false)
    }
  }

  const saveNotes = async () => {
    setSavingNotes(true)
    try {
      await api.updateAgentLead(id, { notes })
      load(true)
      alert('Internal notes saved.')
    } catch (e) {
      alert('Could not save notes: ' + e.message)
    } finally {
      setSavingNotes(false)
    }
  }

  const changeStatus = async (next) => {
    const prev = status
    const isReopen = (prev === 'closed_won' || prev === 'closed_lost') && next !== prev
    let reason = null
    if (isReopen) {
      reason = window.prompt(
        `Reopening closed lead #${id} from ${statusLabel(prev)} to ${statusLabel(next)}. Enter reason:`,
        'Customer re-opened enquiry'
      )
      if (reason === null) return
    }
    setStatus(next)
    try {
      await api.transitionLeadStatus(id, {
        status: next,
        reopen: isReopen,
        reason: reason || null,
      })
      load()
    } catch (e) {
      setStatus(prev)
      alert('Could not update status: ' + e.message)
    }
  }

  const runAssign = async (mode, agentIdVal = null) => {
    setAssignBusy(true)
    try {
      await api.assignAgentLead(id, {
        mode,
        assigned_agent_id: agentIdVal != null && agentIdVal !== '' ? Number(agentIdVal) : null,
      })
      load()
      api.agentSalesAgents().then((r) => setSalesAgents(r.results || [])).catch(() => {})
    } catch (e) {
      alert('Assignment error: ' + e.message)
    } finally {
      setAssignBusy(false)
    }
  }

  const handleMergeDuplicate = async (dup) => {
    if (!window.confirm(`Merge duplicate lead #${dup.id} (${dup.name}) into this lead #${id}? All notes, conversations, follow-ups, and recommendations will be preserved.`)) {
      return
    }
    setMergingId(dup.id)
    try {
      await api.mergeAgentLead(id, {
        source_lead_id: dup.id,
        reason: `Merged duplicate lead #${dup.id} into #${id}`,
      })
      load()
    } catch (e) {
      alert('Merge failed: ' + e.message)
    } finally {
      setMergingId(null)
    }
  }

  const saveEdit = async () => {
    if (!edit || !data) return
    const l = data.lead
    const s = (v) => (v || '').trim()
    const n = (v) => (v === '' ? null : Number(v))
    const L = (v) => v.split(',').map((x) => x.trim()).filter(Boolean)
    const sameList = (a, b) => JSON.stringify(a) === JSON.stringify(b || [])
    const cleanOrig = (v) => (v === 'Not provided' || v == null ? '' : String(v))

    const patch = {}
    if (s(edit.name) !== cleanOrig(l.name)) patch.name = s(edit.name)
    if (s(edit.phone) !== cleanOrig(l.phone)) patch.phone = s(edit.phone)
    if (s(edit.email) !== cleanOrig(l.email)) patch.email = s(edit.email)
    if (s(edit.preferred_language) !== cleanOrig(l.preferred_language)) patch.preferred_language = s(edit.preferred_language)
    if (edit.intent !== l.buy_rent) patch.buy_rent = edit.intent
    if (s(edit.emirate) !== cleanOrig(l.emirate)) patch.emirate = s(edit.emirate)
    if (s(edit.location) !== cleanOrig(l.location)) patch.location = s(edit.location)
    if (s(edit.property_type) !== cleanOrig(l.property_type)) patch.property_type = s(edit.property_type)
    if (n(edit.bedrooms) !== l.bedrooms) patch.bedrooms = n(edit.bedrooms)
    if (n(edit.bathrooms) !== l.bathrooms) patch.bathrooms = n(edit.bathrooms)
    if (n(edit.budget_min) !== l.budget_min) patch.budget_min = n(edit.budget_min)
    if (n(edit.budget_max) !== l.budget_max) patch.budget_max = n(edit.budget_max)
    if (edit.budget_currency !== (l.budget_currency || '')) patch.budget_currency = edit.budget_currency
    if (edit.budget_period !== (l.budget_period || '')) patch.budget_period = edit.budget_period
    if (s(edit.investment_purpose) !== cleanOrig(l.investment_purpose)) patch.investment_purpose = s(edit.investment_purpose)
    if (s(edit.financing_type) !== cleanOrig(l.financing_type)) patch.financing_type = s(edit.financing_type)
    if (s(edit.preferred_viewing_time) !== cleanOrig(l.preferred_viewing_time)) patch.preferred_viewing_time = s(edit.preferred_viewing_time)
    if (s(edit.next_action) !== cleanOrig(l.next_action)) patch.next_action = s(edit.next_action)
    if (s(edit.timeline) !== cleanOrig(l.timeline)) patch.timeline = s(edit.timeline)
    if (n(edit.timeline_days) !== l.timeline_days) patch.timeline_days = n(edit.timeline_days)
    if (!sameList(L(edit.amenities), l.amenities)) patch.amenities = L(edit.amenities)
    if (!sameList(L(edit.preferences), l.preferences)) patch.preferences = L(edit.preferences)

    if (Object.keys(patch).length === 0) {
      setEditOpen(false)
      return
    }

    setSavingEdit(true)
    setEditError('')
    try {
      await api.updateAgentLead(id, patch)
      setEditOpen(false)
      load()
    } catch (e) {
      setEditError(e.message || 'Could not save changes.')
    } finally {
      setSavingEdit(false)
    }
  }

  const handleAddFollowup = async (e) => {
    e.preventDefault()
    if (!fuForm.due) {
      alert('Please select a due date and time.')
      return
    }
    setFuBusy(true)
    try {
      await api.createLeadFollowup(id, {
        type: fuForm.type,
        due_at: new Date(fuForm.due).toISOString(),
        priority: fuForm.priority,
        notes: fuForm.notes,
      })
      setFuForm({ type: 'call', due: '', priority: 'normal', notes: '' })
      load()
    } catch (err) {
      alert('Could not schedule follow-up: ' + err.message)
    } finally {
      setFuBusy(false)
    }
  }

  const handleCompleteFollowup = async (fuId) => {
    try {
      await api.updateLeadFollowup(fuId, { completed: true })
      load()
    } catch (err) {
      alert('Could not update follow-up: ' + err.message)
    }
  }

  const handleCancelFollowup = async (fuId) => {
    const reason = window.prompt('Reason for cancelling this follow-up:', 'Customer rescheduled')
    if (reason === null) return
    try {
      await api.cancelLeadFollowup(fuId, { cancellation_reason: reason })
      load()
    } catch (err) {
      alert('Could not cancel follow-up: ' + err.message)
    }
  }

  const handleLinkProperty = async (e) => {
    e.preventDefault()
    if (!propPickId) return
    setLinkingProp(true)
    setPropLinkMsg('')
    try {
      await api.linkLeadProperty(id, { property_id: Number(propPickId) })
      setPropLinkMsg('Property linked successfully!')
      setPropPickId('')
      load()
    } catch (err) {
      alert('Could not link property: ' + err.message)
    } finally {
      setLinkingProp(false)
    }
  }

  const handleUnlinkProperty = async (recId) => {
    if (!window.confirm('Remove this property recommendation from the lead?')) return
    try {
      await api.unlinkLeadProperty(id, recId)
      load()
    } catch (err) {
      alert('Could not unlink property: ' + err.message)
    }
  }

  const handleRunRecommendations = async () => {
    setMatching(true)
    setMatchError('')
    setMatchResult(null)
    try {
      const res = await api.runLeadRecommendations(id, { persist: true, limit: 5 })
      setMatchResult(res)
      load()
    } catch (err) {
      setMatchError(err.message || 'Recommendation run failed.')
    } finally {
      setMatching(false)
    }
  }

  if (error) {
    return (
      <div className="ax-empty ax-error" style={{ textAlign: 'left', padding: 24, margin: 20 }}>
        <h3 style={{ color: '#b91c1c', margin: '0 0 8px 0' }}>⚠ Lead Detail Error</h3>
        <p style={{ margin: '0 0 16px 0' }}>{error}</p>
        <button className="btn btn-sm btn-primary" onClick={() => load()}>Retry Loading</button>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="ax-empty" style={{ padding: 60 }}>
        <div className="ax-spin" />
        <div style={{ marginTop: 12, color: '#64748b' }}>Loading luxury lead workspace…</div>
      </div>
    )
  }

  const lead = data.lead
  const convs = data.conversations || []
  const recs = data.property_recommendations || []
  const duplicates = data.duplicates || []
  const activity = data.activity || []
  const appointments = data.appointments || []
  const offers = data.offers || []
  const deals = data.deals || []
  const fus = lead.follow_ups || []
  const qual = lead.qualification || {}
  const msgCount = convs.reduce((n, c) => n + (c.messages?.length || 0), 0)

  const pendingFu = fus.find((f) => !f.completed_at && f.status !== 'cancelled')

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', padding: '0 8px 40px' }}>
      {/* Top back navigation */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <button
          className="ax-back"
          onClick={() => navigate('/agent/leads')}
          style={{ background: 'none', border: 'none', color: '#5a1645', fontWeight: 600, fontSize: 13, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}
        >
          ← Return to Leads Pipeline
        </button>
        <div className="ax-live-badge" title="Continuous real-time background synchronization active">
          <span className="ax-live-pulse-dot" />
          <span>Real-time Sync</span>
        </div>
      </div>

      {/* Duplicate Alert Banner */}
      {duplicates.length > 0 && (
        <div
          style={{
            background: '#fffbeb',
            border: '1px solid #fde68a',
            borderRadius: 12,
            padding: '12px 18px',
            marginBottom: 18,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: 12,
          }}
        >
          <div>
            <b style={{ color: '#b45309' }}>⚠ Potential Duplicate Contact Detected:</b>
            <span style={{ fontSize: 13, color: '#92400e', marginLeft: 8 }}>
              {duplicates.length} other record{duplicates.length > 1 ? 's' : ''} share this customer's phone or email address.
            </span>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {duplicates.map((dup) => (
              <button
                key={dup.id || dup.lead_id}
                className="btn btn-sm btn-ghost"
                style={{ fontSize: 12, borderColor: '#f59e0b', color: '#b45309' }}
                disabled={mergingId === dup.id}
                onClick={() => handleMergeDuplicate(dup)}
              >
                {mergingId === dup.id ? 'Merging…' : `Merge Duplicate #${dup.id || dup.lead_id}`}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* 1. LUXURY CUSTOMER IDENTITY HEADER                        */}
      {/* ======================================================== */}
      <section className="ax-lead-hero">
        <div className="ax-lead-hero__identity">
          <div className="ax-lead-hero__avatar">
            {(lead.name || 'C').charAt(0).toUpperCase()}
          </div>
          <div className="ax-lead-hero__titles">
            <h1>
              <span>{lead.name && lead.name !== 'Not provided' ? lead.name : 'VIP Prospective Buyer'}</span>
              <span style={{ fontSize: 14, fontWeight: 700, color: '#c5a880', background: 'rgba(197,168,128,0.15)', padding: '2px 8px', borderRadius: 6 }}>
                #{lead.id}
              </span>
            </h1>
            <div className="ax-lead-hero__badges">
              <span className={`ax-badge ${lead.status}`}>
                {statusLabel(lead.status)}
              </span>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  padding: '3px 10px',
                  borderRadius: 999,
                  fontSize: 12,
                  fontWeight: 700,
                  background: lead.temperature === 'hot' ? '#fee2e2' : lead.temperature === 'warm' ? '#fef3c7' : '#f1f5f9',
                  color: lead.temperature === 'hot' ? '#991b1b' : lead.temperature === 'warm' ? '#92400e' : '#475569',
                }}
              >
                {lead.temperature === 'hot' ? '🔥 Hot Lead' : lead.temperature === 'warm' ? '⚡ Warm Lead' : '❄ Cold Lead'}
              </span>
              <span style={{ fontSize: 12, color: '#64748b', background: '#f8fafc', padding: '3px 9px', borderRadius: 6, border: '1px solid #e2e8f0' }}>
                Channel: {lead.source || 'AI Property Concierge'}
              </span>
              {lead.buy_rent && lead.buy_rent !== 'Not provided' && (
                <span style={{ fontSize: 12, fontWeight: 600, color: '#5a1645', background: 'rgba(90,22,69,0.08)', padding: '3px 9px', borderRadius: 6 }}>
                  Intent: {lead.buy_rent.toUpperCase()}
                </span>
              )}
              <span style={{ fontSize: 12, color: '#475569' }}>
                Assigned: <b>{lead.assigned_agent?.full_name || 'Unassigned Pool'}</b>
              </span>
            </div>
          </div>
        </div>

        <div className="ax-lead-hero__actions">
          <button
            className="btn btn-sm btn-primary"
            onClick={() => setEditOpen(true)}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            ✎ Edit Lead
          </button>
          <button
            className="btn btn-sm btn-ghost"
            onClick={() => setActiveTab('conversations')}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            💬 Open Conversations ({convs.length})
          </button>
          <button
            className="btn btn-sm btn-ghost"
            onClick={() => {
              setActiveTab('activity')
              setTimeout(() => {
                const el = document.getElementById('fu-input-due')
                if (el) el.focus()
              }, 100)
            }}
          >
            ＋ Follow-up
          </button>
        </div>
      </section>

      {/* ======================================================== */}
      {/* 2. COMPACT KPI SUMMARY BAR                                */}
      {/* ======================================================== */}
      <section className="ax-lead-kpis">
        <div className="ax-lead-kpi-card">
          <span>Saved &amp; Recommendations</span>
          <b>{recs.length} properties</b>
        </div>
        <div className="ax-lead-kpi-card">
          <span>AI Concierge Chats</span>
          <b>{convs.length} threads · {msgCount} msgs</b>
        </div>
        <div className="ax-lead-kpi-card">
          <span>Last Interaction</span>
          <b style={{ fontSize: 16 }}>{lead.last_interaction_at ? fmtDate(lead.last_interaction_at) : '—'}</b>
        </div>
        <div className="ax-lead-kpi-card">
          <span>Next Follow-up</span>
          <b style={{ fontSize: 16, color: pendingFu ? '#b45309' : '#475569' }}>
            {pendingFu ? fmtDate(pendingFu.due_at) : 'None scheduled'}
          </b>
        </div>
        <div className="ax-lead-kpi-card">
          <span>Booked Viewings</span>
          <b>{appointments.length} appointment{appointments.length === 1 ? '' : 's'}</b>
        </div>
      </section>

      {/* ======================================================== */}
      {/* 3. LUXURY TAB NAVIGATION                                  */}
      {/* ======================================================== */}
      <nav className="ax-lead-nav-tabs" aria-label="Lead Detail Views">
        <button
          className={`ax-lead-nav-btn ${activeTab === 'overview' ? 'active' : ''}`}
          onClick={() => setActiveTab('overview')}
        >
          1. Profile &amp; Overview
        </button>
        <button
          className={`ax-lead-nav-btn ${activeTab === 'activity' ? 'active' : ''}`}
          onClick={() => setActiveTab('activity')}
        >
          2. Activity &amp; Governance
          <span className="ax-lead-nav-badge">{activity.length}</span>
        </button>
        <button
          className={`ax-lead-nav-btn ${activeTab === 'properties' ? 'active' : ''}`}
          onClick={() => setActiveTab('properties')}
        >
          3. Property Portfolio
          <span className="ax-lead-nav-badge">{recs.length}</span>
        </button>
        <button
          className={`ax-lead-nav-btn ${activeTab === 'conversations' ? 'active' : ''}`}
          onClick={() => setActiveTab('conversations')}
        >
          4. AI Conversations
          <span className="ax-lead-nav-badge">{convs.length}</span>
        </button>
      </nav>

      {/* ======================================================== */}
      {/* TAB 1: PROFILE & OVERVIEW                                 */}
      {/* ======================================================== */}
      {activeTab === 'overview' && (
        <div className="ax-lead-overview-grid">
          {/* Left Column: Identity & Contact Details */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            <div className="ax-panel">
              <h3 style={{ margin: '0 0 16px 0', color: '#5a1645', fontSize: 16, borderBottom: '1px solid #f1f5f9', paddingBottom: 8 }}>
                Contact &amp; Identification
              </h3>
              <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: '10px 14px', fontSize: 13.5 }}>
                <span style={{ color: '#64748b', fontWeight: 600 }}>Full Name:</span>
                <ValueOrEmpty value={lead.name} placeholder="Name not provided" />

                <span style={{ color: '#64748b', fontWeight: 600 }}>Phone:</span>
                <div>
                  <ValueOrEmpty value={lead.phone} placeholder="Phone not specified" />
                  {lead.phone && (
                    <a href={`tel:${lead.phone}`} style={{ marginLeft: 8, fontSize: 12, color: '#5a1645' }}>📞 Call</a>
                  )}
                </div>

                <span style={{ color: '#64748b', fontWeight: 600 }}>Email Address:</span>
                <div>
                  <ValueOrEmpty value={lead.email} placeholder="Email not specified" />
                  {lead.email && (
                    <a href={`mailto:${lead.email}`} style={{ marginLeft: 8, fontSize: 12, color: '#5a1645' }}>✉ Email</a>
                  )}
                </div>

                <span style={{ color: '#64748b', fontWeight: 600 }}>Language:</span>
                <ValueOrEmpty value={lead.preferred_language?.toUpperCase()} placeholder="English (Default)" />

                <span style={{ color: '#64748b', fontWeight: 600 }}>Emirate:</span>
                <ValueOrEmpty value={lead.emirate} placeholder="Dubai" />
              </div>

              {/* Status and Temperature Quick Controls */}
              <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid #f1f5f9' }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: '#475569', marginBottom: 8, textTransform: 'uppercase' }}>
                  Update Pipeline Status:
                </div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {STATUSES.map(([stVal, stLbl]) => (
                    <button
                      key={stVal}
                      type="button"
                      className={`btn btn-sm ${status === stVal ? 'btn-primary' : 'btn-ghost'}`}
                      style={{ fontSize: 11.5, padding: '3px 8px' }}
                      onClick={() => changeStatus(stVal)}
                    >
                      {stLbl}
                    </button>
                  ))}
                </div>
              </div>

              <div style={{ marginTop: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: '#475569', marginBottom: 8, textTransform: 'uppercase' }}>
                  Lead Temperature:
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  {['hot', 'warm', 'cold'].map((t) => (
                    <button
                      key={t}
                      type="button"
                      disabled={tempBusy}
                      onClick={() => changeTemperature(t)}
                      className={`btn btn-sm ${lead.temperature === t ? '' : 'btn-ghost'}`}
                      style={{
                        fontSize: 11.5,
                        padding: '3px 10px',
                        borderColor: t === 'hot' ? '#ef4444' : t === 'warm' ? '#f59e0b' : '#94a3b8',
                        color: t === 'hot' ? '#b91c1c' : t === 'warm' ? '#b45309' : '#475569',
                        background: lead.temperature === t ? (t === 'hot' ? '#fee2e2' : t === 'warm' ? '#fef3c7' : '#f1f5f9') : 'transparent',
                      }}
                    >
                      {t === 'hot' ? '🔥 Hot' : t === 'warm' ? '⚡ Warm' : '❄ Cold'}
                    </button>
                  ))}
                </div>
              </div>

              {/* Staff Assignment */}
              {canAssign && (
                <div style={{ marginTop: 16, paddingTop: 14, borderTop: '1px solid #f1f5f9' }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: '#475569', marginBottom: 8, textTransform: 'uppercase' }}>
                    Agent Assignment:
                  </div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <select
                      className="ax-input"
                      style={{ flex: 1, fontSize: 13 }}
                      value={selectedAgentId}
                      onChange={(e) => setSelectedAgentId(e.target.value)}
                    >
                      <option value="">— Unassigned Pool —</option>
                      {salesAgents.map((ag) => (
                        <option key={ag.id} value={ag.id}>
                          {ag.full_name} ({ag.email})
                        </option>
                      ))}
                    </select>
                    <button
                      className="btn btn-sm btn-primary"
                      disabled={assignBusy}
                      onClick={() => runAssign('manual', selectedAgentId)}
                    >
                      Assign
                    </button>
                    <button
                      className="btn btn-sm btn-ghost"
                      disabled={assignBusy}
                      onClick={() => runAssign('round_robin')}
                      title="Automatically assign to next available sales consultant"
                    >
                      Round-Robin
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Score & Qualification Completeness */}
            <div className="ax-panel">
              <h3 style={{ margin: '0 0 14px 0', color: '#5a1645', fontSize: 16, borderBottom: '1px solid #f1f5f9', paddingBottom: 8 }}>
                AI Lead Qualification &amp; Scoring
              </h3>
              <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14 }}>
                <div style={{ fontSize: 32, fontWeight: 800, color: '#44102f', fontFamily: 'Playfair Display, Georgia, serif' }}>
                  {lead.score ?? 0}
                  <span style={{ fontSize: 16, color: '#94a3b8', fontWeight: 500 }}> / 100</span>
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#64748b', marginBottom: 4 }}>
                    <span>Profile Completeness</span>
                    <b>{qual.completeness_percentage ?? 0}%</b>
                  </div>
                  <div style={{ width: '100%', height: 8, background: '#f1f5f9', borderRadius: 999, overflow: 'hidden' }}>
                    <div
                      style={{
                        width: `${qual.completeness_percentage ?? 0}%`,
                        height: '100%',
                        background: 'linear-gradient(90deg, #d4af37, #5a1645)',
                        borderRadius: 999,
                      }}
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Right Column: Preferences, Budget & Agent Notes */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            <div className="ax-panel">
              <h3 style={{ margin: '0 0 16px 0', color: '#5a1645', fontSize: 16, borderBottom: '1px solid #f1f5f9', paddingBottom: 8 }}>
                Property Preferences &amp; Investment Criteria
              </h3>
              <div style={{ display: 'grid', gridTemplateColumns: '150px 1fr', gap: '10px 14px', fontSize: 13.5 }}>
                <span style={{ color: '#64748b', fontWeight: 600 }}>Preferred Location:</span>
                <ValueOrEmpty value={lead.location} placeholder="Flexible / Not specified" />

                <span style={{ color: '#64748b', fontWeight: 600 }}>Property Type:</span>
                <ValueOrEmpty value={lead.property_type} placeholder="Any luxury property type" />

                <span style={{ color: '#64748b', fontWeight: 600 }}>Bedrooms / Baths:</span>
                <span>
                  {lead.bedrooms ? `${lead.bedrooms} beds` : 'Any beds'} · {lead.bathrooms ? `${lead.bathrooms} baths` : 'Any baths'}
                </span>

                <span style={{ color: '#64748b', fontWeight: 600 }}>Budget Range:</span>
                <ValueOrEmpty value={lead.budget_display} placeholder="Budget not specified" />

                <span style={{ color: '#64748b', fontWeight: 600 }}>Investment Purpose:</span>
                <ValueOrEmpty value={lead.investment_purpose} placeholder="Primary residence / Investment" />

                <span style={{ color: '#64748b', fontWeight: 600 }}>Financing Strategy:</span>
                <ValueOrEmpty value={lead.financing_type} placeholder="Cash / Mortgage" />

                <span style={{ color: '#64748b', fontWeight: 600 }}>Acquisition Timeline:</span>
                <ValueOrEmpty value={lead.timeline} placeholder="Immediate (0 - 30 days)" />

                <span style={{ color: '#64748b', fontWeight: 600 }}>Viewing Availability:</span>
                <ValueOrEmpty value={lead.preferred_viewing_time} placeholder="Flexible weekend / evening" />
              </div>
            </div>

            {/* Internal Staff Notes */}
            <div className="ax-panel">
              <h3 style={{ margin: '0 0 12px 0', color: '#5a1645', fontSize: 16 }}>
                Internal Consultant Notes
              </h3>
              <p style={{ margin: '0 0 10px 0', fontSize: 12.5, color: '#64748b' }}>
                Private broker notes visible only to authorized internal team members.
              </p>
              <textarea
                className="ax-input"
                rows={4}
                style={{ width: '100%', resize: 'vertical', fontSize: 13.5, lineHeight: 1.5, marginBottom: 10 }}
                placeholder="Record client discussions, viewing preferences, negotiation notes, or follow-up insights…"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <button
                  className="btn btn-sm btn-primary"
                  disabled={savingNotes}
                  onClick={saveNotes}
                >
                  {savingNotes ? 'Saving…' : 'Save Consultant Notes'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* TAB 2: ACTIVITY & GOVERNANCE                             */}
      {/* ======================================================== */}
      {activeTab === 'activity' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
          {/* Left: Follow-ups & Appointments */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            <div className="ax-panel">
              <h3 style={{ margin: '0 0 14px 0', color: '#5a1645', fontSize: 16 }}>
                Scheduled Follow-ups ({fus.length})
              </h3>

              {/* Add Follow-up Form */}
              <form onSubmit={handleAddFollowup} style={{ background: '#f8fafc', padding: 14, borderRadius: 10, border: '1px solid #e2e8f0', marginBottom: 16 }}>
                <div style={{ fontSize: 12.5, fontWeight: 700, color: '#334155', marginBottom: 10 }}>Schedule New Follow-up</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
                  <select
                    className="ax-input"
                    value={fuForm.type}
                    onChange={(e) => setFuForm({ ...fuForm, type: e.target.value })}
                  >
                    <option value="call">📞 Phone Call</option>
                    <option value="email">✉ Email</option>
                    <option value="whatsapp">💬 WhatsApp</option>
                    <option value="viewing">🏡 Viewing</option>
                    <option value="general">📌 General Task</option>
                  </select>
                  <input
                    id="fu-input-due"
                    type="datetime-local"
                    className="ax-input"
                    required
                    value={fuForm.due}
                    onChange={(e) => setFuForm({ ...fuForm, due: e.target.value })}
                  />
                </div>
                <textarea
                  className="ax-input"
                  rows={2}
                  style={{ width: '100%', marginBottom: 10 }}
                  placeholder="Follow-up notes / objective…"
                  value={fuForm.notes}
                  onChange={(e) => setFuForm({ ...fuForm, notes: e.target.value })}
                />
                <button className="btn btn-sm btn-primary" type="submit" disabled={fuBusy}>
                  {fuBusy ? 'Scheduling…' : 'Schedule Follow-up'}
                </button>
              </form>

              {/* Follow-ups List */}
              {fus.length === 0 ? (
                <div className="ax-empty sm">No follow-ups recorded for this lead yet.</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {fus.map((fu) => (
                    <div
                      key={fu.id}
                      style={{
                        padding: '10px 14px',
                        background: fu.completed_at ? '#f8fafc' : '#ffffff',
                        border: '1px solid #e2e8f0',
                        borderRadius: 10,
                        borderLeft: fu.completed_at ? '3px solid #10b981' : fu.status === 'cancelled' ? '3px solid #94a3b8' : '3px solid #f59e0b',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'flex-start',
                        gap: 12,
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: 600, fontSize: 13, color: '#1e293b' }}>
                          {fu.type.toUpperCase()} · Due {fmtDate(fu.due_at)}
                        </div>
                        <div style={{ fontSize: 12.5, color: '#475569', marginTop: 2 }}>{fu.notes || 'No notes provided'}</div>
                      </div>
                      {!fu.completed_at && fu.status !== 'cancelled' && (
                        <div style={{ display: 'flex', gap: 6 }}>
                          <button
                            className="btn btn-sm btn-primary"
                            style={{ fontSize: 11, padding: '2px 8px' }}
                            onClick={() => handleCompleteFollowup(fu.id)}
                          >
                            ✓ Done
                          </button>
                          <button
                            className="btn btn-sm btn-ghost"
                            style={{ fontSize: 11, padding: '2px 8px', color: '#dc2626' }}
                            onClick={() => handleCancelFollowup(fu.id)}
                          >
                            ✕ Cancel
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Right: Audit Trail History */}
          <div className="ax-panel">
            <h3 style={{ margin: '0 0 14px 0', color: '#5a1645', fontSize: 16 }}>
              Chronological Audit Trail ({activity.length})
            </h3>
            {activity.length === 0 ? (
              <div className="ax-empty sm">No activity events logged for this lead.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: 560, overflowY: 'auto' }}>
                {activity.map((ev) => (
                  <div
                    key={ev.id}
                    style={{
                      fontSize: 12.5,
                      padding: '8px 12px',
                      background: '#fdfcf9',
                      borderLeft: '3px solid #d4af37',
                      borderBottom: '1px solid #f1f5f9',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: '#888', marginBottom: 2 }}>
                      <span style={{ fontWeight: 700, color: '#44102f' }}>{ev.action}</span>
                      <span>{fmtDate(ev.created_at)}</span>
                    </div>
                    <div style={{ color: '#334155' }}>
                      <span style={{ color: '#64748b' }}>By {ev.actor}: </span>
                      {formatAuditDetail(ev.detail) || ev.detail || 'Event recorded'}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* TAB 3: PROPERTY PORTFOLIO & MATCHES                       */}
      {/* ======================================================== */}
      {activeTab === 'properties' && (
        <div>
          {/* Actions Bar */}
          <div className="ax-panel" style={{ marginBottom: 20 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 14 }}>
              <div>
                <h3 style={{ margin: '0 0 4px 0', color: '#5a1645', fontSize: 16 }}>
                  Recommended &amp; Saved Properties
                </h3>
                <p style={{ margin: 0, fontSize: 12.5, color: '#64748b' }}>
                  Properties recommended by LykAI during AI chats or curated by sales consultants.
                </p>
              </div>

              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <button
                  className="btn btn-sm btn-primary"
                  disabled={matching}
                  onClick={handleRunRecommendations}
                >
                  {matching ? 'Matching Properties…' : '⚡ Run AI Property Match'}
                </button>
              </div>
            </div>

            {/* Quick Link Property Form */}
            <form onSubmit={handleLinkProperty} style={{ marginTop: 16, paddingTop: 14, borderTop: '1px solid #f1f5f9', display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: '#334155' }}>Link Property to Lead:</span>
              <select
                className="ax-input"
                style={{ width: 340, fontSize: 13 }}
                value={propPickId}
                onChange={(e) => setPropPickId(e.target.value)}
              >
                <option value="">— Select an approved property —</option>
                {propOptions.map((p) => (
                  <option key={p.id} value={p.id}>
                    #{p.id} - {p.title || p.property_type} ({p.location || 'Dubai'}) - AED {p.price ? Number(p.price).toLocaleString() : '—'}
                  </option>
                ))}
              </select>
              <button className="btn btn-sm btn-ghost" type="submit" disabled={linkingProp || !propPickId}>
                {linkingProp ? 'Linking…' : '＋ Link to Portfolio'}
              </button>
              {propLinkMsg && <span style={{ fontSize: 12, color: '#10b981', fontWeight: 600 }}>{propLinkMsg}</span>}
            </form>
          </div>

          {/* Properties Grid */}
          {recs.length === 0 ? (
            <div className="ax-panel" style={{ textAlign: 'center', padding: 48, color: '#64748b' }}>
              <div style={{ fontSize: 36, marginBottom: 10 }}>🏢</div>
              <h4 style={{ margin: '0 0 6px 0', color: '#1e293b' }}>No Property Recommendations Linked Yet</h4>
              <p style={{ margin: '0 0 16px 0', fontSize: 13 }}>
                Click "Run AI Property Match" above to evaluate current inventory against this client's budget and specifications.
              </p>
              <button className="btn btn-sm btn-primary" disabled={matching} onClick={handleRunRecommendations}>
                Run AI Property Match
              </button>
            </div>
          ) : (
            <div className="ax-lead-props-grid">
              {recs.map((r, i) => {
                const ap = adaptProperty(r)
                const isVerified = r.source === 'record' || r.property_source === 'record'
                return (
                  <div key={`${r.property_id || r.id}-${i}`} className="ax-lead-prop-card">
                    <div className="ax-lead-prop-card__header">
                      <span
                        style={{
                          fontSize: 11,
                          fontWeight: 700,
                          padding: '2px 8px',
                          borderRadius: 4,
                          background: isVerified ? '#ecfdf5' : '#f8fafc',
                          color: isVerified ? '#047857' : '#475569',
                          border: isVerified ? '1px solid #a7f3d0' : '1px solid #e2e8f0',
                        }}
                      >
                        {isVerified ? '✓ Verified Lyka Inventory' : 'Market Reference'}
                      </span>
                      <span style={{ fontSize: 18 }}>{ap.fallbackEmoji}</span>
                    </div>

                    <div className="ax-lead-prop-card__body">
                      <b style={{ color: '#2c0f20', fontSize: 15 }}>
                        {ap.propertyType} <span style={{ color: '#94a3b8', fontSize: 13 }}>#{r.property_id || r.id}</span>
                      </b>
                      <div style={{ fontSize: 18, fontWeight: 700, color: '#5a1645' }}>
                        {ap.formattedPrice}
                      </div>
                      <div style={{ fontSize: 13, color: '#64748b' }}>
                        📍 {ap.location}
                      </div>
                      <div style={{ display: 'flex', gap: 10, fontSize: 12.5, color: '#475569', marginTop: 4 }}>
                        <span>🛏 {ap.bedroomLabel}</span>
                        <span>🛁 {ap.bathroomLabel}</span>
                        <span>📐 {ap.formattedArea}</span>
                      </div>
                      {r.relevance_score != null && (
                        <div style={{ marginTop: 8 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#64748b' }}>
                            <span>Relevance Match</span>
                            <b>{Math.round(Number(r.relevance_score) * 100)}%</b>
                          </div>
                          <div style={{ width: '100%', height: 5, background: '#f1f5f9', borderRadius: 999, overflow: 'hidden' }}>
                            <div style={{ width: `${Math.round(Number(r.relevance_score) * 100)}%`, height: '100%', background: '#d4af37' }} />
                          </div>
                        </div>
                      )}
                    </div>

                    <div className="ax-lead-prop-card__footer">
                      <button
                        className="btn btn-sm btn-ghost"
                        style={{ fontSize: 12, padding: '3px 8px' }}
                        onClick={() => navigate(`/properties/${r.property_id || r.id}`)}
                      >
                        Open Listing →
                      </button>
                      <button
                        className="btn btn-sm btn-ghost"
                        style={{ fontSize: 12, padding: '3px 8px', color: '#dc2626' }}
                        onClick={() => handleUnlinkProperty(r.id)}
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* ======================================================== */}
      {/* TAB 4: CONVERSATIONS (REAL-TIME LIVE SYNCHRONIZATION)     */}
      {/* ======================================================== */}
      {activeTab === 'conversations' && (
        <div className="ax-panel">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, borderBottom: '1px solid #f1f5f9', paddingBottom: 14 }}>
            <div>
              <h3 style={{ margin: '0 0 4px 0', color: '#5a1645', fontSize: 17 }}>
                LykAI Concierge ↔ Customer Chat Transcript
              </h3>
              <p style={{ margin: 0, fontSize: 13, color: '#64748b' }}>
                Full live conversation history captured across web and voice channels.
              </p>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div className="ax-live-badge">
                <span className="ax-live-pulse-dot" />
                <span>Live Synchronizing (3s)</span>
              </div>
              <button
                className="btn btn-sm btn-ghost"
                onClick={() => load(false)}
                title="Force refresh conversation messages"
              >
                ↻ Refresh
              </button>
            </div>
          </div>

          {convs.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '50px 20px', color: '#64748b' }}>
              <div style={{ fontSize: 40, marginBottom: 12 }}>💬</div>
              <h4 style={{ margin: '0 0 6px 0', color: '#1e293b', fontSize: 16 }}>No Linked AI Conversations Yet</h4>
              <p style={{ margin: '0 auto', maxWidth: 460, fontSize: 13.5, lineHeight: 1.55 }}>
                When this customer chats with LykAI on the public concierge or asks questions about property listings,
                their messages and LykAI responses will automatically appear here in real-time.
              </p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
              {convs.map((c) => (
                <div
                  key={c.id}
                  style={{
                    background: '#fcfbf8',
                    border: '1px solid #ede4da',
                    borderRadius: 14,
                    padding: '16px 20px',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, borderBottom: '1px solid #f0e6dc', paddingBottom: 10 }}>
                    <div>
                      <b style={{ color: '#5a1645', fontSize: 14 }}>Conversation #{c.id}</b>
                      <span style={{ fontSize: 12, color: '#64748b', marginLeft: 10 }}>
                        Started {fmtDate(c.created_at)} · {c.messages?.length || 0} messages
                      </span>
                    </div>
                    <span
                      style={{
                        fontSize: 11.5,
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        padding: '2px 8px',
                        borderRadius: 6,
                        background: c.status === 'active' ? '#ecfdf5' : '#f1f5f9',
                        color: c.status === 'active' ? '#047857' : '#64748b',
                      }}
                    >
                      {c.status || 'Active'}
                    </span>
                  </div>

                  {/* Messages Stream */}
                  {(!c.messages || c.messages.length === 0) ? (
                    <div className="ax-empty sm">Empty conversation thread.</div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column' }}>
                      {c.messages.map((m) => (
                        <MsgBubble key={m.id} m={m} />
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ======================================================== */}
      {/* MODAL: EDIT LEAD SPECIFICATIONS                           */}
      {/* ======================================================== */}
      {editOpen && edit && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999, padding: 16 }}>
          <div style={{ background: '#ffffff', borderRadius: 16, padding: '24px 28px', width: '100%', maxWidth: 700, maxHeight: '90vh', overflowY: 'auto' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, borderBottom: '1px solid #f1f5f9', paddingBottom: 12 }}>
              <h3 style={{ margin: 0, color: '#5a1645', fontSize: 18 }}>
                Edit Lead Profile &amp; Preferences #{lead.id}
              </h3>
              <button
                type="button"
                onClick={() => setEditOpen(false)}
                style={{ background: 'none', border: 'none', fontSize: 20, color: '#94a3b8', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>

            {editError && (
              <div style={{ padding: '8px 12px', background: '#fee2e2', color: '#b91c1c', borderRadius: 8, fontSize: 13, marginBottom: 14 }}>
                {editError}
              </div>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <label>
                <span style={{ fontSize: 12, fontWeight: 700 }}>Full Name</span>
                <input
                  type="text"
                  className="ax-input"
                  value={edit.name}
                  onChange={(e) => setEdit({ ...edit, name: e.target.value })}
                />
              </label>

              <label>
                <span style={{ fontSize: 12, fontWeight: 700 }}>Phone</span>
                <input
                  type="text"
                  className="ax-input"
                  value={edit.phone}
                  onChange={(e) => setEdit({ ...edit, phone: e.target.value })}
                />
              </label>

              <label>
                <span style={{ fontSize: 12, fontWeight: 700 }}>Email</span>
                <input
                  type="email"
                  className="ax-input"
                  value={edit.email}
                  onChange={(e) => setEdit({ ...edit, email: e.target.value })}
                />
              </label>

              <label>
                <span style={{ fontSize: 12, fontWeight: 700 }}>Intent</span>
                <select
                  className="ax-input"
                  value={edit.intent}
                  onChange={(e) => setEdit({ ...edit, intent: e.target.value })}
                >
                  {INTENTS.map(([val, lbl]) => <option key={val} value={val}>{lbl}</option>)}
                </select>
              </label>

              <label>
                <span style={{ fontSize: 12, fontWeight: 700 }}>Preferred Location</span>
                <input
                  type="text"
                  className="ax-input"
                  value={edit.location}
                  onChange={(e) => setEdit({ ...edit, location: e.target.value })}
                />
              </label>

              <label>
                <span style={{ fontSize: 12, fontWeight: 700 }}>Property Type</span>
                <input
                  type="text"
                  className="ax-input"
                  value={edit.property_type}
                  onChange={(e) => setEdit({ ...edit, property_type: e.target.value })}
                />
              </label>

              <label>
                <span style={{ fontSize: 12, fontWeight: 700 }}>Min Budget (AED)</span>
                <input
                  type="number"
                  className="ax-input"
                  value={edit.budget_min}
                  onChange={(e) => setEdit({ ...edit, budget_min: e.target.value })}
                />
              </label>

              <label>
                <span style={{ fontSize: 12, fontWeight: 700 }}>Max Budget (AED)</span>
                <input
                  type="number"
                  className="ax-input"
                  value={edit.budget_max}
                  onChange={(e) => setEdit({ ...edit, budget_max: e.target.value })}
                />
              </label>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 22, paddingTop: 14, borderTop: '1px solid #f1f5f9' }}>
              <button className="btn btn-sm btn-ghost" type="button" onClick={() => setEditOpen(false)}>
                Cancel
              </button>
              <button className="btn btn-sm btn-primary" type="button" disabled={savingEdit} onClick={saveEdit}>
                {savingEdit ? 'Saving…' : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function AgentLeadDetail() {
  return (
    <ErrorBoundary title="Lead Detail Workspace">
      <AgentLeadDetailView />
    </ErrorBoundary>
  )
}
