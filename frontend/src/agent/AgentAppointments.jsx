import React from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import api from '../api.js'
import { useAuth, hasPerm } from '../auth/AuthContext.jsx'

const APPOINTMENT_TYPES = [
  ['viewing', 'Property viewing'],
  ['consultation', 'Consultation'],
  ['callback', 'Callback'],
  ['negotiation_meeting', 'Negotiation meeting'],
  ['documentation_meeting', 'Documentation / MOU meeting'],
]

const MEETING_METHODS = [
  ['in_person', 'In person at property/tower', '🏢'],
  ['phone', 'Phone call', '📞'],
  ['video', 'Video conference (Zoom/Meet)', '🎥'],
]

const APPOINTMENT_STATUSES = [
  ['', 'All statuses'],
  ['scheduled', 'Scheduled'],
  ['confirmed', 'Confirmed'],
  ['rescheduled', 'Rescheduled'],
  ['completed', 'Completed'],
  ['cancelled', 'Cancelled'],
  ['no_show', 'No-show'],
]

const VIEWING_OUTCOMES = [
  ['interested', 'Interested — ready for offer / shortlist', '⭐'],
  ['requested_another_viewing', 'Requested another viewing / second visit', '🔄'],
  ['requested_more_info', 'Requested more info / floor plans / documents', '📋'],
  ['undecided', 'Undecided — follow up needed', '⏳'],
  ['not_interested', 'Not interested in this property', '✕'],
]

/**
 * Format ISO datetime into Dubai Gulf Standard Time (GST, UTC+4).
 */
function fmtDubaiDateTime(iso) {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (isNaN(d.getTime())) return iso
    return d.toLocaleString('en-GB', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: true,
      timeZone: 'Asia/Dubai',
    }) + ' GST'
  } catch {
    return iso
  }
}

/**
 * Human-readable relative time tag (e.g. "Today", "Tomorrow", "In 3 days", "Past")
 */
function getRelativeTag(iso) {
  if (!iso) return null
  try {
    const d = new Date(iso)
    const now = new Date()
    const diffMs = d.getTime() - now.getTime()
    const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24))

    if (diffMs < -1000 * 60 * 60 * 24) return { label: 'Past', bg: '#f1f5f9', color: '#64748b' }
    if (diffDays === 0) return { label: 'Today', bg: '#fef3c7', color: '#b45309' }
    if (diffDays === 1) return { label: 'Tomorrow', bg: '#e0f2fe', color: '#0369a1' }
    if (diffDays > 1 && diffDays <= 7) return { label: `In ${diffDays} days`, bg: '#f3e8ff', color: '#7e22ce' }
    if (diffDays > 7) return { label: 'Upcoming', bg: '#f0fdf4', color: '#15803d' }
    return { label: 'Today', bg: '#fef3c7', color: '#b45309' }
  } catch {
    return null
  }
}

/**
 * Download a standard .ics calendar invite for the appointment.
 */
