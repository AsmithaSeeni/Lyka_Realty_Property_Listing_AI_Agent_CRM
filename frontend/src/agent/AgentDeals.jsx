import React from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import api from '../api.js'
import { useAuth, hasPerm } from '../auth/AuthContext.jsx'

const DEAL_STAGES = [
  ['qualification', 'Qualification'],
  ['viewing', 'Viewing'],
  ['offer_preparation', 'Offer preparation'],
  ['negotiation', 'Negotiation'],
  ['offer_accepted', 'Offer accepted'],
  ['reservation_pending', 'Reservation pending'],
  ['reservation_confirmed', 'Reservation confirmed'],
  ['documentation_pending', 'Documentation & KYC pending'],
  ['transaction_pending_completion', 'Transaction pending completion'],
  ['completed', 'Completed (Closed Won)'],
  ['cancelled', 'Cancelled'],
  ['failed', 'Failed / Fallen through'],
]

const CHECKLIST_STATUSES = [
  ['pending', 'Pending'],
  ['uploaded', 'Uploaded'],
  ['received', 'Received'],
  ['reviewed', 'Reviewed'],
  ['verified', 'Verified ✓'],
  ['waived', 'Waived'],
]

const FINANCING_OPTIONS = [
  ['cash', 'Cash buyer'],
  ['mortgage_preapproved', 'Mortgage (pre-approved)'],
  ['mortgage_needed', 'Mortgage (needs assistance)'],
  ['payment_plan', 'Developer payment plan'],
  ['cheques', 'Rental cheques (1–12)'],
]

const PAYMENT_FREQUENCIES = [
  ['one_time', 'One-time (Purchase)'],
  ['yearly', 'Yearly (1 cheque)'],
  ['semi_annual', 'Semi-annual (2 cheques)'],
  ['quarterly', 'Quarterly (4 cheques)'],
  ['monthly', 'Monthly (12 cheques)'],
  ['installment_plan', 'Developer installment plan'],
]

