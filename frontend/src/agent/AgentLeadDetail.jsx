import React from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import api from '../api.js'
import { STATUSES, statusLabel, priorityLabel, fmtDate } from './AgentLeads.jsx'

const PROFILE_FIELDS = [
  ['name', 'Customer name'],
  ['phone', 'Phone'],
  ['email', 'Email'],
  ['buy_rent', 'Buy / rent'],
  ['location', 'Preferred location'],
  ['property_type', 'Property type'],
  ['budget', 'Budget'],
  ['investment_purpose', 'Investment purpose'],
  ['timeline', 'Timeline'],
  ['requirements', 'Requirements'],
  ['source', 'Source'],
]

const FU_TYPES = [
  ['call', 'Call'], ['email', 'Email'], ['whatsapp', 'WhatsApp'],
  ['viewing', 'Viewing'], ['general', 'General'],
]

const BUCKET_LABEL = { overdue: 'Overdue', due_today: 'Due today', upcoming: 'Upcoming' }

const INTENTS = [['buy', 'Buy'], ['rent', 'Rent'], ['lease', 'Lease'], ['unknown', 'Unknown']]
const PERIODS = [
  ['', '— none —'], ['monthly', 'Per month'], ['yearly', 'Per year'],
  ['one_time', 'One time'],
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
  return (
    <div className={`ax-msg ${m.role}`}>
      <div className="ax-msg__who">
        <b>{m.role === 'user' ? 'Customer' : 'LykAI'}</b>
        <span>
          {time}
          {m.message_type === 'voice' ? ' · 🎙 voice' : ' · 💬 text'}
          {m.detected_language && m.detected_language !== 'en' ? ` · ${m.detected_language}` : ''}
        </span>
      </div>
      <div className="ax-msg__bubble">{m.content}</div>
    </div>
  )
}

/** lead row → editable form values (strings for inputs) */
function formFromLead(l) {
  const s = (v) => (v == null ? '' : String(v))
  return {
    name: l.name || '', phone: l.phone || '', email: l.email || '',
    intent: l.buy_rent || 'unknown',
    location: l.location || '', property_type: l.property_type || '',
    bedrooms: s(l.bedrooms), bathrooms: s(l.bathrooms),
    budget_min: s(l.budget_min), budget_max: s(l.budget_max),
    budget_currency: l.budget_currency || '', budget_period: l.budget_period || '',
    amenities: (l.amenities || []).join(', '),
    preferences: (l.preferences || []).join(', '),
    timeline: l.timeline || '', timeline_days: s(l.timeline_days),
  }
}

/**
 * /agent/leads/:id — full CRM record for one lead (Phase 5):
 *  - left: customer profile, status & notes (unchanged) + linked account
 *  - right: deterministic score & breakdown, structured requirement editing
 *    (server re-scores on requirement changes), follow-up scheduling,
 *    property matching against approved database listings, the complete
 *    AI↔customer conversation, and every saved recommendation.
 */