function downloadIcsFile(appt) {
  const title = `Lyka Realty: ${appt.appointment_type === 'viewing' ? 'Property Viewing' : 'Appointment'} - #${appt.id}`
  const description = `Customer: ${appt.lead_name || 'Client'}\nProperty: ${appt.property_title || 'N/A'}\nNotes: ${appt.notes || 'None'}`
  const location = appt.location_or_link || 'Dubai, UAE'
  
  const start = appt.start_at ? new Date(appt.start_at).toISOString().replace(/-|:|\.\d+/g, '') : ''
  const end = appt.end_at ? new Date(appt.end_at).toISOString().replace(/-|:|\.\d+/g, '') : start

  const ics = `BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Lyka Realty CRM//Appointments//EN
BEGIN:VEVENT
SUMMARY:${title}
DESCRIPTION:${description.replace(/\n/g, '\\n')}
LOCATION:${location}
DTSTART:${start}
DTEND:${end}
STATUS:CONFIRMED
END:VEVENT
END:VCALENDAR`

  const blob = new Blob([ics], { type: 'text/calendar;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `appointment-${appt.id}.ics`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export default function AgentAppointments() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { permissions, agent: currentAgent } = useAuth()
  const canAssign = hasPerm({ permissions }, 'leads.assign') || currentAgent?.role === 'admin'

  const [items, setItems] = React.useState([])
  const [total, setTotal] = React.useState(0)
  const [summary, setSummary] = React.useState(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState('')
  const [salesAgents, setSalesAgents] = React.useState([])

  // Filters
  const [windowFilter, setWindowFilter] = React.useState(searchParams.get('window') || 'all')
  const [typeFilter, setTypeFilter] = React.useState(searchParams.get('type') || '')
  const [statusFilter, setStatusFilter] = React.useState(searchParams.get('status') || '')
  const [searchQuery, setSearchQuery] = React.useState('')

  // Modals
  const [createModalOpen, setCreateModalOpen] = React.useState(searchParams.get('new') === '1')
  const [leads, setLeads] = React.useState([])
  const [properties, setProperties] = React.useState([])
  
  // Default start date = today at 15:00, end = 16:00
  const defaultStart = new Date()
  defaultStart.setHours(defaultStart.getHours() + 2, 0, 0, 0)
  const defaultEnd = new Date(defaultStart.getTime() + 60 * 60 * 1000)
  const toLocalIso = (d) => {
    const pad = (n) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
  }

  const [form, setForm] = React.useState({
    lead_id: searchParams.get('lead_id') || '',
    property_id: searchParams.get('property_id') || '',
    assigned_agent_id: '',
    appointment_type: 'viewing',
    meeting_method: 'in_person',
    start_at: toLocalIso(defaultStart),
    end_at: toLocalIso(defaultEnd),
    timezone: 'Asia/Dubai',
    location_or_link: '',
    notes: '',
    conflict_override: false,
    conflict_override_reason: '',
  })
  const [conflictAlert, setConflictAlert] = React.useState(null)
  const [createBusy, setCreateBusy] = React.useState(false)
  const [createErr, setCreateErr] = React.useState('')

  // Outcome Modal State
  const [outcomeModalAppt, setOutcomeModalAppt] = React.useState(null)
  const [outcomeForm, setOutcomeForm] = React.useState({
    status: 'completed',
    viewing_outcome: 'interested',
    customer_feedback: '',
    next_action: '',
    outcome: '',
  })

  // Reschedule Modal State
  const [rescheduleModalAppt, setRescheduleModalAppt] = React.useState(null)
  const [rescheduleForm, setRescheduleForm] = React.useState({
    start_at: '',
    end_at: '',
    reason: '',
    conflict_override: false,
    conflict_override_reason: '',
  })

  const [actionBusy, setActionBusy] = React.useState(false)

  // Close modals on Escape key
  React.useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        if (createModalOpen) setCreateModalOpen(false)
        if (outcomeModalAppt) setOutcomeModalAppt(null)
        if (rescheduleModalAppt) setRescheduleModalAppt(null)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [createModalOpen, outcomeModalAppt, rescheduleModalAppt])

  const loadAll = React.useCallback(() => {
    setLoading(true)
    setError('')
    Promise.all([
      api.agentAppointments({
        window: windowFilter !== 'all' ? windowFilter : undefined,
        appointment_type: typeFilter || undefined,
        status: statusFilter || undefined,
        limit: 100,
      }),
      api.agentSalesOpsSummary().catch(() => null),
    ])
      .then(([res, sum]) => {
        setItems(res.results || [])
        setTotal(res.total || 0)
        if (sum) setSummary(sum)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [windowFilter, typeFilter, statusFilter])

  const paramPropId = searchParams.get('property_id')
  const paramLeadId = searchParams.get('lead_id')

  React.useEffect(() => {
    loadAll()
  }, [loadAll])

  React.useEffect(() => {
    api.agentLeads({ limit: 150 })
      .then(async (r) => {
        let list = r.results || r.leads || []
        if (paramLeadId && !list.some((l) => String(l.id) === String(paramLeadId))) {
          try {
            const sp = await api.agentLead(paramLeadId)
            if (sp?.lead) list = [sp.lead, ...list]
          } catch {}
        }
        setLeads(list)
      })
      .catch(() => {})

    api
      .agentProperties({ approved: true, availability: 'available', limit: 100 })
      .then(async (r) => {
        let list = r.results || r.items || []
        if (paramPropId && !list.some((p) => String(p.id) === String(paramPropId))) {
          try {
            const sp = await api.agentProperty(paramPropId)
            const propObj = sp?.property || sp
            if (propObj && propObj.id) list = [propObj, ...list]
          } catch {}
        }
        setProperties(list)
      })
      .catch(() => {})

    api.agentSalesAgents()
      .then((r) => setSalesAgents(r.results || []))
      .catch(() => {})
  }, [paramPropId, paramLeadId])

  React.useEffect(() => {
    if (paramPropId) {
      setForm((prev) => ({ ...prev, property_id: String(paramPropId) }))
    }
    if (paramLeadId) {
      setForm((prev) => ({ ...prev, lead_id: String(paramLeadId) }))
    }
  }, [paramPropId, paramLeadId])

  // Auto-fill location when property changes in creation form
  const handlePropertySelect = (propId) => {
    const selectedProp = properties.find((p) => String(p.id) === String(propId))
    setForm((prev) => ({
      ...prev,
      property_id: propId,
      location_or_link: selectedProp ? `${selectedProp.title} Lobby, ${selectedProp.location}` : prev.location_or_link,
    }))
  }

  const handleCreate = async (e) => {
    e.preventDefault()
    if (!form.lead_id || !form.start_at || !form.end_at) {
      setCreateErr('Please select a customer lead, start time, and end time.')
      return
    }
    setCreateBusy(true)
    setCreateErr('')
    try {
      await api.createAgentAppointment({
        lead_id: Number(form.lead_id),
        property_id: form.property_id ? Number(form.property_id) : null,
        assigned_agent_id: form.assigned_agent_id ? Number(form.assigned_agent_id) : null,
        appointment_type: form.appointment_type,
        meeting_method: form.meeting_method,
        start_at: form.start_at,
        end_at: form.end_at,
        timezone: form.timezone || 'Asia/Dubai',
        location_or_link: form.location_or_link || null,
        notes: form.notes || null,
        conflict_override: form.conflict_override,
        conflict_override_reason: form.conflict_override_reason || null,
      })
      setConflictAlert(null)
      setCreateModalOpen(false)
      setForm({
        lead_id: '',
        property_id: '',
        appointment_type: 'viewing',
        meeting_method: 'in_person',
        start_at: toLocalIso(defaultStart),
        end_at: toLocalIso(defaultEnd),
        timezone: 'Asia/Dubai',
        location_or_link: '',
        notes: '',
        conflict_override: false,
        conflict_override_reason: '',
      })
      loadAll()
    } catch (err) {
      if (err.status === 409 && err.detail && err.detail.code === 'appointment_conflict') {
        setConflictAlert(err.detail)
        setCreateErr(err.detail.message || 'Scheduling conflict detected.')
      } else {
        setCreateErr(err.message || 'Failed to schedule appointment.')
      }
    } finally {
      setCreateBusy(false)
    }
  }

  const handleConfirm = async (appt) => {
    setActionBusy(true)
    try {
      if (appt.customer_confirmation_status === 'pending') {
        await api.agentAcceptViewingRequest(appt.id)
      } else {
        await api.updateAgentAppointment(appt.id, {
          status: 'confirmed',
          customer_confirmation_status: 'confirmed',
        })
      }
      loadAll()
    } catch (e) {
      alert('Could not confirm appointment: ' + e.message)
    } finally {
      setActionBusy(false)
    }
  }

  const handleRejectViewingRequest = async (appt) => {
    const reason = window.prompt(
      'Reason for declining this customer viewing request:',
      'Specialist unavailable at requested time slot'
    )
    if (!reason) return
    setActionBusy(true)
    try {
      await api.agentRejectViewingRequest(appt.id, { reason })
      loadAll()
    } catch (e) {
      alert('Could not decline viewing request: ' + e.message)
    } finally {
      setActionBusy(false)
    }
  }

  const handleCancel = async (appt) => {
    const reason = window.prompt(
      `Cancel appointment #${appt.id} with ${appt.lead_name || `Lead #${appt.lead_id}`}? Enter reason:`,
      'Customer requested cancellation'
    )
    if (reason === null) return
    setActionBusy(true)
    try {
      await api.cancelAgentAppointment(appt.id, { reason })
      loadAll()
    } catch (e) {
      alert('Cancel failed: ' + e.message)
    } finally {
      setActionBusy(false)
    }
  }

  const openOutcomeModal = (appt) => {
    setOutcomeModalAppt(appt)
    setOutcomeForm({
      status: 'completed',
      viewing_outcome: appt.viewing_outcome || 'interested',
      customer_feedback: appt.customer_feedback || '',
      next_action: appt.next_action || '',
      outcome: appt.outcome || '',
    })
  }

  const handleOutcomeSubmit = async (e) => {
    e.preventDefault()
    if (!outcomeModalAppt) return
    setActionBusy(true)
    try {
      await api.recordAgentAppointmentOutcome(outcomeModalAppt.id, {
        status: outcomeForm.status,
        viewing_outcome: outcomeForm.status === 'completed' ? outcomeForm.viewing_outcome : null,
        customer_feedback: outcomeForm.customer_feedback || null,
        next_action: outcomeForm.next_action || null,
        outcome: outcomeForm.outcome || null,
      })
      const isInterested = outcomeForm.status === 'completed' && outcomeForm.viewing_outcome === 'interested'
      const leadId = outcomeModalAppt.lead_id
      const propId = outcomeModalAppt.property_id
      setOutcomeModalAppt(null)
      loadAll()

      if (isInterested && propId) {
        if (window.confirm('Customer is interested! Would you like to create a formal Purchase/Lease Offer now?')) {
          navigate(`/agent/deals?new_offer=1&lead_id=${leadId}&property_id=${propId}`)
        }
      }
    } catch (e) {
      alert('Could not record outcome: ' + e.message)
    } finally {
      setActionBusy(false)
    }
  }

  const openRescheduleModal = (appt) => {
    setRescheduleModalAppt(appt)
    setRescheduleForm({
      start_at: appt.start_at ? toLocalIso(new Date(appt.start_at)) : '',
      end_at: appt.end_at ? toLocalIso(new Date(appt.end_at)) : '',
      reason: '',
      conflict_override: false,
      conflict_override_reason: '',
    })
  }

  const handleRescheduleSubmit = async (e) => {
    e.preventDefault()
    if (!rescheduleModalAppt || !rescheduleForm.start_at || !rescheduleForm.end_at) {
      alert('Please specify new start and end times.')
      return
    }
    setActionBusy(true)
    try {
      await api.rescheduleAgentAppointment(rescheduleModalAppt.id, {
        start_at: rescheduleForm.start_at,
        end_at: rescheduleForm.end_at,
        timezone: 'Asia/Dubai',
        reason: rescheduleForm.reason || 'Rescheduled by agent',
        conflict_override: rescheduleForm.conflict_override,
        conflict_override_reason: rescheduleForm.conflict_override_reason || null,
      })
      setRescheduleModalAppt(null)
      loadAll()
    } catch (e) {
      alert('Reschedule failed: ' + e.message)
    } finally {
      setActionBusy(false)
    }
  }

  // Filtered Appointments
  const filteredItems = items.filter((a) => {
    if (!searchQuery.trim()) return true
    const q = searchQuery.toLowerCase()
    const matchLead = (a.lead_name || '').toLowerCase().includes(q)
    const matchId = String(a.id).includes(q) || String(a.lead_id).includes(q)
    const matchProp = (a.property_title || '').toLowerCase().includes(q) || (a.property_location || '').toLowerCase().includes(q)
    const matchLoc = (a.location_or_link || '').toLowerCase().includes(q)
    return matchLead || matchId || matchProp || matchLoc
  })

  const apptStats = summary?.appointments || {}
  const byApptStatus = apptStats.by_status || {}

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', paddingBottom: 60 }}>
      {/* Top Workspace Header & Schedule CTA */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 20,
          flexWrap: 'wrap',
          gap: 14,
          background: '#ffffff',
          padding: '16px 22px',
          borderRadius: 14,
          border: '1px solid #ebdbe4',
          boxShadow: '0 2px 6px rgba(90, 22, 69, 0.04)',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 22 }}>📅</span>
            <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: '#5a1645', fontFamily: 'var(--display, serif)' }}>
              Appointments &amp; Property Viewings
            </h2>
          </div>
          <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: 13 }}>
            Coordinate customer property viewings, resolve double-booking conflicts, and record buyer feedback in Dubai GST.
          </p>
        </div>

        <button
          type="button"
          onClick={() => {
            setCreateErr('')
            setConflictAlert(null)
            setCreateModalOpen(true)
          }}
          style={{
            background: 'linear-gradient(135deg, #5a1645 0%, #3a0c26 100%)',
            color: '#e8bd68',
            border: '1px solid #e8bd68',
            borderRadius: 10,
            fontWeight: 700,
            fontSize: 13.5,
            padding: '9px 20px',
            cursor: 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            boxShadow: '0 4px 12px rgba(90, 22, 69, 0.25)',
            transition: 'all 0.2s ease',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.transform = 'translateY(-1px)'
            e.currentTarget.style.boxShadow = '0 6px 16px rgba(90, 22, 69, 0.35)'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.transform = 'none'
            e.currentTarget.style.boxShadow = '0 4px 12px rgba(90, 22, 69, 0.25)'
          }}
        >
          <span style={{ fontSize: 16 }}>＋</span> Schedule Viewing / Meeting
        </button>
      </div>

      {/* Executive KPI Overview Cards */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))',
          gap: 12,
          marginBottom: 22,
        }}
      >
        {[
          {
            tab: 'today',
            label: "Today's Schedule",
            count: apptStats.today ?? 0,
            sub: 'Viewings & calls due today',
            icon: '📅',
            color: '#5a1645',
            active: windowFilter === 'today',
          },
          {
            tab: 'upcoming',
            label: 'Upcoming Viewings',
            count: apptStats.upcoming_viewings ?? 0,
            sub: 'Scheduled customer visits',
            icon: '🏢',
            color: '#0284c7',
            active: windowFilter === 'upcoming',
          },
          {
            tab: 'overdue',
            label: 'Overdue Outcomes',
            count: apptStats.overdue_action_needed ?? 0,
            sub: 'Completed visits needing notes',
            icon: '⚠',
            color: (apptStats.overdue_action_needed ?? 0) > 0 ? '#dc2626' : '#64748b',
            active: windowFilter === 'overdue',
          },
          {
            tab: 'conflicts',
            label: 'Listing Conflicts',
            count: apptStats.property_conflicts ?? 0,
            sub: 'Reserved/off-market warnings',
            icon: '⚡',
            color: (apptStats.property_conflicts ?? 0) > 0 ? '#ea580c' : '#64748b',
            active: windowFilter === 'conflicts',
          },
          {
            tab: 'all',
            label: 'Completed Viewings',
            count: byApptStatus.completed ?? 0,
            sub: 'Successfully finished visits',
            icon: '✓',
            color: '#10b981',
            active: false,
          },
          {
            tab: 'all',
            label: 'Customer No-Shows',
            count: byApptStatus.no_show ?? 0,
            sub: 'Unattended appointments',
            icon: '✕',
            color: '#94a3b8',
            active: false,
          },
        ].map((kpi, idx) => (
          <div
            key={idx}
            onClick={() => {
              if (kpi.tab !== 'all') {
                const next = windowFilter === kpi.tab ? 'all' : kpi.tab
                setWindowFilter(next)
                setSearchParams((p) => {
                  const n = new URLSearchParams(p)
                  if (next === 'all') n.delete('window')
                  else n.set('window', next)
                  return n
                })
              }
            }}
            style={{
              background: '#ffffff',
              border: kpi.active ? `2px solid ${kpi.color}` : '1px solid #ebdbe4',
              borderLeft: `4px solid ${kpi.color}`,
              borderRadius: 12,
              padding: '14px 16px',
              display: 'flex',
              flexDirection: 'column',
              gap: 3,
              cursor: kpi.tab !== 'all' ? 'pointer' : 'default',
              transition: 'all 0.15s ease',
              boxShadow: kpi.active ? '0 4px 14px rgba(90, 22, 69, 0.12)' : '0 1px 3px rgba(0,0,0,0.04)',
            }}
            onMouseEnter={(e) => {
              if (kpi.tab !== 'all') {
                e.currentTarget.style.transform = 'translateY(-2px)'
                e.currentTarget.style.boxShadow = '0 6px 14px rgba(0,0,0,0.08)'
              }
            }}
            onMouseLeave={(e) => {
              if (kpi.tab !== 'all') {
                e.currentTarget.style.transform = 'none'
                e.currentTarget.style.boxShadow = kpi.active
                  ? '0 4px 14px rgba(90, 22, 69, 0.12)'
                  : '0 1px 3px rgba(0,0,0,0.04)'
              }
            }}
            title={kpi.tab !== 'all' ? `Filter by ${kpi.label}` : undefined}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: '#64748b' }}>
                {kpi.label}
              </span>
              <span style={{ fontSize: 15 }}>{kpi.icon}</span>
            </div>
            <span style={{ fontSize: 26, fontWeight: 800, color: kpi.color, lineHeight: 1.1, fontVariantNumeric: 'tabular-nums' }}>
              {kpi.count.toLocaleString()}
            </span>
            <span style={{ fontSize: 11.5, color: '#94a3b8' }}>{kpi.sub}</span>
          </div>
        ))}
      </div>

      {/* Filter and Search Command Bar */}
      <div
        style={{
          background: '#ffffff',
          borderRadius: 12,
          padding: '14px 18px',
          border: '1px solid #ebdbe4',
          marginBottom: 20,
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
          boxShadow: '0 1px 3px rgba(0,0,0,0.03)',
        }}
      >
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
          {/* Real-time search */}
          <div style={{ flex: '1 1 280px', position: 'relative' }}>
            <span style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: '#94a3b8', fontSize: 14 }}>
              🔍
            </span>
            <input
              type="text"
              placeholder="Search by lead name, phone, property title, or tower location…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                width: '100%',
                padding: '9px 12px 9px 34px',
                borderRadius: 8,
                border: '1px solid #cbd5e1',
                fontSize: 13,
                outline: 'none',
                boxSizing: 'border-box',
              }}
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                style={{
                  position: 'absolute',
                  right: 10,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'none',
                  border: 'none',
                  color: '#94a3b8',
                  cursor: 'pointer',
                  fontSize: 12,
                }}
              >
                ✕
              </button>
            )}
          </div>

          {/* Quick window tabs */}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {[
              ['all', 'All Windows'],
              ['today', "Today's Schedule"],
              ['upcoming', 'Upcoming'],
              ['overdue', 'Overdue'],
              ['conflicts', '⚠ Conflicts'],
            ].map(([wKey, wLabel]) => {
              const isSelected = windowFilter === wKey
              return (
                <button
                  key={wKey}
                  type="button"
                  onClick={() => {
                    setWindowFilter(wKey)
                    setSearchParams((p) => {
                      const n = new URLSearchParams(p)
                      if (wKey === 'all') n.delete('window')
                      else n.set('window', wKey)
                      return n
                    })
                  }}
                  style={{
                    padding: '7px 14px',
                    borderRadius: 8,
                    fontSize: 12.5,
                    fontWeight: isSelected ? 700 : 500,
                    border: isSelected ? '1px solid #5a1645' : '1px solid #e2e8f0',
                    background: isSelected ? '#5a1645' : '#ffffff',
                    color: isSelected ? '#ffffff' : '#475569',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                >
                  {wLabel}
                </button>
              )
            })}
          </div>
        </div>

        {/* Dropdown Filters */}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', paddingTop: 10, borderTop: '1px solid #f1f5f9' }}>
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            style={{
              padding: '7px 12px',
              borderRadius: 8,
              border: '1px solid #cbd5e1',
              fontSize: 12.5,
              color: '#334155',
              background: '#fff',
            }}
          >
            <option value="">All appointment types</option>
            {APPOINTMENT_TYPES.map(([k, l]) => (
              <option key={k} value={k}>{l}</option>
            ))}
          </select>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            style={{
              padding: '7px 12px',
              borderRadius: 8,
              border: '1px solid #cbd5e1',
              fontSize: 12.5,
              color: '#334155',
              background: '#fff',
            }}
          >
            {APPOINTMENT_STATUSES.map(([k, l]) => (
              <option key={k} value={k}>{l}</option>
            ))}
          </select>

          {(typeFilter || statusFilter || windowFilter !== 'all' || searchQuery) && (
            <button
              type="button"
              onClick={() => {
                setTypeFilter('')
                setStatusFilter('')
                setWindowFilter('all')
                setSearchQuery('')
                setSearchParams({})
              }}
              style={{
                background: 'none',
                border: 'none',
                color: '#5a1645',
                fontSize: 12.5,
                fontWeight: 600,
                cursor: 'pointer',
                textDecoration: 'underline',
              }}
            >
              Reset filters
            </button>
          )}

          <div style={{ marginLeft: 'auto', fontSize: 12.5, color: '#64748b' }}>
            Showing <b>{filteredItems.length}</b> of {total} appointments
          </div>
        </div>
      </div>

      {/* Main Appointments Feed */}
      <section style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {loading && (
          <div style={{ padding: 48, textAlign: 'center', background: '#fff', borderRadius: 14, border: '1px solid #ebdbe4' }}>
            <div className="ax-spin" style={{ margin: '0 auto 12px' }} />
            <span style={{ color: '#64748b', fontSize: 14 }}>Loading viewing dossiers and calendar slots…</span>
          </div>
        )}

        {!loading && error && (
          <div style={{ padding: 16, background: '#fef2f2', border: '1px solid #fecdd3', borderRadius: 10, color: '#991b1b' }}>
            ⚠ {error}
          </div>
        )}

        {!loading && !error && filteredItems.length === 0 && (
          <div
            style={{
              padding: 56,
              textAlign: 'center',
              background: '#ffffff',
              borderRadius: 14,
              border: '1px dashed #cbd5e1',
            }}
          >
            <span style={{ fontSize: 36, display: 'block', marginBottom: 10 }}>📅</span>
            <h3 style={{ margin: 0, color: '#0f172a', fontSize: 17, fontWeight: 700 }}>No appointments found</h3>
            <p style={{ margin: '6px 0 16px', color: '#64748b', fontSize: 13.5 }}>
              There are no scheduled viewings matching your current filter criteria.
            </p>
            <button
              type="button"
              onClick={() => setCreateModalOpen(true)}
              style={{
                background: '#5a1645',
                color: '#fff',
                padding: '8px 18px',
                borderRadius: 8,
                border: 'none',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              ＋ Schedule First Appointment
            </button>
          </div>
        )}

        {/* Appointment Cards */}
        {!loading && filteredItems.map((a) => {
          const isActive = a.status === 'scheduled' || a.status === 'confirmed' || a.status === 'rescheduled'
          const leadObj = leads.find((l) => l.id === a.lead_id)
          const propObj = properties.find((p) => p.id === a.property_id)
          const relTag = getRelativeTag(a.start_at)

          // Status colors
          const statusStyle = {
            confirmed: { bg: '#ecfdf5', color: '#065f46', border: '#a7f3d0', label: '✓ Confirmed' },
            scheduled: { bg: '#fffbeb', color: '#92400e', border: '#fde68a', label: '⏳ Scheduled' },
            rescheduled: { bg: '#f5f3ff', color: '#5b21b6', border: '#ddd6fe', label: '🔄 Rescheduled' },
            completed: { bg: '#f0f9ff', color: '#0369a1', border: '#bae6fd', label: '✓ Completed' },
            cancelled: { bg: '#fff1f2', color: '#9f1239', border: '#fecdd3', label: '✕ Cancelled' },
            no_show: { bg: '#fef2f2', color: '#991b1b', border: '#fecaca', label: 'No-Show' },
          }[a.status] || { bg: '#f8fafc', color: '#475569', border: '#e2e8f0', label: a.status }

          const methodMeta = MEETING_METHODS.find(([k]) => k === a.meeting_method) || ['in_person', a.meeting_method, '🏢']

          return (
            <div
              key={a.id}
              style={{
                background: '#ffffff',
                borderRadius: 14,
                border: a.property_availability_conflict ? '1.5px solid #dc2626' : '1px solid #ebdbe4',
                borderLeft: a.property_availability_conflict
                  ? '6px solid #dc2626'
                  : a.status === 'confirmed'
                    ? '6px solid #10b981'
                    : a.status === 'rescheduled'
                      ? '6px solid #7c3aed'
                      : a.status === 'completed'
                        ? '6px solid #0284c7'
                        : '6px solid #5a1645',
                padding: '18px 22px',
                boxShadow: '0 2px 8px rgba(90, 22, 69, 0.04)',
                display: 'flex',
                flexDirection: 'column',
                gap: 14,
                transition: 'all 0.15s ease',
              }}
            >
              {/* Card Top Strip */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 10 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span
                    style={{
                      fontWeight: 800,
                      color: '#5a1645',
                      fontSize: 14,
                      background: 'rgba(90, 22, 69, 0.07)',
                      padding: '3px 8px',
                      borderRadius: 6,
                    }}
                  >
                    #{a.id}
                  </span>

                  <span style={{ fontSize: 15, fontWeight: 700, color: '#0f172a' }}>
                    {APPOINTMENT_TYPES.find(([k]) => k === a.appointment_type)?.[1] || a.appointment_type}
                  </span>

                  {/* Status badge */}
                  <span
                    style={{
                      fontSize: 11.5,
                      fontWeight: 700,
                      padding: '3px 10px',
                      borderRadius: 999,
                      background: statusStyle.bg,
                      color: statusStyle.color,
                      border: `1px solid ${statusStyle.border}`,
                    }}
                  >
                    {statusStyle.label}
                  </span>

                  {/* Method badge */}
                  <span
                    style={{
                      fontSize: 11.5,
                      fontWeight: 600,
                      padding: '3px 9px',
                      borderRadius: 6,
                      background: '#f8fafc',
                      color: '#475569',
                      border: '1px solid #e2e8f0',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 4,
                    }}
                  >
                    <span>{methodMeta[2]}</span>
                    <span>{methodMeta[1]}</span>
                  </span>

                  {/* Pending customer action alert */}
                  {a.customer_confirmation_status === 'pending' && (
                    <span
                      style={{
                        fontSize: 11.5,
                        fontWeight: 700,
                        padding: '3px 9px',
                        borderRadius: 6,
                        background: '#fef3c7',
                        color: '#92400e',
                        border: '1px solid #fde68a',
                      }}
                    >
                      ⏳ Client Confirmation Pending
                    </span>
                  )}

                  {/* Conflict override tag */}
                  {a.conflict_override_reason && (
                    <span
                      style={{
                        fontSize: 11,
                        padding: '2px 8px',
                        borderRadius: 6,
                        background: '#fee2e2',
                        color: '#991b1b',
                        fontWeight: 600,
                      }}
                      title={a.conflict_override_reason}
                    >
                      ⚡ Override: {a.conflict_override_reason}
                    </span>
                  )}
                </div>

                {/* Relative Tag & Calendar Export */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  {relTag && (
                    <span
                      style={{
                        fontSize: 11.5,
                        fontWeight: 700,
                        padding: '3px 9px',
                        borderRadius: 6,
                        background: relTag.bg,
                        color: relTag.color,
                      }}
                    >
                      {relTag.label}
                    </span>
                  )}

                  <button
                    type="button"
                    onClick={() => downloadIcsFile(a)}
                    style={{
                      background: 'none',
                      border: '1px solid #cbd5e1',
                      borderRadius: 6,
                      padding: '3px 8px',
                      fontSize: 11.5,
                      color: '#475569',
                      cursor: 'pointer',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 4,
                    }}
                    title="Export appointment to Outlook / Apple / Google Calendar"
                  >
                    <span>🗓</span> .ICS
                  </button>
                </div>
              </div>

              {/* Conflict Alert Banner if property is unapproved / off-market */}
              {a.property_availability_conflict && (
                <div
                  style={{
                    padding: '10px 14px',
                    borderRadius: 8,
                    background: '#fef2f2',
                    border: '1px solid #fecaca',
                    color: '#991b1b',
                    fontSize: 13,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                  }}
                >
                  <span style={{ fontSize: 16 }}>⚠</span>
                  <div>
                    <b>Property Availability Conflict:</b>{' '}
                    {a.property_conflict_detail || `Listing #${a.property_id} is no longer available on market.`}
                  </div>
                </div>
              )}

              {/* Time & Location Bar */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 16,
                  flexWrap: 'wrap',
                  background: '#fcf8fa',
                  padding: '10px 14px',
                  borderRadius: 8,
                  border: '1px solid #f0e6ed',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#0f172a' }}>
                  <span style={{ fontSize: 15 }}>🕒</span>
                  <b>{fmtDubaiDateTime(a.start_at)} → {fmtDubaiDateTime(a.end_at)}</b>
                </div>

                {a.location_or_link && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#5a1645' }}>
                    <span style={{ fontSize: 14 }}>📍</span>
                    <span>{a.location_or_link}</span>
                    <a
                      href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(a.location_or_link)}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ fontSize: 11.5, color: '#0284c7', textDecoration: 'none', marginLeft: 4, fontWeight: 600 }}
                    >
                      Directions ↗
                    </a>
                  </div>
                )}
              </div>

              {/* Dossier Grid: Customer Lead Details vs Property Specs */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
                  gap: 14,
                }}
              >
                {/* Customer Lead Box */}
                <div
                  style={{
                    padding: '12px 14px',
                    background: '#ffffff',
                    borderRadius: 10,
                    border: '1px solid #e2e8f0',
                    display: 'flex',
                    gap: 12,
                    alignItems: 'flex-start',
                  }}
                >
                  <div
                    style={{
                      width: 38,
                      height: 38,
                      borderRadius: '50%',
                      background: 'linear-gradient(135deg, #5a1645 0%, #3a0c26 100%)',
                      color: '#e8bd68',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontWeight: 700,
                      fontSize: 15,
                      flexShrink: 0,
                    }}
                  >
                    {(a.lead_name || 'C').slice(0, 1).toUpperCase()}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 2 }}>
                      <Link
                        to={`/agent/leads/${a.lead_id}`}
                        style={{
                          fontSize: 13.5,
                          fontWeight: 700,
                          color: '#5a1645',
                          textDecoration: 'none',
                        }}
                      >
                        #{a.lead_id} {a.lead_name || 'Anonymous Client'}
                      </Link>
                      {leadObj?.temperature && (
                        <span
                          style={{
                            fontSize: 10.5,
                            fontWeight: 700,
                            padding: '1px 6px',
                            borderRadius: 4,
                            background: leadObj.temperature === 'hot' ? '#fee2e2' : '#fef3c7',
                            color: leadObj.temperature === 'hot' ? '#b91c1c' : '#b45309',
                          }}
                        >
                          {leadObj.temperature === 'hot' ? '🔥 HOT' : '⚡ WARM'}
                        </span>
                      )}
                    </div>

                    <div style={{ fontSize: 12, color: '#64748b', display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 4 }}>
                      {leadObj?.phone && (
                        <a
                          href={`tel:${leadObj.phone}`}
                          style={{ color: '#0284c7', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 3 }}
                        >
                          📞 {leadObj.phone}
                        </a>
                      )}
                      {leadObj?.phone && (
                        <a
                          href={`https://wa.me/${leadObj.phone.replace(/[^0-9]/g, '')}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ color: '#16a34a', textDecoration: 'none', fontWeight: 600 }}
                        >
                          💬 WhatsApp
                        </a>
                      )}
                      {leadObj?.email && (
                        <a href={`mailto:${leadObj.email}`} style={{ color: '#64748b', textDecoration: 'none' }}>
                          ✉ {leadObj.email}
                        </a>
                      )}
                    </div>
                  </div>
                </div>

                {/* Property Specification Box */}
                {a.property_id ? (
                  <div
                    style={{
                      padding: '12px 14px',
                      background: '#ffffff',
                      borderRadius: 10,
                      border: '1px solid #e2e8f0',
                      display: 'flex',
                      gap: 12,
                      alignItems: 'flex-start',
                    }}
                  >
                    <span style={{ fontSize: 24, lineHeight: 1 }}>🏢</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 6 }}>
                        <Link
                          to={`/agent/properties/${a.property_id}`}
                          style={{
                            fontSize: 13.5,
                            fontWeight: 700,
                            color: '#0f172a',
                            textDecoration: 'none',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                            display: 'block',
                          }}
                        >
                          #{a.property_id} {a.property_title || 'Listing'}
                        </Link>
                        <span
                          style={{
                            fontSize: 10.5,
                            padding: '1px 6px',
                            borderRadius: 4,
                            fontWeight: 600,
                            background: a.property_availability === 'available' ? '#ecfdf5' : '#fee2e2',
                            color: a.property_availability === 'available' ? '#166534' : '#991b1b',
                          }}
                        >
                          {a.property_availability || 'available'}
                        </span>
                      </div>

                      <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
                        {a.property_location || (propObj ? propObj.location : 'UAE')}
                        {propObj?.price != null && (
                          <span style={{ marginLeft: 8, fontWeight: 700, color: '#5a1645' }}>
                            · AED {Number(propObj.price).toLocaleString()}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div
                    style={{
                      padding: '12px 14px',
                      background: '#f8fafc',
                      borderRadius: 10,
                      border: '1px dashed #cbd5e1',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      color: '#64748b',
                      fontSize: 12.5,
                    }}
                  >
                    <span>💬</span> General consultation meeting (no specific property linked)
                  </div>
                )}
              </div>

              {/* Host Agent & Preparation Notes */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, fontSize: 12.5 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#475569' }}>
                  <b>Host:</b>
                  {canAssign && salesAgents.length > 0 ? (
                    <select
                      style={{
                        padding: '3px 8px',
                        fontSize: 12,
                        fontWeight: 600,
                        background: '#fff',
                        border: '1px solid #cbd5e1',
                        borderRadius: 6,
                        color: '#1e293b',
                        cursor: 'pointer',
                      }}
                      value={a.assigned_agent_id || ''}
                      onChange={async (e) => {
                        const newId = Number(e.target.value)
                        if (!newId || newId === a.assigned_agent_id) return
                        try {
                          await api.updateAgentAppointment(a.id, { assigned_agent_id: newId })
                          loadAll()
                        } catch (err) {
                          alert('Failed to reassign appointment: ' + err.message)
                        }
                      }}
                      title="Reassign viewing host"
                    >
                      {salesAgents.map((ag) => (
                        <option key={ag.id} value={ag.id}>
                          {ag.full_name} ({ag.role || 'Agent'})
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span>{a.assigned_agent_name || `Agent #${a.assigned_agent_id || 'Staff'}`}</span>
                  )}
                </div>
                {a.notes && (
                  <div style={{ background: '#f8fafc', padding: '4px 10px', borderRadius: 6, color: '#475569', fontSize: 12 }}>
                    📝 <b>Prep Notes:</b> {a.notes}
                  </div>
                )}
              </div>

              {/* Outcome Feedback Strip (if completed or outcome recorded) */}
              {a.viewing_outcome && (
                <div
                  style={{
                    padding: '10px 14px',
                    borderRadius: 8,
                    background: '#f0fdf4',
                    border: '1px solid #bbf7d0',
                    color: '#166534',
                    fontSize: 13,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 4,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 700 }}>
                    <span>⭐</span>
                    <span>
                      Outcome: {VIEWING_OUTCOMES.find(([k]) => k === a.viewing_outcome)?.[1] || a.viewing_outcome}
                    </span>
                  </div>
                  {a.customer_feedback && (
                    <div style={{ fontSize: 12.5, color: '#14532d' }}>
                      <b>Client Feedback:</b> “{a.customer_feedback}”
                    </div>
                  )}
                  {a.next_action && (
                    <div style={{ fontSize: 12.5, color: '#15803d' }}>
                      <b>Next Action:</b> {a.next_action}
                    </div>
                  )}
                </div>
              )}

              {/* Cancellation Reason if cancelled */}
              {a.cancellation_reason && (
                <div style={{ fontSize: 12, color: '#dc2626', background: '#fef2f2', padding: '6px 10px', borderRadius: 6 }}>
                  ✕ <b>Cancellation Reason:</b> {a.cancellation_reason}
                </div>
              )}

              {/* Action Buttons Row */}
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  gap: 8,
                  paddingTop: 12,
                  borderTop: '1px solid #f1f5f9',
                }}
              >
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {/* Pending Client Request Actions */}
                  {a.customer_confirmation_status === 'pending' && (
                    <>
                      <button
                        type="button"
                        disabled={actionBusy}
                        onClick={() => handleConfirm(a)}
                        style={{
                          background: '#10b981',
                          color: '#fff',
                          border: 'none',
                          padding: '6px 14px',
                          borderRadius: 6,
                          fontWeight: 700,
                          fontSize: 12.5,
                          cursor: 'pointer',
                        }}
                      >
                        ✓ Accept Request
                      </button>
                      <button
                        type="button"
                        disabled={actionBusy}
                        onClick={() => handleRejectViewingRequest(a)}
                        style={{
                          background: '#fff',
                          color: '#dc2626',
                          border: '1px solid #fca5a5',
                          padding: '6px 14px',
                          borderRadius: 6,
                          fontWeight: 600,
                          fontSize: 12.5,
                          cursor: 'pointer',
                        }}
                      >
                        ✕ Decline
                      </button>
                    </>
                  )}

                  {/* Scheduled -> Confirm */}
                  {a.status === 'scheduled' && a.customer_confirmation_status !== 'pending' && (
                    <button
                      type="button"
                      disabled={actionBusy}
                      onClick={() => handleConfirm(a)}
                      style={{
                        background: '#5a1645',
                        color: '#fff',
                        border: 'none',
                        padding: '6px 14px',
                        borderRadius: 6,
                        fontWeight: 600,
                        fontSize: 12.5,
                        cursor: 'pointer',
                      }}
                    >
                      ✓ Confirm Appointment
                    </button>
                  )}

                  {/* Active -> Record Outcome */}
                  {isActive && (
                    <button
                      type="button"
                      disabled={actionBusy}
                      onClick={() => openOutcomeModal(a)}
                      style={{
                        background: 'linear-gradient(135deg, #5a1645 0%, #3a0c26 100%)',
                        color: '#e8bd68',
                        border: '1px solid #e8bd68',
                        padding: '6px 14px',
                        borderRadius: 6,
                        fontWeight: 700,
                        fontSize: 12.5,
                        cursor: 'pointer',
                      }}
                    >
                      📝 Record Outcome
                    </button>
                  )}

                  {/* Active -> Reschedule */}
                  {isActive && (
                    <button
                      type="button"
                      disabled={actionBusy}
                      onClick={() => openRescheduleModal(a)}
                      style={{
                        background: '#fff',
                        color: '#475569',
                        border: '1px solid #cbd5e1',
                        padding: '6px 12px',
                        borderRadius: 6,
                        fontWeight: 600,
                        fontSize: 12.5,
                        cursor: 'pointer',
                      }}
                    >
                      🔄 Reschedule
                    </button>
                  )}

                  {/* Active -> Cancel */}
                  {isActive && (
                    <button
                      type="button"
                      disabled={actionBusy}
                      onClick={() => handleCancel(a)}
                      style={{
                        background: '#fff',
                        color: '#94a3b8',
                        border: '1px solid #e2e8f0',
                        padding: '6px 12px',
                        borderRadius: 6,
                        fontSize: 12,
                        cursor: 'pointer',
                      }}
                    >
                      Cancel
                    </button>
                  )}
                </div>

                {/* Offer Pipeline Shortcut if Completed + Interested */}
                {a.status === 'completed' && a.viewing_outcome === 'interested' && a.property_id && (
                  <button
                    type="button"
                    onClick={() => navigate(`/agent/deals?new_offer=1&lead_id=${a.lead_id}&property_id=${a.property_id}`)}
                    style={{
                      background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
                      color: '#ffffff',
                      border: 'none',
                      padding: '7px 16px',
                      borderRadius: 8,
                      fontWeight: 700,
                      fontSize: 12.5,
                      cursor: 'pointer',
                      boxShadow: '0 2px 8px rgba(16, 185, 129, 0.3)',
                    }}
                  >
                    ＋ Create Formal Offer →
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </section>

      {/* ========================================================================= */}
      {/* 1. SCHEDULE APPOINTMENT / VIEWING MODAL (Centered Popup Dialog)            */}
      {/* ========================================================================= */}
      {createModalOpen && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 10001,
            background: 'rgba(20, 8, 16, 0.65)',
            backdropFilter: 'blur(6px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 20,
          }}
          onClick={(e) => {
            if (e.target === e.currentTarget) setCreateModalOpen(false)
          }}
        >
          <div
            style={{
              width: '100%',
              maxWidth: 780,
              maxHeight: '92vh',
              overflowY: 'auto',
              background: '#ffffff',
              borderRadius: 16,
              boxShadow: '0 24px 48px -12px rgba(0, 0, 0, 0.35)',
              border: '1px solid #e8bd68',
              padding: '24px 28px',
              position: 'relative',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18, borderBottom: '1px solid #f1f5f9', paddingBottom: 14 }}>
              <div>
                <h3 style={{ margin: 0, color: '#5a1645', fontSize: 20, fontWeight: 700 }}>
                  Schedule Viewing or Client Meeting
                </h3>
                <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: 13 }}>
                  Create a confirmed calendar slot with double-booking and property availability protection.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setCreateModalOpen(false)}
                style={{
                  background: 'none',
                  border: 'none',
                  fontSize: 20,
                  color: '#64748b',
                  cursor: 'pointer',
                  padding: 4,
                  lineHeight: 1,
                }}
                aria-label="Close modal"
              >
                ✕
              </button>
            </div>

            {createErr && (
              <div style={{ marginBottom: 14, padding: '10px 14px', background: '#fef2f2', color: '#991b1b', borderRadius: 8, borderLeft: '4px solid #ef4444', fontSize: 13 }}>
                ⚠ {createErr}
              </div>
            )}

            {conflictAlert && (
              <div style={{ marginBottom: 14, padding: '12px 14px', background: '#fffbeb', color: '#92400e', borderRadius: 8, border: '1px solid #fde68a', fontSize: 13 }}>
                <b>⚠ Agent Double-Booking Conflict ({conflictAlert.conflicts?.length || 1} overlapping slot):</b>
                <ul style={{ margin: '6px 0', paddingLeft: 20, fontSize: 12.5 }}>
                  {(conflictAlert.conflicts || []).map((c) => (
                    <li key={c.id}>
                      Appointment #{c.id} ({c.appointment_type}) · {fmtDubaiDateTime(c.start_at)} → {fmtDubaiDateTime(c.end_at)}
                    </li>
                  ))}
                </ul>
                <label style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8, cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={form.conflict_override}
                    onChange={(e) => setForm({ ...form, conflict_override: e.target.checked })}
                  />
                  <b style={{ color: '#78350f' }}>Authorize scheduling conflict with documented business override</b>
                </label>
                {form.conflict_override && (
                  <input
                    type="text"
                    style={{
                      width: '100%',
                      marginTop: 8,
                      padding: '8px 12px',
                      borderRadius: 6,
                      border: '1px solid #f59e0b',
                      fontSize: 12.5,
                      boxSizing: 'border-box',
                    }}
                    placeholder="Enter reason (e.g. colleague attending / adjacent tower viewing)…"
                    value={form.conflict_override_reason}
                    onChange={(e) => setForm({ ...form, conflict_override_reason: e.target.value })}
                  />
                )}
              </div>
            )}

            {/* Form */}
            <form onSubmit={handleCreate} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              {/* Customer Lead */}
              <label style={{ gridColumn: '1 / -1', display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>Customer Lead *</span>
                <select
                  value={form.lead_id}
                  onChange={(e) => setForm({ ...form, lead_id: e.target.value })}
                  required
                  style={{ padding: '9px 12px', borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 13 }}
                >
                  <option value="">— Select registered customer lead —</option>
                  {leads.map((l) => (
                    <option key={l.id} value={String(l.id)}>
                      #{l.id} · {l.name || 'Anonymous'} {l.phone ? `(${l.phone})` : ''} · {l.preferred_location || l.emirate || 'Dubai'}
                    </option>
                  ))}
                </select>
              </label>

              {/* Host Agent Assignment */}
              {canAssign && salesAgents.length > 0 && (
                <label style={{ gridColumn: '1 / -1', display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>Assigned Host Agent</span>
                  <select
                    value={form.assigned_agent_id}
                    onChange={(e) => setForm({ ...form, assigned_agent_id: e.target.value })}
                    style={{ padding: '9px 12px', borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 13 }}
                  >
                    <option value="">— Current Agent / Default Host —</option>
                    {salesAgents.map((ag) => (
                      <option key={ag.id} value={String(ag.id)}>
                        {ag.full_name} ({ag.role || 'Agent'})
                      </option>
                    ))}
                  </select>
                </label>
              )}

              {/* Appointment Type */}
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>Appointment Type *</span>
                <select
                  value={form.appointment_type}
                  onChange={(e) => setForm({ ...form, appointment_type: e.target.value })}
                  style={{ padding: '9px 12px', borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 13 }}
                >
                  {APPOINTMENT_TYPES.map(([k, l]) => (
                    <option key={k} value={k}>{l}</option>
                  ))}
                </select>
              </label>

              {/* Meeting Method */}
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>Meeting Method *</span>
                <select
                  value={form.meeting_method}
                  onChange={(e) => setForm({ ...form, meeting_method: e.target.value })}
                  style={{ padding: '9px 12px', borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 13 }}
                >
                  {MEETING_METHODS.map(([k, l, icon]) => (
                    <option key={k} value={k}>{icon} {l}</option>
                  ))}
                </select>
              </label>

              {/* Property Selector */}
              <label style={{ gridColumn: '1 / -1', display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>
                  Property Listing {form.appointment_type === 'viewing' ? '*' : '(Optional)'}
                </span>
                <select
                  value={form.property_id}
                  onChange={(e) => handlePropertySelect(e.target.value)}
                  required={form.appointment_type === 'viewing'}
                  style={{ padding: '9px 12px', borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 13 }}
                >
                  <option value="">— Select approved property listing —</option>
                  {properties.map((p) => (
                    <option key={p.id} value={String(p.id)}>
                      #{p.id} · {p.title || p.property_type} · {p.location} {p.price ? `(AED ${Number(p.price).toLocaleString()})` : ''}
                    </option>
                  ))}
                </select>
              </label>

              {/* Start Date & Time */}
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>Start Date &amp; Time (Dubai GST) *</span>
                <input
                  type="datetime-local"
                  value={form.start_at}
                  onChange={(e) => setForm({ ...form, start_at: e.target.value })}
                  required
                  style={{ padding: '9px 12px', borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 13 }}
                />
              </label>

              {/* End Date & Time */}
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>End Date &amp; Time (Dubai GST) *</span>
                <input
                  type="datetime-local"
                  value={form.end_at}
                  onChange={(e) => setForm({ ...form, end_at: e.target.value })}
                  required
                  style={{ padding: '9px 12px', borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 13 }}
                />
              </label>

              {/* Meeting Location */}
              <label style={{ gridColumn: '1 / -1', display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>Meeting Location / Tower Lobby / Link</span>
                <input
                  type="text"
                  placeholder="e.g. Marina Gate Tower 1 Main Lobby / Zoom / Office 1002…"
                  value={form.location_or_link}
                  onChange={(e) => setForm({ ...form, location_or_link: e.target.value })}
                  style={{ padding: '9px 12px', borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 13 }}
                />
              </label>

              {/* Preparation Notes */}
              <label style={{ gridColumn: '1 / -1', display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>Preparation Notes</span>
                <textarea
                  rows={2}
                  placeholder="e.g. Bring payment plan breakdown and DLD registration checklist…"
                  value={form.notes}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })}
                  style={{ padding: '9px 12px', borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 13, resize: 'vertical' }}
                />
              </label>

              {/* Form Actions */}
              <div style={{ gridColumn: '1 / -1', display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 10, paddingTop: 14, borderTop: '1px solid #f1f5f9' }}>
                <button
                  type="button"
                  onClick={() => setCreateModalOpen(false)}
                  style={{
                    background: '#fff',
                    border: '1px solid #cbd5e1',
                    padding: '8px 18px',
                    borderRadius: 8,
                    fontSize: 13,
                    color: '#64748b',
                    cursor: 'pointer',
                  }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createBusy}
                  style={{
                    background: 'linear-gradient(135deg, #5a1645 0%, #3a0c26 100%)',
                    color: '#e8bd68',
                    border: '1px solid #e8bd68',
                    padding: '8px 24px',
                    borderRadius: 8,
                    fontWeight: 700,
                    fontSize: 13.5,
                    cursor: 'pointer',
                  }}
                >
                  {createBusy ? 'Scheduling…' : '✓ Confirm & Schedule'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* 2. RECORD OUTCOME MODAL (Centered Popup Dialog)                            */}
      {/* ========================================================================= */}
      {outcomeModalAppt && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 10002,
            background: 'rgba(20, 8, 16, 0.65)',
            backdropFilter: 'blur(6px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 20,
          }}
          onClick={(e) => {
            if (e.target === e.currentTarget) setOutcomeModalAppt(null)
          }}
        >
          <div
            style={{
              width: '100%',
              maxWidth: 580,
              background: '#ffffff',
              borderRadius: 16,
              boxShadow: '0 24px 48px -12px rgba(0, 0, 0, 0.35)',
              border: '1px solid #10b981',
              padding: '24px 28px',
              position: 'relative',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, borderBottom: '1px solid #f1f5f9', paddingBottom: 12 }}>
              <div>
                <h3 style={{ margin: 0, color: '#065f46', fontSize: 18, fontWeight: 700 }}>
                  Record Viewing Outcome — #{outcomeModalAppt.id}
                </h3>
                <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: 12.5 }}>
                  Log customer interest, feedback, and trigger offer negotiation pipeline.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setOutcomeModalAppt(null)}
                style={{ background: 'none', border: 'none', fontSize: 18, color: '#64748b', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleOutcomeSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>Attendance Status</span>
                <select
                  value={outcomeForm.status}
                  onChange={(e) => setOutcomeForm({ ...outcomeForm, status: e.target.value })}
                  style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 13 }}
                >
                  <option value="completed">Completed — Customer attended visit</option>
                  <option value="no_show">Customer No-Show / Cancelled on spot</option>
                </select>
              </label>

              {outcomeForm.status === 'completed' && (
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>Viewing Result / Interest Level *</span>
                  <select
                    value={outcomeForm.viewing_outcome}
                    onChange={(e) => setOutcomeForm({ ...outcomeForm, viewing_outcome: e.target.value })}
                    style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 13 }}
                  >
                    {VIEWING_OUTCOMES.map(([k, l, icon]) => (
                      <option key={k} value={k}>{icon} {l}</option>
                    ))}
                  </select>
                </label>
              )}

              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>Client Feedback &amp; Impressions</span>
                <textarea
                  rows={3}
                  placeholder="e.g. Loved the marina view and balcony size. Wants to negotiate on parking slot or check post-handover payment plan…"
                  value={outcomeForm.customer_feedback}
                  onChange={(e) => setOutcomeForm({ ...outcomeForm, customer_feedback: e.target.value })}
                  style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 13, resize: 'vertical' }}
                />
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>Next Action Follow-Up</span>
                <input
                  type="text"
                  placeholder="e.g. Send draft MOU / schedule second visit with spouse…"
                  value={outcomeForm.next_action}
                  onChange={(e) => setOutcomeForm({ ...outcomeForm, next_action: e.target.value })}
                  style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 13 }}
                />
              </label>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 8, paddingTop: 14, borderTop: '1px solid #f1f5f9' }}>
                <button
                  type="button"
                  onClick={() => setOutcomeModalAppt(null)}
                  style={{ background: '#fff', border: '1px solid #cbd5e1', padding: '8px 16px', borderRadius: 8, fontSize: 13, color: '#64748b', cursor: 'pointer' }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionBusy}
                  style={{
                    background: '#10b981',
                    color: '#fff',
                    border: 'none',
                    padding: '8px 20px',
                    borderRadius: 8,
                    fontWeight: 700,
                    fontSize: 13,
                    cursor: 'pointer',
                  }}
                >
                  {actionBusy ? 'Saving…' : '✓ Save Outcome'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* 3. RESCHEDULE MODAL (Centered Popup Dialog)                                */}
      {/* ========================================================================= */}
      {rescheduleModalAppt && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 10002,
            background: 'rgba(20, 8, 16, 0.65)',
            backdropFilter: 'blur(6px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 20,
          }}
          onClick={(e) => {
            if (e.target === e.currentTarget) setRescheduleModalAppt(null)
          }}
        >
          <div
            style={{
              width: '100%',
              maxWidth: 540,
              background: '#ffffff',
              borderRadius: 16,
              boxShadow: '0 24px 48px -12px rgba(0, 0, 0, 0.35)',
              border: '1px solid #7c3aed',
              padding: '24px 28px',
              position: 'relative',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, borderBottom: '1px solid #f1f5f9', paddingBottom: 12 }}>
              <div>
                <h3 style={{ margin: 0, color: '#5b21b6', fontSize: 18, fontWeight: 700 }}>
                  Reschedule Appointment — #{rescheduleModalAppt.id}
                </h3>
                <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: 12.5 }}>
                  Move appointment to a new date/time slot in Dubai GST.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setRescheduleModalAppt(null)}
                style={{ background: 'none', border: 'none', fontSize: 18, color: '#64748b', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleRescheduleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>New Start Date &amp; Time (GST) *</span>
                <input
                  type="datetime-local"
                  required
                  value={rescheduleForm.start_at}
                  onChange={(e) => setRescheduleForm({ ...rescheduleForm, start_at: e.target.value })}
                  style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 13 }}
                />
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>New End Date &amp; Time (GST) *</span>
                <input
                  type="datetime-local"
                  required
                  value={rescheduleForm.end_at}
                  onChange={(e) => setRescheduleForm({ ...rescheduleForm, end_at: e.target.value })}
                  style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 13 }}
                />
              </label>

              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>Reason for Rescheduling *</span>
                <input
                  type="text"
                  required
                  placeholder="e.g. Client requested evening slot / landlord unavailable…"
                  value={rescheduleForm.reason}
                  onChange={(e) => setRescheduleForm({ ...rescheduleForm, reason: e.target.value })}
                  style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 13 }}
                />
              </label>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 8, paddingTop: 14, borderTop: '1px solid #f1f5f9' }}>
                <button
                  type="button"
                  onClick={() => setRescheduleModalAppt(null)}
                  style={{ background: '#fff', border: '1px solid #cbd5e1', padding: '8px 16px', borderRadius: 8, fontSize: 13, color: '#64748b', cursor: 'pointer' }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={actionBusy}
                  style={{
                    background: '#7c3aed',
                    color: '#fff',
                    border: 'none',
                    padding: '8px 20px',
                    borderRadius: 8,
                    fontWeight: 700,
                    fontSize: 13,
                    cursor: 'pointer',
                  }}
                >
                  {actionBusy ? 'Rescheduling…' : 'Confirm Reschedule'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
