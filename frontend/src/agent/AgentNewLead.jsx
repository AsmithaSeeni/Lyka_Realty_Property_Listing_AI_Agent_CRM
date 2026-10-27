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

const EMPTY_FORM = {
  name: '', phone: '', email: '', intent: 'unknown',
  property_type: '', location: '', bedrooms: '', bathrooms: '',
  budget_min: '', budget_max: '', budget_currency: '', budget_period: '',
  amenities: '', preferences: '', timeline: '', timeline_days: '',
  original_enquiry: '', notes: '',
}

const num = (v) => (v === '' || v == null ? null : Number(v))

/**
 * /agent/leads/new — explicit human-in-the-loop lead creation (Phase 5).

 * Workflow: (1) optionally paste the customer enquiry and let OpenAI
 * structure it — REVIEW ONLY, nothing is saved; (2) inspect & edit every
 * field (missing data stays empty — never invented); (3) tick the explicit
 * confirmation checkbox; (4) save. The server re-validates everything,
 * recomputes score/priority deterministically, and refuses silent
 * duplicates: a possible match returns 409 with an "open it or create a
 * separate lead" decision — it never overwrites the existing lead.
 */
export default function AgentNewLead() {
  const navigate = useNavigate()
  const [extract, setExtract] = React.useState('')
  const [extracting, setExtracting] = React.useState(false)
  const [extractNote, setExtractNote] = React.useState(null) // {kind:'ok'|'warn', text}
  const [extraction, setExtraction] = React.useState(null)   // metadata (missing/questions/provenance)
  const [form, setForm] = React.useState(EMPTY_FORM)
  const [confirmed, setConfirmed] = React.useState(false)
  const [saving, setSaving] = React.useState(false)
  const [error, setError] = React.useState('')
  const [duplicate, setDuplicate] = React.useState(null)     // structured 409 payload

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
      // only overwrite a form field when extraction actually produced a value
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
      // safe structured error (e.g. 503 when no OpenAI key is configured)
      setExtractNote({ kind: 'warn', text: `Extraction unavailable: ${e.message}` })
    } finally {
      setExtracting(false)
    }
  }

  const submit = async (override = false) => {
    if (!confirmed && !override) return
    setSaving(true)
    setError('')
    try {
      const list = (v) => v.split(',').map((s) => s.trim()).filter(Boolean)
      const body = {
        name: form.name.trim() || null,
        phone: form.phone.trim() || null,
        email: form.email.trim() || null,
        intent: form.intent,
        property_type: form.property_type.trim() || null,
        location: form.location.trim() || null,
        bedrooms: num(form.bedrooms),
        bathrooms: num(form.bathrooms),
        budget_min: num(form.budget_min),
        budget_max: num(form.budget_max),
        budget_currency: form.budget_currency.trim() || null,
        budget_period: form.budget_period || null,
        amenities: list(form.amenities),
        preferences: list(form.preferences),
        timeline: form.timeline.trim() || null,
        timeline_days: num(form.timeline_days),
        original_enquiry: form.original_enquiry,
        provenance: extraction?.provenance || {},
        notes: form.notes,
        confirm: true, // this page only submits through the explicit confirm step
        duplicate_override: override,
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
        setDuplicate(e.detail) // surfaced for an explicit decision, never auto-merged
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
          <h3>2 · Review, edit & confirm</h3>
          <span className="ax-count">score & priority are computed by the server</span>
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
            <span>Name</span>
            <input className="ax-input" value={form.name} onChange={(e) => set('name', e.target.value)} />
          </label>
          <label className="ax-field">
            <span>Phone</span>
            <input className="ax-input" placeholder="+9715…" value={form.phone} onChange={(e) => set('phone', e.target.value)} />
          </label>
          <label className="ax-field">
            <span>Email</span>
            <input className="ax-input" value={form.email} onChange={(e) => set('email', e.target.value)} />
          </label>
          <label className="ax-field">
            <span>Intent</span>
            <select className="ax-input" value={form.intent} onChange={(e) => set('intent', e.target.value)}>
              {INTENTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>
          <label className="ax-field">
            <span>Location</span>
            <input className="ax-input" value={form.location} onChange={(e) => set('location', e.target.value)} />
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
            <span>Timeline</span>
            <input className="ax-input" placeholder="within 2 months" value={form.timeline} onChange={(e) => set('timeline', e.target.value)} />
          </label>
          <label className="ax-field">
            <span>Timeline (days)</span>
            <input className="ax-input" type="number" min="1" max="3650" value={form.timeline_days} onChange={(e) => set('timeline_days', e.target.value)} />
          </label>
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