export default function AgentLeadDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [data, setData] = React.useState(null)
  const [error, setError] = React.useState(null)
  const [notes, setNotes] = React.useState('')
  const [saving, setSaving] = React.useState(false)
  const [status, setStatus] = React.useState('new')

  // Phase 5: structured edit form (diff-based PATCH), follow-ups, matching
  const [edit, setEdit] = React.useState(null)
  const [editOpen, setEditOpen] = React.useState(false)
  const [savingEdit, setSavingEdit] = React.useState(false)
  const [editError, setEditError] = React.useState('')
  const [fuForm, setFuForm] = React.useState({ type: 'call', due: '', notes: '' })
  const [fuBusy, setFuBusy] = React.useState(false)
  const [matching, setMatching] = React.useState(false)
  const [matchResult, setMatchResult] = React.useState(null)
  const [matchError, setMatchError] = React.useState('')

  const load = React.useCallback(() => {
    api
      .agentLead(id)
      .then((d) => {
        setData(d)
        setNotes(d.lead.notes || '')
        setStatus(d.lead.status)
        setEdit(formFromLead(d.lead))
      })
      .catch((e) => setError(e.message))
  }, [id])

  React.useEffect(load, [load])

  const saveNotes = async () => {
    setSaving(true)
    try {
      await api.updateAgentLead(id, { notes })
      load()
    } catch (e) {
      alert('Could not save notes: ' + e.message)
    } finally {
      setSaving(false)
    }
  }

  const changeStatus = async (next) => {
    const prev = status
    setStatus(next)
    try {
      await api.updateAgentLead(id, { status: next })
      load()
    } catch (e) {
      setStatus(prev)
      alert('Could not update status: ' + e.message)
    }
  }

  // ---- diff-based PATCH: only changed fields are sent (never client scores) ----
  const saveEdit = async () => {
    if (!edit || !data) return
    const l = data.lead
    const s = (v) => (v || '').trim()
    const n = (v) => (v === '' ? null : Number(v))
    const L = (v) => v.split(',').map((x) => x.trim()).filter(Boolean)
    const sameList = (a, b) => JSON.stringify(a) === JSON.stringify(b || [])
    const p = {}
    if (s(edit.name) !== (l.name || '')) p.name = s(edit.name) || null
    if (s(edit.phone) !== (l.phone || '')) p.phone = s(edit.phone) || null
    if (s(edit.email) !== (l.email || '')) p.email = s(edit.email) || null
    if (edit.intent !== (l.buy_rent || 'unknown')) p.buy_rent = edit.intent
    if (s(edit.location) !== (l.location || '')) p.location = s(edit.location) || null
    if (s(edit.property_type) !== (l.property_type || '')) p.property_type = s(edit.property_type) || null
    if (n(edit.bedrooms) !== (l.bedrooms ?? null)) p.bedrooms = n(edit.bedrooms)
    if (n(edit.bathrooms) !== (l.bathrooms ?? null)) p.bathrooms = n(edit.bathrooms)
    if (n(edit.budget_min) !== (l.budget_min ?? null)) p.budget_min = n(edit.budget_min)
    if (n(edit.budget_max) !== (l.budget_max ?? null)) p.budget_max = n(edit.budget_max)
    const cur = s(edit.budget_currency).toUpperCase()
    if (cur !== (l.budget_currency || '')) p.budget_currency = cur || null
    if (edit.budget_period !== (l.budget_period || '')) p.budget_period = edit.budget_period || null
    if (!sameList(L(edit.amenities), l.amenities)) p.amenities = L(edit.amenities)
    if (!sameList(L(edit.preferences), l.preferences)) p.preferences = L(edit.preferences)
    if (s(edit.timeline) !== (l.timeline || '')) p.timeline = s(edit.timeline) || null
    if (n(edit.timeline_days) !== (l.timeline_days ?? null)) p.timeline_days = n(edit.timeline_days)

    if (Object.keys(p).length === 0) {
      setEditOpen(false)
      return
    }
    setSavingEdit(true)
    setEditError('')
    try {
      await api.updateAgentLead(id, p) // server re-validates & re-scores
      load()
      setEditOpen(false)
    } catch (e) {
      setEditError(e.message)
    } finally {
      setSavingEdit(false)
    }
  }

  // ---- follow-ups (existing Phase 2 table, no schedulers: labels only) ----
  const addFollowUp = async () => {
    if (!fuForm.due) return
    setFuBusy(true)
    try {
      await api.createAgentFollowUp(id, {
        type: fuForm.type,
        // browser local wall-time → explicit UTC instant
        due_at: new Date(fuForm.due).toISOString(),
        notes: fuForm.notes,
      })
      setFuForm({ type: 'call', due: '', notes: '' })
      load()
    } catch (e) {
      alert('Could not schedule follow-up: ' + e.message)
    } finally {
      setFuBusy(false)
    }
  }

  const toggleFollowUp = async (fu) => {
    try {
      await api.updateAgentFollowUp(fu.id, { is_completed: !fu.is_completed })
      load()
    } catch (e) {
      alert('Could not update follow-up: ' + e.message)
    }
  }

  // ---- property matching (approved database listings, deterministic) ----
  const runMatch = async () => {
    setMatching(true)
    setMatchError('')
    try {
      const out = await api.runLeadRecommendations(id, { limit: 3, save: true })
      setMatchResult(out)
      load() // refresh saved history + refreshed score
    } catch (e) {
      setMatchError(e.message)
    } finally {
      setMatching(false)
    }
  }

  if (error) return <div className="ax-empty">⚠ {error}</div>
  if (!data) return <div className="ax-empty"><div className="ax-spin" /> Loading lead…</div>

  const lead = data.lead
  const convs = data.conversations || []
  const recs = data.property_recommendations || []
  const fus = lead.follow_ups || []
  const msgCount = convs.reduce((n, c) => n + c.messages.length, 0)
  const breakdown = lead.score_breakdown || []

  return (
    <div>
      <button className="ax-back" onClick={() => navigate('/agent/leads')}>← Back to leads</button>

      <div className="ax-lead-layout">
        {/* ---------------- LEFT: profile ---------------- */}
        <aside className="ax-profile">
          <div className="ax-profile__head">
            <div className="ax-profile__avatar">{(lead.name || '?').slice(0, 1).toUpperCase()}</div>
            <div>
              <h2>{lead.name}</h2>
              <span className="ax-id">Lead #{lead.id}</span>
            </div>
          </div>

          <label className="ax-field">
            <span>Lead status</span>
            <select className={`ax-status-select big ${status}`} value={status} onChange={(e) => changeStatus(e.target.value)}>
              {STATUSES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>

          <dl className="ax-dl">
            {PROFILE_FIELDS.map(([k, label]) => (
              <React.Fragment key={k}>
                <dt>{label}</dt>
                <dd className={lead[k] === 'Not provided' ? 'np' : ''}>{lead[k]}</dd>
              </React.Fragment>
            ))}
            <dt>Assigned to</dt>
            <dd>{lead.assigned_agent_name || 'Unassigned (shared pool)'}</dd>
            <dt>Customer account</dt>
            <dd className={data.customer_account ? '' : 'np'}>
              {data.customer_account
                ? `${data.customer_account.name || '—'} · ${data.customer_account.email || 'no email'}`
                : 'Not linked (guest chat)'}
            </dd>
            <dt>Created</dt>
            <dd>{fmtDate(lead.created_at)}</dd>
            <dt>Last interaction</dt>
            <dd>{fmtDate(lead.last_interaction_at)}</dd>
          </dl>

          <div className="ax-field">
            <span>Internal notes</span>
            <textarea
              className="ax-textarea"
              value={notes}
              placeholder="Add call notes, objections, next steps…"
              onChange={(e) => setNotes(e.target.value)}
            />
            <button className="btn btn-sm ax-save" onClick={saveNotes} disabled={saving}>
              {saving ? 'Saving…' : 'Save notes'}
            </button>
          </div>
        </aside>

        {/* ---------------- RIGHT: score, edit, follow-ups, chat, recs -------- */}
        <div className="ax-detail-main">
          {/* ---- Deterministic score (Phase 4, refreshed by the server) ---- */}
          <section className="ax-panel">
            <div className="ax-panel__head">
              <h3>Lead score</h3>
              {lead.lead_score != null ? (
                <span className={`ax-prio ${lead.priority}`}>{priorityLabel(lead.priority)}</span>
              ) : (
                <span className="ax-count">not scored yet</span>
              )}
            </div>

            {lead.lead_score != null && (
              <>
                <div className="ax-score">
                  <b>{Math.round(lead.lead_score)}</b>
                  <div className="ax-score__bar">
                    <i style={{ width: `${Math.max(0, Math.min(100, lead.lead_score))}%` }} />
                  </div>
                  <span className="ax-muted">/ 100 · high ≥ 70 · medium 40–69 · low ≤ 39</span>
                </div>

                {breakdown.length > 0 && (
                  <div className="ax-break">
                    {breakdown.map((c) => (
                      <div className="ax-break__row" key={c.criterion} title={c.reason || ''}>
                        <span>{c.criterion}</span>
                        <div className="ax-break__meter">
                          <i style={{ width: `${c.weight ? Math.round((c.points / c.weight) * 100) : 0}%` }} />
                        </div>
                        <em>{Math.round(c.points)}/{c.weight}</em>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}

            {lead.missing_fields?.length > 0 && (
              <>
                <b style={{ fontSize: 13, display: 'block', marginTop: 12 }}>Missing information</b>
                <div className="ax-qchips">
                  {lead.missing_fields.map((m) => <span key={m}>{m}</span>)}
                </div>
              </>
            )}
            {lead.clarification_questions?.length > 0 && (
              <>
                <b style={{ fontSize: 13, display: 'block', marginTop: 12 }}>Suggested questions</b>
                <div className="ax-qchips">
                  {lead.clarification_questions.map((q, i) => <span key={i}>“{q}”</span>)}
                </div>
              </>
            )}
            <p className="ax-muted" style={{ fontSize: 12, marginTop: 10, marginBottom: 0 }}>
              Server-computed by the deterministic rubric — it refreshes automatically whenever
              requirement fields change. Client-supplied scores are never accepted.
            </p>
          </section>

          {/* ---- Structured requirement editing ---- */}
          <section className="ax-panel">
            <div className="ax-panel__head">
              <h3>Requirements</h3>
              <button className="ax-link" onClick={() => setEditOpen((o) => !o)}>
                {editOpen ? 'Close editor ✕' : 'Edit ✎'}
              </button>
            </div>

            {editError && <div className="ax-warn">{editError}</div>}

            {!editOpen && (
              <dl className="ax-dl">
                <dt>Intent</dt><dd>{lead.buy_rent}</dd>
                <dt>Location</dt><dd className={lead.location ? '' : 'np'}>{lead.location}</dd>
                <dt>Type</dt><dd className={lead.property_type ? '' : 'np'}>{lead.property_type}</dd>
                <dt>Bedrooms</dt><dd>{lead.bedrooms ?? '—'}</dd>
                <dt>Bathrooms</dt><dd>{lead.bathrooms ?? '—'}</dd>
                <dt>Budget</dt><dd className={lead.budget_min == null && lead.budget_max == null ? 'np' : ''}>
                  {lead.budget_min != null || lead.budget_max != null
                    ? `${lead.budget_min ?? '…'} – ${lead.budget_max ?? '…'} ${lead.budget_currency || ''} ${lead.budget_period ? `(${lead.budget_period})` : ''}`.trim()
                    : lead.budget}
                </dd>
                <dt>Amenities</dt><dd className={lead.amenities?.length ? '' : 'np'}>{lead.amenities?.length ? lead.amenities.join(', ') : '—'}</dd>
                <dt>Preferences</dt><dd className={lead.preferences?.length ? '' : 'np'}>{lead.preferences?.length ? lead.preferences.join(', ') : '—'}</dd>
                <dt>Timeline</dt><dd>{lead.timeline || '—'}{lead.timeline_days ? ` · ${lead.timeline_days} days` : ''}</dd>
              </dl>
            )}

            {editOpen && edit && (
              <div className="ax-form">
                <label className="ax-field"><span>Name</span>
                  <input className="ax-input" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></label>
                <label className="ax-field"><span>Phone</span>
                  <input className="ax-input" value={edit.phone} onChange={(e) => setEdit({ ...edit, phone: e.target.value })} /></label>
                <label className="ax-field"><span>Email</span>
                  <input className="ax-input" value={edit.email} onChange={(e) => setEdit({ ...edit, email: e.target.value })} /></label>
                <label className="ax-field"><span>Intent</span>
                  <select className="ax-input" value={edit.intent} onChange={(e) => setEdit({ ...edit, intent: e.target.value })}>
                    {INTENTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                  </select></label>
                <label className="ax-field"><span>Location</span>
                  <input className="ax-input" value={edit.location} onChange={(e) => setEdit({ ...edit, location: e.target.value })} /></label>
                <label className="ax-field"><span>Property type</span>
                  <input className="ax-input" value={edit.property_type} onChange={(e) => setEdit({ ...edit, property_type: e.target.value })} /></label>
                <label className="ax-field"><span>Bedrooms</span>
                  <input className="ax-input" type="number" min="0" max="30" value={edit.bedrooms} onChange={(e) => setEdit({ ...edit, bedrooms: e.target.value })} /></label>
                <label className="ax-field"><span>Bathrooms</span>
                  <input className="ax-input" type="number" min="0" max="30" value={edit.bathrooms} onChange={(e) => setEdit({ ...edit, bathrooms: e.target.value })} /></label>
                <label className="ax-field"><span>Budget min</span>
                  <input className="ax-input" type="number" min="0" value={edit.budget_min} onChange={(e) => setEdit({ ...edit, budget_min: e.target.value })} /></label>
                <label className="ax-field"><span>Budget max</span>
                  <input className="ax-input" type="number" min="0" value={edit.budget_max} onChange={(e) => setEdit({ ...edit, budget_max: e.target.value })} /></label>
                <label className="ax-field"><span>Currency</span>
                  <input className="ax-input" maxLength={3} placeholder="AED" value={edit.budget_currency}
                    onChange={(e) => setEdit({ ...edit, budget_currency: e.target.value.toUpperCase() })} /></label>
                <label className="ax-field"><span>Budget period</span>
                  <select className="ax-input" value={edit.budget_period} onChange={(e) => setEdit({ ...edit, budget_period: e.target.value })}>
                    {PERIODS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                  </select></label>
                <label className="ax-field wide"><span>Amenities (comma-separated)</span>
                  <input className="ax-input" value={edit.amenities} onChange={(e) => setEdit({ ...edit, amenities: e.target.value })} /></label>
                <label className="ax-field wide"><span>Preferences (comma-separated)</span>
                  <input className="ax-input" value={edit.preferences} onChange={(e) => setEdit({ ...edit, preferences: e.target.value })} /></label>
                <label className="ax-field"><span>Timeline</span>
                  <input className="ax-input" value={edit.timeline} onChange={(e) => setEdit({ ...edit, timeline: e.target.value })} /></label>
                <label className="ax-field"><span>Timeline (days)</span>
                  <input className="ax-input" type="number" min="1" max="3650" value={edit.timeline_days} onChange={(e) => setEdit({ ...edit, timeline_days: e.target.value })} /></label>

                <div style={{ gridColumn: '1 / -1', marginTop: 10, display: 'flex', gap: 10 }}>
                  <button className="btn btn-sm" disabled={savingEdit} onClick={saveEdit}>
                    {savingEdit ? 'Saving…' : 'Save changes & re-score'}
                  </button>
                  <button className="btn btn-sm btn-ghost" onClick={() => { setEdit(formFromLead(lead)); setEditOpen(false) }}>
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </section>

          {/* ---- Follow-ups ---- */}
          <section className="ax-panel">
            <div className="ax-panel__head">
              <h3>Follow-ups</h3>
              <span className="ax-count">
                {fus.length === 0 ? 'none scheduled' : `${fus.filter((f) => !f.is_completed).length} pending`}
              </span>
            </div>

            <div className="ax-fu">
              {fus.length === 0 && (
                <div className="ax-empty sm">No follow-ups scheduled for this lead.</div>
              )}
              {fus.map((f) => (
                <div className={`ax-fu__row${f.is_completed ? ' done' : ''}`} key={f.id}>
                  <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <input
                      type="checkbox"
                      checked={!!f.is_completed}
                      onChange={() => toggleFollowUp(f)}
                    />
                    <span className="ax-tag">{FU_TYPES.find(([k]) => k === f.type)?.[1] || f.type}</span>
                  </label>
                  <span className="ax-fu__due">{fmtDate(f.due_at)}</span>
                  {f.bucket && <span className={`ax-bucket ${f.bucket}`}>{BUCKET_LABEL[f.bucket] || f.bucket}</span>}
                  <span className="ax-muted">{f.notes || '—'}</span>
                  {f.is_completed && f.completed_at && (
                    <span className="ax-muted">✓ done {fmtDate(f.completed_at)}</span>
                  )}
                </div>
              ))}
            </div>

            <div className="ax-fu-add">
              <label className="ax-field"><span>Type</span>
                <select className="ax-input" value={fuForm.type} onChange={(e) => setFuForm({ ...fuForm, type: e.target.value })}>
                  {FU_TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select></label>
              <label className="ax-field"><span>Due (your local time)</span>
                <input className="ax-input" type="datetime-local" value={fuForm.due}
                  onChange={(e) => setFuForm({ ...fuForm, due: e.target.value })} /></label>
              <label className="ax-field" style={{ flex: 1, minWidth: 200 }}><span>Notes</span>
                <input className="ax-input" placeholder="Call about villa shortlist…"
                  value={fuForm.notes} onChange={(e) => setFuForm({ ...fuForm, notes: e.target.value })} /></label>
              <button className="btn btn-sm" disabled={fuBusy || !fuForm.due} onClick={addFollowUp}>
                {fuBusy ? 'Scheduling…' : 'Schedule'}
              </button>
            </div>
          </section>

          {/* Conversation threads */}
          <section className="ax-panel">
            <div className="ax-panel__head">
              <h3>LykAI ↔ customer conversation</h3>
              <span className="ax-count">{convs.length} thread{convs.length === 1 ? '' : 's'} · {msgCount} messages</span>
            </div>

            {convs.length === 0 && (
              <div className="ax-empty sm">No conversations linked to this lead yet.</div>
            )}

            {convs.map((c) => (
              <div className="ax-thread" key={c.id}>
                <div className="ax-thread__meta">
                  Conversation #{c.id} · started {fmtDate(c.created_at)}
                </div>
                {c.messages.length === 0 && <div className="ax-empty sm">Empty thread.</div>}
                {c.messages.map((m) => <MsgBubble key={m.id} m={m} />)}
              </div>
            ))}
          </section>

          {/* ---- Property matching against approved database listings ---- */}
          <section className="ax-panel">
            <div className="ax-panel__head">
              <h3>Property matching</h3>
              <button className="btn btn-sm" disabled={matching} onClick={runMatch}>
                {matching ? 'Matching…' : matchResult ? 'Run again' : 'Run matching'}
              </button>
            </div>
            <p className="ax-muted" style={{ fontSize: 12.5, marginTop: 0 }}>
              Deterministic match against approved &amp; available database listings (top 3).
              Already-saved matches are re-shown but never duplicated in the history below.
            </p>

            {matchError && <div className="ax-warn">{matchError}</div>}

            {matchResult && (
              <>
                {matchResult.explanation && (
                  <p style={{ fontSize: 13, marginBottom: 10 }}>{matchResult.explanation}</p>
                )}
                {matchResult.saved_count > 0 && (
                  <div className="ax-ok">
                    {matchResult.saved_count} new recommendation{matchResult.saved_count === 1 ? '' : 's'} saved
                    to this lead's history.
                  </div>
                )}
                {matchResult.results.length === 0 && (
                  <div className="ax-empty sm">
                    No database listing currently matches the hard requirements
                    (approved · available · purpose · type · bedrooms).
                  </div>
                )}
                <div className="ax-match">
                  {(matchResult.results || []).map((m) => (
                    <div className="ax-match__row" key={m.property_id}>
                      <div className="ax-match__head">
                        <span>{propEmoji(m.property_type)}</span>
                        <b>{m.title || `${m.property_type || 'Property'} #${m.property_id}`}</b>
                        <span className="ax-cell-sub">
                          📍 {m.location || '—'} · 🛏 {m.bedrooms ?? '—'} · 🛁 {m.bathrooms ?? '—'} ·
                          {' '}{m.currency || 'AED'} {m.price?.toLocaleString?.() ?? m.price}
                        </span>
                        {m.previously_saved && <span className="ax-tag">already saved</span>}
                        <span className="ax-match__score">{Math.round(m.match_score)} / 100</span>
                      </div>
                      {m.match_reasons?.length > 0 && (
                        <ul>
                          {m.match_reasons.map((r, i) => <li key={i}>{r}</li>)}
                        </ul>
                      )}
                      {m.match_mismatches?.length > 0 && (
                        <ul className="neg">
                          {m.match_mismatches.map((r, i) => (
                            <li key={i} className={/data gap/i.test(r) ? 'gap-text' : ''}>{r}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}
          </section>

          {/* Property recommendations (saved history + chat dataset rows) */}
          <section className="ax-panel">
            <div className="ax-panel__head">
              <h3>Recommended properties</h3>
              <span className="ax-count">
                {recs.filter((r) => r.match_score != null).length} saved · {recs.length} total
              </span>
            </div>

            {recs.length === 0 && (
              <div className="ax-empty sm">
                No recommendations saved yet — run property matching above, or ask LykAI in chat.
              </div>
            )}

            <div className="ax-props">
              {recs.map((r, i) => (
                <div className="ax-prop" key={`${r.property_record_id || r.property_id}-${i}`}>
                  <div className="ax-prop__top">
                    <span className="ax-prop__emoji">{propEmoji(r.property_type)}</span>
                    <span className="ax-prop__price">AED {r.price}</span>
                    {r.match_score != null && (
                      <span className="ax-tag">saved · {Math.round(r.match_score)}</span>
                    )}
                  </div>
                  <b className="ax-prop__type">
                    {r.property_type || 'Property'}{' '}
                    <i className="ax-id">#{r.property_record_id || r.property_id}</i>
                  </b>
                  <div className="ax-prop__loc">📍 {r.location || 'UAE'}</div>
                  <div className="ax-prop__specs">
                    <span>🛏 {r.bedrooms ?? '—'}</span>
                    <span>🛁 {r.bathrooms ?? '—'}</span>
                    <span>📐 {r.area || '—'}</span>
                  </div>
                  {r.highlights && <p className="ax-prop__hl">{r.highlights}</p>}
                  <div className="ax-prop__foot">
                    <span>Rec. {fmtDate(r.created_at)}</span>
                    {/* Link by id space: a saved match carries the DB record
                        id (/properties/:id); a chat-era dataset row only has
                        the dataset id (/property/:id). Mixing them opened a
                        same-numbered listing from the wrong space. */}
                    {r.property_record_id != null ? (
                      <Link className="ax-link" to={`/properties/${r.property_record_id}`} target="_blank">
                        Open listing ↗
                      </Link>
                    ) : r.property_id != null ? (
                      <Link className="ax-link" to={`/property/${r.property_id}`} target="_blank">
                        Open dataset listing ↗
                      </Link>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
