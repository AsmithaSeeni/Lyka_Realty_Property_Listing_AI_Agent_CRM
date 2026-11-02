import React from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api.js'

const INTENTS = [
  ['buy', 'Buy'], ['rent', 'Rent'], ['lease', 'Lease'], ['unknown', 'Unknown'],
]
const PERIODS = [
  ['', '— none —'], ['monthly', 'Per month'], ['yearly', 'Per year'],
  ['one_time', 'One time'],
]
const EMIRATES = [
  ['', '— select emirate —'],
  ['Dubai', 'Dubai'],
  ['Abu Dhabi', 'Abu Dhabi'],
  ['Sharjah', 'Sharjah'],
  ['Ajman', 'Ajman'],
  ['Ras Al Khaimah', 'Ras Al Khaimah'],
  ['Fujairah', 'Fujairah'],
  ['Umm Al Quwain', 'Umm Al Quwain'],
]
const INVESTMENT_PURPOSES = [
  ['', '— select purpose —'],
  ['end_use', 'End use / Family living'],
  ['investment', 'Investment / Rental yield'],
  ['holiday_home', 'Holiday home'],
  ['commercial', 'Commercial'],
]
const FINANCING_TYPES = [
  ['', '— select financing —'],
  ['cash', 'Cash buyer'],
  ['mortgage_preapproved', 'Mortgage (pre-approved)'],
  ['mortgage_needed', 'Mortgage (needs assistance)'],
  ['payment_plan', 'Developer payment plan'],
  ['undecided', 'Undecided'],
]
const LANGUAGES = [
  ['', '— select language —'],
  ['en', 'English'],
  ['ar', 'Arabic'],
  ['hi', 'Hindi'],
  ['ur', 'Urdu'],
  ['ru', 'Russian'],
  ['zh', 'Chinese'],
  ['fr', 'French'],
]

const EMPTY_FORM = {
  name: '', phone: '', email: '', preferred_language: '',
  intent: 'unknown', emirate: '', location: '', property_type: '',
  bedrooms: '', bathrooms: '',
  budget_min: '', budget_max: '', budget_currency: 'AED', budget_period: '',
  investment_purpose: '', financing_type: '', preferred_viewing_time: '',
  amenities: '', preferences: '', timeline: '', timeline_days: '',
  next_action: '', assignment_mode: 'pool', assigned_agent_id: '',
  original_enquiry: '', notes: '',
}

const num = (v) => (v === '' || v == null ? null : Number(v))

/**
 * /agent/leads/new — explicit human-in-the-loop lead creation (Phase 5 + Phase E).
 */