function fmtAED(num) {
  if (num == null || Number.isNaN(Number(num))) return 'AED 0'
  return `AED ${Number(num).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
}

function fmtDate(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString([], {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

export default function AgentDeals() {
  const { id } = useParams()
  if (id) {
    return <DealDetailView dealId={id} />
  }
  return <DealsAndOffersIndex />
}

function DealsAndOffersIndex() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [tab, setTab] = React.useState(searchParams.get('new_offer') === '1' ? 'offers' : 'deals')
  const [deals, setDeals] = React.useState([])
  const [offers, setOffers] = React.useState([])
  const [summary, setSummary] = React.useState(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState('')

  const [stageFilter, setStageFilter] = React.useState('')
  const [offerStatusFilter, setOfferStatusFilter] = React.useState('')

  const [leads, setLeads] = React.useState([])
  const [properties, setProperties] = React.useState([])

  // Offer creation form
  const [newOfferOpen, setNewOfferOpen] = React.useState(searchParams.get('new_offer') === '1')
  const [offerForm, setOfferForm] = React.useState({
    lead_id: searchParams.get('lead_id') || '',
    property_id: searchParams.get('property_id') || '',
    offered_price: '',
    currency: 'AED',
    transaction_intent: 'purchase',
    payment_frequency: 'one_time',
    financing_type: 'cash',
    cheques_count: '',
    terms_conditions: '',
    notes: '',
    submit_immediately: true,
  })
  const [offerErr, setOfferErr] = React.useState('')
  const [offerBusy, setOfferBusy] = React.useState(false)

  // Counteroffer state
  const [activeCounterOfferId, setActiveCounterOfferId] = React.useState(null)
  const [counterForm, setCounterForm] = React.useState({
    counter_amount: '',
    party: 'seller',
    reason: '',
    notes: '',
  })

  // Deal creation form
  const [newDealOpen, setNewDealOpen] = React.useState(searchParams.get('new_deal') === '1')
  const [dealForm, setDealForm] = React.useState({
    lead_id: searchParams.get('lead_id') || '',
    property_id: searchParams.get('property_id') || '',
    offer_id: searchParams.get('offer_id') || '',
    transaction_type: 'purchase',
    initial_status: 'offer_accepted',
    agreed_amount: '',
    currency: 'AED',
    estimated_commission_pct: '2.0',
    notes: '',
  })
  const [dealErr, setDealErr] = React.useState('')
  const [dealBusy, setDealBusy] = React.useState(false)

  const loadAll = React.useCallback(() => {
    setLoading(true)
    setError('')
    Promise.all([
      api.agentDeals({ status: stageFilter || undefined, limit: 100 }),
      api.agentOffers({ status: offerStatusFilter || undefined, limit: 100 }),
      api.agentSalesOpsSummary().catch(() => null),
    ])
      .then(([dRes, oRes, sRes]) => {
        setDeals(dRes.results || [])
        setOffers(oRes.results || [])
        if (sRes) setSummary(sRes)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [stageFilter, offerStatusFilter])

  const paramPropId = searchParams.get('property_id')
  const paramLeadId = searchParams.get('lead_id')

  React.useEffect(() => {
    loadAll()
  }, [loadAll])

  React.useEffect(() => {
    api.agentLeads({ limit: 100 })
      .then(async (r) => {
        let list = r.results || r.leads || []
        if (paramLeadId && !list.some((l) => String(l.id) === String(paramLeadId))) {
          try {
            const specificLead = await api.agentLead(paramLeadId)
            if (specificLead?.lead) list = [specificLead.lead, ...list]
          } catch {}
        }
        setLeads(list)
      })
      .catch(() => {})

    api.agentProperties({ approved: true, limit: 100 })
      .then(async (r) => {
        let list = r.results || r.items || []
        if (paramPropId && !list.some((p) => String(p.id) === String(paramPropId))) {
          try {
            const specificProp = await api.agentProperty(paramPropId)
            const propObj = specificProp?.property || specificProp
            if (propObj && propObj.id) list = [propObj, ...list]
          } catch {}
        }
        setProperties(list)
      })
      .catch(() => {})
  }, [paramPropId, paramLeadId])

  React.useEffect(() => {
    if (paramPropId) {
      setOfferForm((prev) => ({ ...prev, property_id: String(paramPropId) }))
      setDealForm((prev) => ({ ...prev, property_id: String(paramPropId) }))
    }
    if (paramLeadId) {
      setOfferForm((prev) => ({ ...prev, lead_id: String(paramLeadId) }))
      setDealForm((prev) => ({ ...prev, lead_id: String(paramLeadId) }))
    }
  }, [paramPropId, paramLeadId])

  const handleCreateOffer = async (e) => {
    e.preventDefault()
    if (!offerForm.lead_id || !offerForm.property_id || !offerForm.offered_price) {
      setOfferErr('Lead, property, and offered price are required.')
      return
    }
    setOfferBusy(true)
    setOfferErr('')
    try {
      await api.createAgentOffer({
        lead_id: Number(offerForm.lead_id),
        property_id: Number(offerForm.property_id),
        offered_price: Number(offerForm.offered_price),
        currency: offerForm.currency || 'AED',
        transaction_intent: offerForm.transaction_intent,
        payment_frequency: offerForm.payment_frequency || null,
        financing_type: offerForm.financing_type || null,
        cheques_count: offerForm.cheques_count ? Number(offerForm.cheques_count) : null,
        terms_conditions: offerForm.terms_conditions || null,
        notes: offerForm.notes || null,
        submit_immediately: offerForm.submit_immediately,
      })
      setNewOfferOpen(false)
      setOfferForm({ ...offerForm, offered_price: '', terms_conditions: '', notes: '' })
      setTab('offers')
      loadAll()
    } catch (err) {
      setOfferErr(err.message)
    } finally {
      setOfferBusy(false)
    }
  }

  const handleCounterSubmit = async (offerId) => {
    if (!counterForm.counter_amount) {
      alert('Enter counteroffer amount.')
      return
    }
    setOfferBusy(true)
    try {
      await api.counterAgentOffer(offerId, {
        counter_amount: Number(counterForm.counter_amount),
        party: counterForm.party,
        reason: counterForm.reason || null,
        notes: counterForm.notes || null,
      })
      setActiveCounterOfferId(null)
      setCounterForm({ counter_amount: '', party: 'seller', reason: '', notes: '' })
      loadAll()
    } catch (e) {
      alert('Counteroffer failed: ' + e.message)
    } finally {
      setOfferBusy(false)
    }
  }

  const handleOfferStatus = async (offer, nextStatus) => {
    let reason = null
    if (nextStatus === 'rejected' || nextStatus === 'withdrawn') {
      reason = window.prompt(`Reason for marking Offer #${offer.id} as ${nextStatus}:`, '')
      if (reason === null) return
    }
    setOfferBusy(true)
    try {
      await api.transitionAgentOfferStatus(offer.id, { status: nextStatus, reason: reason || null })
      loadAll()
    } catch (e) {
      alert('Status update failed: ' + e.message)
    } finally {
      setOfferBusy(false)
    }
  }

  const handleCreateDeal = async (e) => {
    e.preventDefault()
    if (!dealForm.lead_id || !dealForm.property_id || !dealForm.agreed_amount) {
      setDealErr('Lead, property, and agreed amount are required.')
      return
    }
    setDealBusy(true)
    setDealErr('')
    try {
      const created = await api.createAgentDeal({
        lead_id: Number(dealForm.lead_id),
        property_id: Number(dealForm.property_id),
        offer_id: dealForm.offer_id ? Number(dealForm.offer_id) : null,
        transaction_type: dealForm.transaction_type,
        initial_status: dealForm.initial_status,
        agreed_amount: Number(dealForm.agreed_amount),
        currency: dealForm.currency || 'AED',
        estimated_commission_pct: dealForm.estimated_commission_pct ? Number(dealForm.estimated_commission_pct) : null,
        notes: dealForm.notes || null,
      })
      setNewDealOpen(false)
      if (created?.deal?.id) {
        navigate(`/agent/deals/${created.deal.id}`)
      } else {
        loadAll()
      }
    } catch (err) {
      setDealErr(err.message)
    } finally {
      setDealBusy(false)
    }
  }

  const dealStats = summary?.deals || {}
  const offerStats = summary?.offers || {}

  return (
    <div>
      {/* KPI Cards */}
      <div className="ax-stats">
        <div className="ax-stat c">
          <b>{dealStats.active ?? 0}</b>
          <span>Active deals</span>
        </div>
        <div className="ax-stat w">
          <b>{dealStats.completed ?? 0}</b>
          <span>Closed won deals</span>
        </div>
        <div className="ax-stat q">
          <b>{fmtAED(dealStats.active_pipeline_value_aed ?? 0)}</b>
          <span>Active pipeline value</span>
        </div>
        <div className="ax-stat v">
          <b>{fmtAED(dealStats.estimated_commission_aed ?? 0)}</b>
          <span>Est. commission</span>
        </div>
        <div className="ax-stat w">
          <b>{fmtAED(dealStats.verified_commission_aed ?? 0)}</b>
          <span>Verified commission</span>
        </div>
        <div className="ax-stat g">
          <b>{offerStats.active_negotiations ?? 0}</b>
          <span>Active offer negotiations</span>
        </div>
      </div>

      {/* Mode Switcher & Actions */}
      <div className="ax-panel" style={{ marginBottom: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              className={`btn btn-sm ${tab === 'deals' ? '' : 'btn-ghost'}`}
              onClick={() => setTab('deals')}
            >
              Deals &amp; Transactions ({deals.length})
            </button>
            <button
              className={`btn btn-sm ${tab === 'offers' ? '' : 'btn-ghost'}`}
              onClick={() => setTab('offers')}
            >
              Offers &amp; Negotiations ({offers.length})
            </button>
          </div>

          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button
              className="btn btn-sm btn-ghost"
              onClick={() => {
                setNewOfferOpen((o) => !o)
                setNewDealOpen(false)
              }}
            >
              {newOfferOpen ? 'Close Offer Form ✕' : '＋ New Offer'}
            </button>
            <button
              className="btn btn-sm"
              onClick={() => {
                setNewDealOpen((o) => !o)
                setNewOfferOpen(false)
              }}
            >
              {newDealOpen ? 'Close Deal Form ✕' : '＋ Open New Deal'}
            </button>
          </div>
        </div>

        {/* Create Offer Form */}
        {newOfferOpen && (
          <form onSubmit={handleCreateOffer} className="ax-form" style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid rgba(148,163,184,0.2)' }}>
            <h4 style={{ gridColumn: '1 / -1', margin: 0 }}>Record Customer Offer</h4>
            {offerErr && <div className="ax-warn" style={{ gridColumn: '1 / -1' }}>{offerErr}</div>}

            <label className="ax-field">
              <span>Customer lead *</span>
              <select
                className="ax-input"
                value={offerForm.lead_id}
                onChange={(e) => setOfferForm({ ...offerForm, lead_id: e.target.value })}
                required
              >
                <option value="">— Select lead —</option>
                {leads.map((l) => (
                  <option key={l.id} value={String(l.id)}>
                    #{l.id} · {l.name} ({l.location || 'UAE'})
                  </option>
                ))}
              </select>
            </label>

            <label className="ax-field">
              <span>Approved property *</span>
              <select
                className="ax-input"
                value={offerForm.property_id}
                onChange={(e) => setOfferForm({ ...offerForm, property_id: e.target.value })}
                required
              >
                <option value="">— Select property —</option>
                {properties.map((p) => (
                  <option key={p.id} value={String(p.id)}>
                    #{p.id} · {p.title || p.property_type} · AED {p.price?.toLocaleString?.() ?? p.price} ({p.availability})
                  </option>
                ))}
              </select>
            </label>

            <label className="ax-field">
              <span>Offered price (AED) *</span>
              <input
                className="ax-input"
                type="number"
                min="1"
                placeholder="2500000"
                value={offerForm.offered_price}
                onChange={(e) => setOfferForm({ ...offerForm, offered_price: e.target.value })}
                required
              />
            </label>

            <label className="ax-field">
              <span>Transaction intent</span>
              <select
                className="ax-input"
                value={offerForm.transaction_intent}
                onChange={(e) => setOfferForm({ ...offerForm, transaction_intent: e.target.value })}
              >
                <option value="purchase">Purchase / Sale</option>
                <option value="rent">Rent</option>
                <option value="lease">Commercial Lease</option>
              </select>
            </label>

            <label className="ax-field">
              <span>Payment frequency</span>
              <select
                className="ax-input"
                value={offerForm.payment_frequency}
                onChange={(e) => setOfferForm({ ...offerForm, payment_frequency: e.target.value })}
              >
                {PAYMENT_FREQUENCIES.map(([k, l]) => (
                  <option key={k} value={k}>{l}</option>
                ))}
              </select>
            </label>

            <label className="ax-field">
              <span>Financing type</span>
              <select
                className="ax-input"
                value={offerForm.financing_type}
                onChange={(e) => setOfferForm({ ...offerForm, financing_type: e.target.value })}
              >
                {FINANCING_OPTIONS.map(([k, l]) => (
                  <option key={k} value={k}>{l}</option>
                ))}
              </select>
            </label>

            <label className="ax-field">
              <span>Rental cheques (1–12)</span>
              <input
                className="ax-input"
                type="number"
                min="1"
                max="12"
                placeholder="1, 2, 4…"
                value={offerForm.cheques_count}
                onChange={(e) => setOfferForm({ ...offerForm, cheques_count: e.target.value })}
              />
            </label>

            <label className="ax-field">
              <span>Submission mode</span>
              <select
                className="ax-input"
                value={offerForm.submit_immediately ? 'submitted' : 'draft'}
                onChange={(e) => setOfferForm({ ...offerForm, submit_immediately: e.target.value === 'submitted' })}
              >
                <option value="submitted">Submit formal offer immediately</option>
                <option value="draft">Save as internal draft</option>
              </select>
            </label>

            <label className="ax-field wide">
              <span>Special terms &amp; contingencies</span>
              <input
                className="ax-input"
                placeholder="Subject to bank valuation & vacant possession on transfer…"
                value={offerForm.terms_conditions}
                onChange={(e) => setOfferForm({ ...offerForm, terms_conditions: e.target.value })}
              />
            </label>

            <div style={{ gridColumn: '1 / -1', display: 'flex', gap: 10 }}>
              <button className="btn btn-sm" type="submit" disabled={offerBusy}>
                {offerBusy ? 'Saving…' : 'Save Offer'}
              </button>
              <button className="btn btn-sm btn-ghost" type="button" onClick={() => setNewOfferOpen(false)}>
                Cancel
              </button>
            </div>
          </form>
        )}

        {/* Create Deal Form */}
        {newDealOpen && (
          <form onSubmit={handleCreateDeal} className="ax-form" style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid rgba(148,163,184,0.2)' }}>
            <h4 style={{ gridColumn: '1 / -1', margin: 0 }}>Open New Deal / Transaction</h4>
            {dealErr && <div className="ax-warn" style={{ gridColumn: '1 / -1' }}>{dealErr}</div>}

            <label className="ax-field">
              <span>Customer lead *</span>
              <select
                className="ax-input"
                value={dealForm.lead_id}
                onChange={(e) => setDealForm({ ...dealForm, lead_id: e.target.value })}
                required
              >
                <option value="">— Select lead —</option>
                {leads.map((l) => (
                  <option key={l.id} value={String(l.id)}>
                    #{l.id} · {l.name} ({l.location || 'UAE'})
                  </option>
                ))}
              </select>
            </label>

            <label className="ax-field">
              <span>Approved property *</span>
              <select
                className="ax-input"
                value={dealForm.property_id}
                onChange={(e) => setDealForm({ ...dealForm, property_id: e.target.value })}
                required
              >
                <option value="">— Select property —</option>
                {properties.map((p) => (
                  <option key={p.id} value={String(p.id)}>
                    #{p.id} · {p.title || p.property_type} · AED {p.price?.toLocaleString?.() ?? p.price}
                  </option>
                ))}
              </select>
            </label>

            <label className="ax-field">
              <span>Transaction type *</span>
              <select
                className="ax-input"
                value={dealForm.transaction_type}
                onChange={(e) => setDealForm({ ...dealForm, transaction_type: e.target.value })}
              >
                <option value="purchase">Purchase / Sale</option>
                <option value="rent">Residential Rent</option>
                <option value="lease">Commercial Lease</option>
              </select>
            </label>

            <label className="ax-field">
              <span>Initial deal stage</span>
              <select
                className="ax-input"
                value={dealForm.initial_status}
                onChange={(e) => setDealForm({ ...dealForm, initial_status: e.target.value })}
              >
                {DEAL_STAGES.filter(([k]) => !['completed', 'cancelled', 'failed'].includes(k)).map(([k, l]) => (
                  <option key={k} value={k}>{l}</option>
                ))}
              </select>
            </label>

            <label className="ax-field">
              <span>Agreed amount (AED) *</span>
              <input
                className="ax-input"
                type="number"
                min="1"
                placeholder="2500000"
                value={dealForm.agreed_amount}
                onChange={(e) => setDealForm({ ...dealForm, agreed_amount: e.target.value })}
                required
              />
            </label>

            <label className="ax-field">
              <span>Est. commission rate (%)</span>
              <input
                className="ax-input"
                type="number"
                step="0.1"
                min="0"
                max="100"
                value={dealForm.estimated_commission_pct}
                onChange={(e) => setDealForm({ ...dealForm, estimated_commission_pct: e.target.value })}
              />
            </label>

            <label className="ax-field wide">
              <span>Deal notes</span>
              <input
                className="ax-input"
                placeholder="DLD Form F preparation…"
                value={dealForm.notes}
                onChange={(e) => setDealForm({ ...dealForm, notes: e.target.value })}
              />
            </label>

            <div style={{ gridColumn: '1 / -1', display: 'flex', gap: 10 }}>
              <button className="btn btn-sm" type="submit" disabled={dealBusy}>
                {dealBusy ? 'Opening Deal…' : 'Create Deal & Initialize Compliance Checklist'}
              </button>
              <button className="btn btn-sm btn-ghost" type="button" onClick={() => setNewDealOpen(false)}>
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>

      {/* DEALS TAB */}
      {tab === 'deals' && (
        <section className="ax-panel">
          <div className="ax-panel__head">
            <h3>Deal &amp; Transaction Pipeline</h3>
            <select
              className="ax-input"
              style={{ minWidth: 210 }}
              value={stageFilter}
              onChange={(e) => setStageFilter(e.target.value)}
            >
              <option value="">All deal stages</option>
              {DEAL_STAGES.map(([k, l]) => (
                <option key={k} value={k}>{l}</option>
              ))}
            </select>
          </div>

          {loading && <div className="ax-empty"><div className="ax-spin" /> Loading deals…</div>}
          {!loading && error && <div className="ax-warn">⚠ {error}</div>}
          {!loading && !error && deals.length === 0 && (
            <div className="ax-empty sm">No deals found. Open a deal from an accepted offer or click “＋ Open New Deal”.</div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {deals.map((d) => {
              const summaryCk = d.checklist_summary || {}
              return (
                <div
                  key={d.id}
                  className="ax-row"
                  style={{ cursor: 'pointer', padding: 12 }}
                  onClick={() => navigate(`/agent/deals/${d.id}`)}
                >
                  <div className="ax-row__id">{d.deal_reference}</div>
                  <div className="ax-row__main">
                    <b>
                      {d.lead_name || `Lead #${d.lead_id}`} · {d.property_title || `Property #${d.property_id}`}
                    </b>
                    <span>
                      {d.transaction_type?.toUpperCase()} · Agreed: <b>{fmtAED(d.agreed_amount)}</b>
                      {' '}· Est. Comm: {fmtAED(d.estimated_commission)}
                      {d.commission_status !== 'estimated' && d.actual_commission != null
                        ? ` · ✓ Verified: ${fmtAED(d.actual_commission)}`
                        : ''}
                      {' '}· Checklist: {summaryCk.verified_required_items ?? 0}/{summaryCk.required_items ?? 0} verified
                    </span>
                  </div>
                  <span className="ax-tag">
                    {DEAL_STAGES.find(([k]) => k === d.status)?.[1] || d.status}
                  </span>
                  <div className="ax-row__time">{fmtDate(d.updated_at)}</div>
                </div>
              )
            })}
          </div>
        </section>
      )}

      {/* OFFERS TAB */}
      {tab === 'offers' && (
        <section className="ax-panel">
          <div className="ax-panel__head">
            <h3>Offers &amp; Counteroffer Negotiations</h3>
            <select
              className="ax-input"
              style={{ minWidth: 180 }}
              value={offerStatusFilter}
              onChange={(e) => setOfferStatusFilter(e.target.value)}
            >
              <option value="">All offer statuses</option>
              <option value="draft">Draft</option>
              <option value="submitted">Submitted</option>
              <option value="countered">Countered</option>
              <option value="accepted">Accepted</option>
              <option value="rejected">Rejected</option>
              <option value="withdrawn">Withdrawn</option>
              <option value="expired">Expired</option>
            </select>
          </div>

          {loading && <div className="ax-empty"><div className="ax-spin" /> Loading offers…</div>}
          {!loading && offers.length === 0 && (
            <div className="ax-empty sm">No offers recorded yet.</div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {offers.map((o) => {
              const isTerminal = ['accepted', 'rejected', 'withdrawn', 'expired'].includes(o.status)
              return (
                <div
                  key={o.id}
                  style={{
                    padding: 12,
                    borderRadius: 10,
                    border: '1px solid rgba(148,163,184,0.2)',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
                    <div>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                        <span className="ax-id">Offer #{o.id}</span>
                        <b>{fmtAED(o.current_price)}</b>
                        {o.current_price !== o.offered_price && (
                          <span className="ax-muted" style={{ fontSize: 12 }}>
                            (initial: {fmtAED(o.offered_price)})
                          </span>
                        )}
                        <span className={`ax-badge ${o.status}`}>{o.status}</span>
                        <span className="ax-tag">{o.transaction_intent}</span>
                        {o.financing_type && <span className="ax-tag">{o.financing_type}</span>}
                      </div>

                      <div style={{ fontSize: 13, marginTop: 6, display: 'flex', gap: 14, flexWrap: 'wrap' }}>
                        <span>
                          <b>Lead:</b>{' '}
                          <Link className="ax-link" to={`/agent/leads/${o.lead_id}`}>
                            #{o.lead_id} {o.lead_name || ''}
                          </Link>
                        </span>
                        <span>
                          <b>Property:</b>{' '}
                          <Link className="ax-link" to={`/agent/properties/${o.property_id}`}>
                            #{o.property_id} {o.property_title || ''}
                          </Link>
                        </span>
                        <span>
                          <b>Agent:</b> {o.assigned_agent_name || `#${o.assigned_agent_id}`}
                        </span>
                      </div>

                      {o.terms_conditions && (
                        <div className="ax-muted" style={{ fontSize: 12.5, marginTop: 4 }}>
                          Terms: {o.terms_conditions}
                        </div>
                      )}

                      {o.negotiation_history?.length > 0 && (
                        <div style={{ marginTop: 8, fontSize: 12, paddingLeft: 10, borderLeft: '2px solid rgba(148,163,184,0.3)' }}>
                          <b>Negotiation timeline ({o.negotiation_history.length} revision{o.negotiation_history.length === 1 ? '' : 's'}):</b>
                          {o.negotiation_history.map((rev, idx) => (
                            <div key={idx} style={{ marginTop: 2 }}>
                              • [{rev.party || rev.event_type}] <b>{fmtAED(rev.amount)}</b> — {rev.new_status}
                              {rev.notes ? ` (“${rev.notes}”)` : ''} · {fmtDate(rev.created_at)}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      {o.status === 'draft' && (
                        <button
                          className="btn btn-sm"
                          disabled={offerBusy}
                          onClick={() => handleOfferStatus(o, 'submitted')}
                        >
                          Submit Formal Offer
                        </button>
                      )}
                      {!isTerminal && o.status !== 'draft' && (
                        <>
                          <button
                            className="btn btn-sm"
                            disabled={offerBusy}
                            onClick={() => handleOfferStatus(o, 'accepted')}
                          >
                            ✓ Accept Offer
                          </button>
                          <button
                            className="btn btn-sm btn-ghost"
                            disabled={offerBusy}
                            onClick={() => setActiveCounterOfferId(activeCounterOfferId === o.id ? null : o.id)}
                          >
                            ⇄ Counteroffer
                          </button>
                          <button
                            className="btn btn-sm btn-ghost"
                            style={{ color: '#dc2626' }}
                            disabled={offerBusy}
                            onClick={() => handleOfferStatus(o, 'rejected')}
                          >
                            Reject
                          </button>
                          <button
                            className="btn btn-sm btn-ghost"
                            disabled={offerBusy}
                            onClick={() => handleOfferStatus(o, 'withdrawn')}
                          >
                            Withdraw
                          </button>
                        </>
                      )}
                      {o.status === 'accepted' && (
                        <button
                          className="btn btn-sm"
                          onClick={() => {
                            setDealForm({
                              ...dealForm,
                              lead_id: String(o.lead_id),
                              property_id: String(o.property_id),
                              offer_id: String(o.id),
                              transaction_type: o.transaction_intent || 'purchase',
                              agreed_amount: String(o.current_price || o.offered_price),
                              initial_status: 'offer_accepted',
                            })
                            setNewDealOpen(true)
                          }}
                        >
                          ＋ Open Deal from Offer →
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Counteroffer Inline Form */}
                  {activeCounterOfferId === o.id && (
                    <div className="ax-form" style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(148,163,184,0.2)' }}>
                      <label className="ax-field">
                        <span>Counter party</span>
                        <select
                          className="ax-input"
                          value={counterForm.party}
                          onChange={(e) => setCounterForm({ ...counterForm, party: e.target.value })}
                        >
                          <option value="seller">Seller / Developer</option>
                          <option value="landlord">Landlord</option>
                          <option value="buyer">Buyer / Tenant</option>
                        </select>
                      </label>
                      <label className="ax-field">
                        <span>Counteroffer amount (AED) *</span>
                        <input
                          className="ax-input"
                          type="number"
                          min="1"
                          value={counterForm.counter_amount}
                          onChange={(e) => setCounterForm({ ...counterForm, counter_amount: e.target.value })}
                        />
                      </label>
                      <label className="ax-field">
                        <span>Counter reason</span>
                        <input
                          className="ax-input"
                          value={counterForm.reason}
                          onChange={(e) => setCounterForm({ ...counterForm, reason: e.target.value })}
                        />
                      </label>
                      <label className="ax-field">
                        <span>Negotiation note</span>
                        <input
                          className="ax-input"
                          value={counterForm.notes}
                          onChange={(e) => setCounterForm({ ...counterForm, notes: e.target.value })}
                        />
                      </label>
                      <div style={{ gridColumn: '1 / -1', display: 'flex', gap: 8 }}>
                        <button className="btn btn-sm" disabled={offerBusy} onClick={() => handleCounterSubmit(o.id)}>
                          Record Counteroffer
                        </button>
                        <button className="btn btn-sm btn-ghost" onClick={() => setActiveCounterOfferId(null)}>
                          Close
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </section>
      )}
    </div>
  )
}

function DealDetailView({ dealId }) {
  const navigate = useNavigate()
  const { permissions } = useAuth()
  const canVerify = hasPerm({ permissions }, 'deals.checklist_verify')
  const canApprove = hasPerm({ permissions }, 'deals.approve')

  const [deal, setDeal] = React.useState(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState('')
  const [busy, setBusy] = React.useState(false)

  const [commForm, setCommForm] = React.useState({
    agreed_amount: '',
    estimated_commission_pct: '',
    actual_commission: '',
    commission_status: 'estimated',
    notes: '',
  })
  const [newCkItem, setNewCkItem] = React.useState({
    title: '',
    is_required: true,
    notes: '',
  })

  const load = React.useCallback(() => {
    setLoading(true)
    api
      .agentDeal(dealId)
      .then((res) => {
        const d = res.deal
        setDeal(d)
        setCommForm({
          agreed_amount: d.agreed_amount != null ? String(d.agreed_amount) : '',
          estimated_commission_pct: d.estimated_commission_pct != null ? String(d.estimated_commission_pct) : '',
          actual_commission: d.actual_commission != null ? String(d.actual_commission) : '',
          commission_status: d.commission_status || 'estimated',
          notes: d.notes || '',
        })
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [dealId])

  React.useEffect(() => {
    load()
  }, [load])

  const handleStageChange = async (nextStage) => {
    let reason = null
    let confirm = false
    if (nextStage === 'reservation_confirmed' || nextStage === 'completed') {
      const ok = window.confirm(
        `Confirm transition of ${deal.deal_reference} to "${nextStage}"? This will synchronize the linked property availability and lead lifecycle.`
      )
      if (!ok) return
      confirm = true
    }
    if (nextStage === 'cancelled' || nextStage === 'failed') {
      reason = window.prompt(`Enter reason for marking ${deal.deal_reference} as ${nextStage}:`, '')
      if (reason === null) return
    }
    setBusy(true)
    try {
      await api.transitionAgentDealStage(deal.id, {
        status: nextStage,
        reason: reason || null,
        confirm,
      })
      load()
    } catch (e) {
      alert('Stage transition rejected: ' + e.message)
    } finally {
      setBusy(false)
    }
  }

  const handleSaveFinancials = async () => {
    setBusy(true)
    try {
      const payload = {
        agreed_amount: commForm.agreed_amount !== '' ? Number(commForm.agreed_amount) : null,
        estimated_commission_pct: commForm.estimated_commission_pct !== '' ? Number(commForm.estimated_commission_pct) : null,
        notes: commForm.notes,
      }
      if (canApprove) {
        if (commForm.actual_commission !== '') {
          payload.actual_commission = Number(commForm.actual_commission)
        }
        payload.commission_status = commForm.commission_status
      }
      await api.updateAgentDeal(deal.id, payload)
      load()
    } catch (e) {
      alert('Update failed: ' + e.message)
    } finally {
      setBusy(false)
    }
  }

  const handleChecklistUpdate = async (item, nextStatus) => {
    const docRef = window.prompt(
      `Document reference / file number for "${item.title}" (optional):`,
      item.document_reference || ''
    )
    if (docRef === null) return
    setBusy(true)
    try {
      await api.updateDealChecklistItem(deal.id, item.id, {
        status: nextStatus,
        document_reference: docRef || null,
      })
      load()
    } catch (e) {
      alert('Checklist update failed: ' + e.message)
    } finally {
      setBusy(false)
    }
  }

  const handleAddChecklistItem = async (e) => {
    e.preventDefault()
    if (!newCkItem.title.trim()) return
    setBusy(true)
    try {
      const cleanTitle = newCkItem.title.trim()
      await api.addDealChecklistItem(deal.id, {
        code: cleanTitle.toLowerCase().replace(/[^a-z0-9]+/g, '_').slice(0, 60),
        title: cleanTitle,
        category: 'custom',
        is_required: newCkItem.is_required,
        notes: newCkItem.notes || null,
      })
      setNewCkItem({ title: '', is_required: true, notes: '' })
      load()
    } catch (err) {
      alert('Could not add checklist item: ' + err.message)
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <div className="ax-empty"><div className="ax-spin" /> Loading deal…</div>
  if (error) return <div className="ax-empty">⚠ {error}</div>
  if (!deal) return null

  const ckSummary = deal.checklist_summary || {}

  return (
    <div>
      <button className="ax-back" onClick={() => navigate('/agent/deals')}>← Back to deals &amp; offers</button>

      <div className="ax-panel" style={{ marginBottom: 14 }}>
        <div className="ax-panel__head">
          <div>
            <span className="ax-id">{deal.deal_reference}</span>
            <h2 style={{ margin: '4px 0' }}>
              {deal.lead_name || `Lead #${deal.lead_id}`} ↔ {deal.property_title || `Property #${deal.property_id}`}
            </h2>
            <div className="ax-muted" style={{ fontSize: 13 }}>
              Transaction: <b>{deal.transaction_type?.toUpperCase()}</b> · Property status:{' '}
              <b>{deal.property_availability || '—'}</b> · Assigned Agent:{' '}
              <b>{deal.assigned_agent_name || `#${deal.assigned_agent_id}`}</b>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6 }}>
            <label className="ax-field" style={{ margin: 0 }}>
              <span>Current pipeline stage</span>
              <select
                className="ax-input"
                value={deal.status}
                disabled={busy}
                onChange={(e) => handleStageChange(e.target.value)}
              >
                {DEAL_STAGES.map(([k, l]) => (
                  <option key={k} value={k}>{l}</option>
                ))}
              </select>
            </label>
            <div style={{ display: 'flex', gap: 8 }}>
              <Link className="ax-link" to={`/agent/leads/${deal.lead_id}`}>View Lead #{deal.lead_id} →</Link>
              <Link className="ax-link" to={`/agent/properties/${deal.property_id}`}>View Property #{deal.property_id} →</Link>
            </div>
          </div>
        </div>
      </div>

      <div className="ax-grid2">
        {/* Financials & Commission */}
        <section className="ax-panel">
          <div className="ax-panel__head">
            <h3>Financials &amp; Commission Tracking</h3>
            {deal.commission_status !== 'estimated' ? (
              <span className="ax-badge closed_won">✓ Commission {deal.commission_status}</span>
            ) : (
              <span className="ax-tag">Estimated (Unverified)</span>
            )}
          </div>

          <div className="ax-form">
            <label className="ax-field">
              <span>Agreed transaction amount (AED)</span>
              <input
                className="ax-input"
                type="number"
                value={commForm.agreed_amount}
                onChange={(e) => setCommForm({ ...commForm, agreed_amount: e.target.value })}
              />
            </label>
            <label className="ax-field">
              <span>Est. commission rate (%)</span>
              <input
                className="ax-input"
                type="number"
                step="0.1"
                value={commForm.estimated_commission_pct}
                onChange={(e) => setCommForm({ ...commForm, estimated_commission_pct: e.target.value })}
              />
            </label>
            <label className="ax-field">
              <span>Calculated est. commission</span>
              <input className="ax-input" disabled value={fmtAED(deal.estimated_commission)} />
            </label>
            <label className="ax-field">
              <span>Actual verified commission (AED)</span>
              <input
                className="ax-input"
                type="number"
                disabled={!canApprove}
                value={commForm.actual_commission}
                onChange={(e) => setCommForm({ ...commForm, actual_commission: e.target.value })}
              />
            </label>
            {canApprove && (
              <label className="ax-field wide">
                <span>Commission verification status</span>
                <select
                  className="ax-input"
                  value={commForm.commission_status}
                  onChange={(e) => setCommForm({ ...commForm, commission_status: e.target.value })}
                >
                  <option value="estimated">Estimated (Unverified)</option>
                  <option value="verified">Verified ✓</option>
                  <option value="earned">Earned</option>
                  <option value="paid">Paid</option>
                </select>
              </label>
            )}
            <label className="ax-field wide">
              <span>Deal &amp; conveyancing notes</span>
              <textarea
                className="ax-textarea"
                value={commForm.notes}
                onChange={(e) => setCommForm({ ...commForm, notes: e.target.value })}
              />
            </label>
            <div style={{ gridColumn: '1 / -1' }}>
              <button className="btn btn-sm" disabled={busy} onClick={handleSaveFinancials}>
                Save Financials &amp; Notes
              </button>
            </div>
          </div>

          {/* Stage History */}
          {deal.stage_history?.length > 0 && (
            <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid rgba(148,163,184,0.2)' }}>
              <b style={{ fontSize: 13 }}>Stage transition history</b>
              <div style={{ marginTop: 6, fontSize: 12, display: 'flex', flexDirection: 'column', gap: 4 }}>
                {deal.stage_history.map((h, i) => (
                  <div key={i}>
                    • {h.from_status ? `${h.from_status} → ` : ''}
                    <b>{h.to_status}</b> ({h.actor_label}) · {fmtDate(h.created_at)}
                    {h.reason ? ` — ${h.reason}` : ''}
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>

        {/* Compliance & Document Checklist */}
        <section className="ax-panel">
          <div className="ax-panel__head">
            <h3>UAE Real-Estate Compliance Checklist</h3>
            <span className="ax-count">
              {ckSummary.verified_required_items ?? 0}/{ckSummary.required_items ?? 0} required verified
            </span>
          </div>

          {!ckSummary.all_required_verified && (
            <div className="ax-warn" style={{ marginBottom: 12, fontSize: 12.5 }}>
              All required checklist milestones must be marked <b>Verified</b> or <b>Waived</b> by an authorized manager/admin before this deal can be marked <b>Completed</b>.
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {(deal.checklist || []).map((item) => (
              <div
                key={item.id}
                style={{
                  padding: 10,
                  borderRadius: 8,
                  border: '1px solid rgba(148,163,184,0.2)',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: 10,
                  flexWrap: 'wrap',
                }}
              >
                <div>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <b>{item.title}</b>
                    {item.is_required ? (
                      <span className="ax-tag">required</span>
                    ) : (
                      <span className="ax-muted" style={{ fontSize: 11 }}>(optional)</span>
                    )}
                  </div>
                  <div className="ax-muted" style={{ fontSize: 12, marginTop: 2 }}>
                    Status: <b>{item.status}</b>
                    {item.document_reference ? ` · Ref: ${item.document_reference}` : ''}
                    {item.verified_by_label ? ` · Verified by ${item.verified_by_label}` : ''}
                  </div>
                </div>

                <select
                  className="ax-input"
                  style={{ width: 150 }}
                  value={item.status}
                  disabled={busy}
                  onChange={(e) => handleChecklistUpdate(item, e.target.value)}
                >
                  {CHECKLIST_STATUSES.map(([k, l]) => {
                    const needsVerifyPerm = k === 'verified' || k === 'waived'
                    return (
                      <option key={k} value={k} disabled={needsVerifyPerm && !canVerify}>
                        {l}{needsVerifyPerm && !canVerify ? ' (Manager/Admin)' : ''}
                      </option>
                    )
                  })}
                </select>
              </div>
            ))}
          </div>

          {/* Add custom milestone */}
          <form onSubmit={handleAddChecklistItem} style={{ marginTop: 14, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <label className="ax-field" style={{ flex: 1, minWidth: 180 }}>
              <span>Add custom compliance milestone</span>
              <input
                className="ax-input"
                placeholder="e.g. Developer NOC issued…"
                value={newCkItem.title}
                onChange={(e) => setNewCkItem({ ...newCkItem, title: e.target.value })}
              />
            </label>
            <button className="btn btn-sm" type="submit" disabled={busy || !newCkItem.title.trim()}>
              ＋ Add Item
            </button>
          </form>
        </section>
      </div>
    </div>
  )
}
