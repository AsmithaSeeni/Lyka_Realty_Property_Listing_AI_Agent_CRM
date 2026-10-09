import React from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import api from '../api.js'
import { STATUSES, statusLabel, fmtDate } from './AgentLeads.jsx'

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

/**
 * /agent/leads/:id — left: customer profile, status & notes.
 *                    right: complete AI↔customer conversation + every
 *                           property the AI recommended (from the dataset).
 */
export default function AgentLeadDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [data, setData] = React.useState(null)
  const [error, setError] = React.useState(null)
  const [notes, setNotes] = React.useState('')
  const [saving, setSaving] = React.useState(false)
  const [status, setStatus] = React.useState('new')

  const load = React.useCallback(() => {
    api
      .agentLead(id)
      .then((d) => {
        setData(d)
        setNotes(d.lead.notes || '')
        setStatus(d.lead.status)
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

  if (error) return <div className="ax-empty">⚠ {error}</div>
  if (!data) return <div className="ax-empty"><div className="ax-spin" /> Loading lead…</div>

  const lead = data.lead
  const convs = data.conversations || []
  const recs = data.property_recommendations || []
  const msgCount = convs.reduce((n, c) => n + c.messages.length, 0)

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

        {/* ---------------- RIGHT: conversation + recs ---------------- */}
        <div className="ax-detail-main">
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

          {/* Property recommendations */}
          <section className="ax-panel">
            <div className="ax-panel__head">
              <h3>Recommended properties</h3>
              <span className="ax-count">{recs.length} from the live dataset</span>
            </div>

            {recs.length === 0 && (
              <div className="ax-empty sm">The AI has not recommended properties in this conversation yet.</div>
            )}

            <div className="ax-props">
              {recs.map((r, i) => (
                <div className="ax-prop" key={`${r.property_id}-${i}`}>
                  <div className="ax-prop__top">
                    <span className="ax-prop__emoji">{propEmoji(r.property_type)}</span>
                    <span className="ax-prop__price">AED {r.price}</span>
                  </div>
                  <b className="ax-prop__type">{r.property_type || 'Property'} <i className="ax-id">#{r.property_id}</i></b>
                  <div className="ax-prop__loc">📍 {r.location || 'UAE'}</div>
                  <div className="ax-prop__specs">
                    <span>🛏 {r.bedrooms ?? '—'}</span>
                    <span>🛁 {r.bathrooms ?? '—'}</span>
                    <span>📐 {r.area || '—'}</span>
                  </div>
                  {r.highlights && <p className="ax-prop__hl">{r.highlights}</p>}
                  <div className="ax-prop__foot">
                    <span>Rec. {fmtDate(r.created_at)}</span>
                    {r.property_id && (
                      <Link className="ax-link" to={`/properties/${r.property_id}`} target="_blank">
                        Open listing ↗
                      </Link>
                    )}
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