export default function AgentNewLead() {
  const navigate = useNavigate()
  const [extract, setExtract] = React.useState('')
  const [extracting, setExtracting] = React.useState(false)
  const [extractNote, setExtractNote] = React.useState(null)
  const [extraction, setExtraction] = React.useState(null)
  const [form, setForm] = React.useState(EMPTY_FORM)
  const [salesAgents, setSalesAgents] = React.useState([])
  const [confirmed, setConfirmed] = React.useState(false)
  const [saving, setSaving] = React.useState(false)
  const [error, setError] = React.useState('')
  const [duplicate, setDuplicate] = React.useState(null)
  const [idempotencyKey] = React.useState(() => `lead-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`)

  React.useEffect(() => {
    api.agentSalesAgents().then((r) => setSalesAgents(r.results || [])).catch(() => {})
  }, [])

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  const runExtract = async () => {
    const text = extract.trim()
    if (!text) return
    setExtracting(true)
    setExtractNote(null)
    setDuplicate(null)
    try {
      const d = await api.extractEnquiry(text)
      const ex = d.extraction || {}
      const keep = (v, prev) => (v == null || v === '' ? prev : String(v))
      setExtraction(ex)
      setForm((f) => ({
        ...f,
        name: keep(ex.name, f.name),
        phone: keep(ex.phone, f.phone),
        email: keep(ex.email, f.email),
        intent: ex.intent || f.intent,
        property_type: keep(ex.property_type, f.property_type),
        location: keep(ex.location, f.location),
        bedrooms: keep(ex.bedrooms, f.bedrooms),
        bathrooms: keep(ex.bathrooms, f.bathrooms),
        budget_min: keep(ex.budget_min, f.budget_min),
        budget_max: keep(ex.budget_max, f.budget_max),
        budget_currency: keep(ex.budget_currency, f.budget_currency),
        budget_period: keep(ex.budget_period, f.budget_period),
        amenities: (ex.amenities || []).join(', ') || f.amenities,
        preferences: (ex.preferences || []).join(', ') || f.preferences,
        timeline: keep(ex.timeline, f.timeline),
        timeline_days: keep(ex.timeline_days, f.timeline_days),
        original_enquiry: ex.original_enquiry || f.original_enquiry || text,
      }))
      setExtractNote({
        kind: 'ok',
        text: d.note || 'Extraction ready — review every field below before saving.',
      })
    } catch (e) {
      setExtractNote({ kind: 'warn', text: `Extraction unavailable: ${e.message}` })
    } finally {
      setExtracting(false)
    }
  }

  const submit = async (override = false) => {
    if (!confirmed && !override) return
    setError('')

    const trimmedName = form.name.trim()
    if (!trimmedName || trimmedName.length < 2) {
      setError('Lead name is required (minimum 2 characters).')
      return
    }
    const trimmedPhone = form.phone.trim()
    const trimmedEmail = form.email.trim()
    if (!trimmedPhone && !trimmedEmail) {
      setError('At least one contact method (phone number or email) is required to create a lead.')
      return
    }
    if (trimmedEmail) {
      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
      if (!emailRegex.test(trimmedEmail)) {
        setError('Please enter a valid email address (e.g. name@domain.com).')
        return
      }
    }
    if (trimmedPhone) {
      const digits = trimmedPhone.replace(/\D/g, '')
      if (digits.length < 7) {
        setError('Please enter a valid phone number with at least 7 digits.')
        return
      }
    }

    setSaving(true)
    try {
      const list = (v) => v.split(',').map((s) => s.trim()).filter(Boolean)
      const body = {
        name: trimmedName,
        phone: trimmedPhone || null,
        email: trimmedEmail || null,
        preferred_language: form.preferred_language || null,
        intent: form.intent,
        emirate: form.emirate || null,
        property_type: form.property_type.trim() || null,
        location: form.location.trim() || null,
        bedrooms: num(form.bedrooms),
        bathrooms: num(form.bathrooms),
        budget_min: num(form.budget_min),
        budget_max: num(form.budget_max),
        budget_currency: form.budget_currency.trim() || null,
        budget_period: form.budget_period || null,
        investment_purpose: form.investment_purpose || null,
        financing_type: form.financing_type || null,
        preferred_viewing_time: form.preferred_viewing_time.trim() || null,
        amenities: list(form.amenities),
        preferences: list(form.preferences),
        timeline: form.timeline.trim() || null,
        timeline_days: num(form.timeline_days),
        next_action: form.next_action.trim() || null,
        assignment_mode: form.assignment_mode === 'round_robin' ? 'round_robin' : (form.assignment_mode === 'manual' ? 'manual' : null),
        assigned_agent_id: form.assignment_mode === 'manual' && form.assigned_agent_id ? Number(form.assigned_agent_id) : null,
        original_enquiry: form.original_enquiry,
        provenance: extraction?.provenance || {},
        notes: form.notes,
        confirm: true,
        duplicate_override: override,
        idempotency_key: override ? `${idempotencyKey}-override` : idempotencyKey,
      }
      if (body.budget_min != null && body.budget_max != null && body.budget_min > body.budget_max) {
        setError('Budget minimum cannot exceed the maximum.')
        setSaving(false)
        return
      }
      const out = await api.createAgentLead(body)
      navigate(`/agent/leads/${out.lead.id}`)
    } catch (e) {
      if (e.status === 409 && e.detail && e.detail.code === 'duplicate_lead') {
        setDuplicate(e.detail)
      } else if (e.status === 422 && Array.isArray(e.detail)) {
        setError(e.detail.map((d) => d.msg || d.message).join(' | '))
      } else {
        setError(e.message)
      }
      setSaving(false)
    }
  }

  return (
    <div>
      <button className="ax-back" onClick={() => navigate('/agent/leads')}>← Back to leads</button>

      {/* ---------------- Step 1: optional extraction ---------------- */}
      <section className="ax-panel">
        <div className="ax-panel__head">
          <h3>1 · Paste the customer enquiry (optional)</h3>
          <span className="ax-count">review-only — nothing is saved here</span>
        </div>
        <textarea
          className="ax-textarea"
          rows={4}
          placeholder="e.g. Hello, I'm looking for a 3-bedroom villa in Arabian Ranches, budget around 4.5M AED, ready to move within 2 months…"
          value={extract}
          onChange={(e) => setExtract(e.target.value)}
        />
        <button
          className="btn btn-sm"
          style={{ marginTop: 10 }}
          disabled={extracting || !extract.trim()}
          onClick={runExtract}
        >
          {extracting ? 'Extracting…' : 'Extract details with AI'}
        </button>

        {extractNote && (
          <div className={extractNote.kind === 'ok' ? 'ax-ok' : 'ax-warn'}>
            {extractNote.text}
          </div>
        )}

        {extraction && (extraction.missing_fields?.length > 0 || extraction.clarification_questions?.length > 0) && (
          <div style={{ marginTop: 6 }}>
            {extraction.missing_fields?.length > 0 && (
              <>
                <b style={{ fontSize: 13 }}>Missing: </b>
                <div className="ax-qchips">
                  {extraction.missing_fields.map((m) => <span key={m}>{m}</span>)}
                </div>
              </>
            )}
            {extraction.clarification_questions?.length > 0 && (
              <>
                <b style={{ fontSize: 13, display: 'block', marginTop: 10 }}>Ask the customer:</b>
                <div className="ax-qchips">
                  {extraction.clarification_questions.map((q, i) => <span key={i}>“{q}”</span>)}
                </div>
              </>
            )}
          </div>
        )}
      </section>

      {/* ---------------- Step 2: review & confirm ---------------- */}
      <section className="ax-panel" style={{ marginTop: 18 }}>
        <div className="ax-panel__head">
          <h3>2 · Review, qualify &amp; confirm</h3>
          <span className="ax-count">score, priority &amp; completeness computed by server</span>
        </div>

        {duplicate && (
          <div className="ax-warn">
            <b>Possible duplicate lead.</b> {duplicate.message}
            <div style={{ marginTop: 10, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              {duplicate.lead_id != null && (
                <button
                  className="btn btn-sm"
                  onClick={() => navigate(`/agent/leads/${duplicate.lead_id}`)}
                >
                  Open existing lead #{duplicate.lead_id} →
                </button>
              )}
              <button
                className="btn btn-sm btn-ghost"
                disabled={saving}
                onClick={() => submit(true)}
              >
                Keep both — create a separate lead
              </button>
            </div>
          </div>
        )}
        {error && <div className="ax-warn">{error}</div>}

        <div className="ax-form" style={{ marginTop: 8 }}>
          <label className="ax-field">
            <span>Name <b style={{ color: '#b91c1c' }}>*</b></span>
            <input className="ax-input" placeholder="e.g. Rashid Al Mansoori" value={form.name} onChange={(e) => set('name', e.target.value)} required />
          </label>
          <label className="ax-field">
            <span>Phone <span className="ax-muted" style={{ fontSize: 11 }}>(or Email)</span></span>
            <input className="ax-input" placeholder="+971 50 …" value={form.phone} onChange={(e) => set('phone', e.target.value)} />
          </label>
          <label className="ax-field">
            <span>Email <span className="ax-muted" style={{ fontSize: 11 }}>(or Phone)</span></span>
            <input className="ax-input" placeholder="client@example.com" value={form.email} onChange={(e) => set('email', e.target.value)} />
          </label>
          <label className="ax-field">
            <span>Preferred language</span>
            <select className="ax-input" value={form.preferred_language} onChange={(e) => set('preferred_language', e.target.value)}>
              {LANGUAGES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>
          <label className="ax-field">
            <span>Intent (Buy / Rent)</span>
            <select className="ax-input" value={form.intent} onChange={(e) => set('intent', e.target.value)}>
              {INTENTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>
          <label className="ax-field">
            <span>Emirate</span>
            <select className="ax-input" value={form.emirate} onChange={(e) => set('emirate', e.target.value)}>
              {EMIRATES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>
          <label className="ax-field">
            <span>Location / Community</span>
            <input className="ax-input" placeholder="Dubai Marina, Downtown, Saadiyat…" value={form.location} onChange={(e) => set('location', e.target.value)} />
          </label>
          <label className="ax-field">
            <span>Property type</span>
            <input className="ax-input" placeholder="villa / apartment / townhouse…" value={form.property_type} onChange={(e) => set('property_type', e.target.value)} />
          </label>
          <label className="ax-field">
            <span>Bedrooms</span>
            <input className="ax-input" type="number" min="0" max="30" value={form.bedrooms} onChange={(e) => set('bedrooms', e.target.value)} />
          </label>
          <label className="ax-field">
            <span>Bathrooms</span>
            <input className="ax-input" type="number" min="0" max="30" value={form.bathrooms} onChange={(e) => set('bathrooms', e.target.value)} />
          </label>
          <label className="ax-field">
            <span>Budget min</span>
            <input className="ax-input" type="number" min="0" value={form.budget_min} onChange={(e) => set('budget_min', e.target.value)} />
          </label>
          <label className="ax-field">
            <span>Budget max</span>
            <input className="ax-input" type="number" min="0" value={form.budget_max} onChange={(e) => set('budget_max', e.target.value)} />
          </label>
          <label className="ax-field">
            <span>Currency</span>
            <input className="ax-input" placeholder="AED" maxLength={3} value={form.budget_currency} onChange={(e) => set('budget_currency', e.target.value.toUpperCase())} />
          </label>
          <label className="ax-field">
            <span>Budget period</span>
            <select className="ax-input" value={form.budget_period} onChange={(e) => set('budget_period', e.target.value)}>
              {PERIODS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>
          <label className="ax-field">
            <span>Investment / Occupancy purpose</span>
            <select className="ax-input" value={form.investment_purpose} onChange={(e) => set('investment_purpose', e.target.value)}>
              {INVESTMENT_PURPOSES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>
          <label className="ax-field">
            <span>Financing / Mortgage</span>
            <select className="ax-input" value={form.financing_type} onChange={(e) => set('financing_type', e.target.value)}>
              {FINANCING_TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>
          <label className="ax-field">
            <span>Timeline</span>
            <input className="ax-input" placeholder="within 2 months" value={form.timeline} onChange={(e) => set('timeline', e.target.value)} />
          </label>
          <label className="ax-field">
            <span>Timeline (days)</span>
            <input className="ax-input" type="number" min="1" max="3650" value={form.timeline_days} onChange={(e) => set('timeline_days', e.target.value)} />
          </label>
          <label className="ax-field">
            <span>Preferred viewing time</span>
            <input className="ax-input" placeholder="Weekend mornings / weekdays after 5pm" value={form.preferred_viewing_time} onChange={(e) => set('preferred_viewing_time', e.target.value)} />
          </label>
          <label className="ax-field">
            <span>Next action</span>
            <input className="ax-input" placeholder="Send 3-bed shortlist on WhatsApp" value={form.next_action} onChange={(e) => set('next_action', e.target.value)} />
          </label>
          <label className="ax-field">
            <span>Initial assignment</span>
            <select className="ax-input" value={form.assignment_mode} onChange={(e) => set('assignment_mode', e.target.value)}>
              <option value="pool">Default (assign to me or shared pool)</option>
              <option value="round_robin">Round-robin across active sales agents</option>
              <option value="manual">Assign to specific sales agent</option>
            </select>
          </label>
          {form.assignment_mode === 'manual' && (
            <label className="ax-field">
              <span>Select sales agent</span>
              <select className="ax-input" value={form.assigned_agent_id} onChange={(e) => set('assigned_agent_id', e.target.value)}>
                <option value="">— choose agent —</option>
                {salesAgents.map((a) => (
                  <option key={a.id} value={String(a.id)}>
                    {a.full_name} ({a.role}) · {a.active_lead_count ?? 0} active
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="ax-field wide">
            <span>Amenities (comma-separated)</span>
            <input className="ax-input" placeholder="pool, gym, parking" value={form.amenities} onChange={(e) => set('amenities', e.target.value)} />
          </label>
          <label className="ax-field wide">
            <span>Preferences (comma-separated)</span>
            <input className="ax-input" placeholder="sea view, pet friendly" value={form.preferences} onChange={(e) => set('preferences', e.target.value)} />
          </label>
          <label className="ax-field wide">
            <span>Original enquiry</span>
            <textarea
              className="ax-textarea"
              rows={3}
              value={form.original_enquiry}
              onChange={(e) => set('original_enquiry', e.target.value)}
            />
          </label>
          <label className="ax-field wide">
            <span>Internal notes</span>
            <textarea
              className="ax-textarea"
              rows={2}
              placeholder="Where did this enquiry come from? Who called?"
              value={form.notes}
              onChange={(e) => set('notes', e.target.value)}
            />
          </label>
        </div>

        <label className="ax-field" style={{ marginTop: 14 }}>
          <span>Explicit confirmation (required)</span>
          <div className="ax-check" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <input
              id="p5-confirm"
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            <label htmlFor="p5-confirm">
              I have reviewed and edited the details above — save them as a new lead.
            </label>
          </div>
        </label>

        <div style={{ marginTop: 12, display: 'flex', gap: 10 }}>
          <button className="btn" disabled={!confirmed || saving} onClick={() => submit(false)}>
            {saving ? 'Saving…' : 'Confirm & create lead'}
          </button>
          <button className="btn btn-ghost" onClick={() => navigate('/agent/leads')}>
            Cancel
          </button>
        </div>
      </section>
    </div>
  )
}
