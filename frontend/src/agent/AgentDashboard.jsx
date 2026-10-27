import React from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api.js'

const STAT_CARDS = [
  { key: 'total', label: 'Total leads', tone: '' },
  { key: 'new', label: 'New', tone: 'n' },
  { key: 'contacted', label: 'Contacted', tone: 'c' },
  { key: 'qualified', label: 'Qualified', tone: 'q' },
  { key: 'viewing', label: 'Viewing', tone: 'v' },
  { key: 'negotiation', label: 'Negotiation', tone: 'g' },
  { key: 'closed', label: 'Closed', tone: 'w' },
  { key: 'lost', label: 'Lost', tone: 'l' },
]

const STATUS_LABEL = {
  new: 'New', contacted: 'Contacted', qualified: 'Qualified',
  viewing: 'Viewing', negotiation: 'Negotiation',
  closed_won: 'Closed won', closed_lost: 'Closed lost',
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

export default function AgentDashboard() {
  const navigate = useNavigate()
  const [data, setData] = React.useState(null)
  const [error, setError] = React.useState(null)

  React.useEffect(() => {
    api
      .agentDashboard()
      .then(setData)
      .catch((e) => setError(e.message))
  }, [])

  if (error) return <div className="ax-empty">⚠ {error}</div>
  if (!data) return <div className="ax-empty"><div className="ax-spin" /> Loading dashboard…</div>

  const counts = data.counts || {}
  const priority = data.priority || {}      // high / medium / low / unscored
  const followUps = data.follow_ups || {}   // overdue / due_today / upcoming

  return (
    <div>
      {/* Status cards */}
      <div className="ax-stats">
        {STAT_CARDS.map((s) => (
          <div className={`ax-stat ${s.tone}`} key={s.key}>
            <b>{counts[s.key] ?? 0}</b>
            <span>{s.label}</span>
          </div>
        ))}
      </div>

      {/* Priority + follow-up workload (Phase 5 — real DB counts) */}
      <div className="ax-stats">
        <div className={`ax-stat ${priority.high ? 'l' : ''}`}>
          <b>{priority.high ?? 0}</b><span>High priority</span>
        </div>
        <div className={`ax-stat ${priority.medium ? 'q' : ''}`}>
          <b>{priority.medium ?? 0}</b><span>Medium priority</span>
        </div>
        <div className={`ax-stat ${priority.low ? 'n' : ''}`}>
          <b>{priority.low ?? 0}</b><span>Low priority</span>
        </div>
        <div className="ax-stat">
          <b>{priority.unscored ?? 0}</b><span>Unscored</span>
        </div>
        <div className={`ax-stat ${followUps.overdue ? 'l' : ''}`}>
          <b>{followUps.overdue ?? 0}</b><span>Follow-ups overdue</span>
        </div>
        <div className={`ax-stat ${followUps.due_today ? 'q' : ''}`}>
          <b>{followUps.due_today ?? 0}</b><span>Due today</span>
        </div>
        <div className={`ax-stat ${followUps.upcoming ? 'v' : ''}`}>
          <b>{followUps.upcoming ?? 0}</b><span>Upcoming</span>
        </div>
      </div>

      <div className="ax-grid2">
        {/* Recent leads */}
        <section className="ax-panel">
          <div className="ax-panel__head">
            <h3>Recent leads</h3>
            <button className="ax-link" onClick={() => navigate('/agent/leads')}>View all →</button>
          </div>
          {data.recent_leads.length === 0 && (
            <div className="ax-empty sm">No leads yet — they appear here as the AI qualifies customers.</div>
          )}
          {data.recent_leads.map((l) => (
            <div
              className="ax-row"
              key={l.id}
              role="button"
              tabIndex={0}
              onClick={() => navigate(`/agent/leads/${l.id}`)}
              onKeyDown={(e) => e.key === 'Enter' && navigate(`/agent/leads/${l.id}`)}
            >
              <div className="ax-row__id">#{l.id}</div>
              <div className="ax-row__main">
                <b>{l.name}</b>
                <span>{l.location} · {l.budget} · {l.bedrooms != null ? `${l.bedrooms} bed` : 'bed n/a'}</span>
              </div>
              <span className={`ax-badge ${l.status}`}>{STATUS_LABEL[l.status] || l.status}</span>
              <div className="ax-row__time">{when(l.last_interaction_at)}</div>
            </div>
          ))}
        </section>

        {/* Recent conversations */}
        <section className="ax-panel">
          <div className="ax-panel__head">
            <h3>Recent conversations</h3>
            <button className="ax-link" onClick={() => navigate('/agent/conversations')}>View all →</button>
          </div>
          {data.recent_conversations.length === 0 && (
            <div className="ax-empty sm">No conversations yet.</div>
          )}
          {data.recent_conversations.map((c) => (
            <div
              className="ax-row"
              key={c.id}
              role="button"
              tabIndex={0}
              onClick={() => navigate('/agent/conversations')}
              onKeyDown={(e) => e.key === 'Enter' && navigate('/agent/conversations')}
            >
              <div className="ax-row__id">#{c.id}</div>
              <div className="ax-row__main">
                <b>{c.customer_name || 'Anonymous visitor'}</b>
                <span className="ax-ellipsis">{c.last_message_preview || 'No messages yet'}</span>
              </div>
              {c.lead_status && <span className={`ax-badge ${c.lead_status}`}>{STATUS_LABEL[c.lead_status] || c.lead_status}</span>}
              <div className="ax-row__time">{when(c.updated_at)}</div>
            </div>
          ))}
        </section>
      </div>
    </div>
  )
}
