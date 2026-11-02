import React, { useState, useEffect } from 'react'
import api from '../api.js'

const LEAVE_TYPES = ['Casual Leave', 'Sick Leave', 'Annual/Earned Leave', 'Unpaid Leave', 'Other']

export default function AgentLeaveModal({ isOpen, onClose }) {
  const [leaves, setLeaves] = useState([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [showForm, setShowForm] = useState(false)

  const [form, setForm] = useState({
    leave_type: 'Casual Leave',
    start_date: new Date().toISOString().split('T')[0],
    end_date: new Date().toISOString().split('T')[0],
    reason: '',
  })

  const loadLeaves = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await api.agentOwnLeaveRequests()
      setLeaves(res.results || [])
    } catch (err) {
      setError(err.message || 'Failed to load leave history')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (isOpen) {
      loadLeaves()
      setShowForm(false)
      setError('')
      setSuccess('')
    }
  }, [isOpen])

  if (!isOpen) return null

  const handleSubmit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    setSuccess('')
    try {
      await api.agentSubmitLeave({
        leave_type: form.leave_type,
        start_date: form.start_date,
        end_date: form.end_date,
        reason: form.reason.trim(),
      })
      setSuccess('Leave request submitted successfully. Pending HR review.')
      setShowForm(false)
      setForm({
        leave_type: 'Casual Leave',
        start_date: new Date().toISOString().split('T')[0],
        end_date: new Date().toISOString().split('T')[0],
        reason: '',
      })
      loadLeaves()
    } catch (err) {
      setError(err.message || 'Failed to submit leave request')
    } finally {
      setBusy(false)
    }
  }

  const handleCancelLeave = async (id) => {
    if (!window.confirm('Cancel this pending leave request?')) return
    setBusy(true)
    setError('')
    try {
      await api.agentCancelLeave(id)
      setSuccess('Leave request cancelled.')
      loadLeaves()
    } catch (err) {
      setError(err.message || 'Failed to cancel leave request')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(15, 23, 42, 0.75)',
        backdropFilter: 'blur(4px)',
        zIndex: 99999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 20,
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: 620,
          background: '#ffffff',
          borderRadius: 14,
          boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.3)',
          overflow: 'hidden',
          border: '1px solid #e2e8f0',
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '18px 24px',
            background: 'linear-gradient(135deg, #4a0e2e 0%, #2b081b 100%)',
            color: '#fff',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#d4af37', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Self-Service Employee Portal
            </div>
            <h3 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: '#fff' }}>
              My Attendance & Leave Requests
            </h3>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#fff',
              fontSize: 20,
              cursor: 'pointer',
              padding: 4,
            }}
          >
            ✕
          </button>
        </div>

        {/* Content Body */}
        <div style={{ padding: '20px 24px', overflowY: 'auto', flex: 1 }}>
          {error && (
            <div style={{ padding: '10px 14px', background: '#fee2e2', border: '1px solid #f87171', color: '#991b1b', borderRadius: 8, marginBottom: 14, fontSize: 13 }}>
              ⚠️ {error}
            </div>
          )}
          {success && (
            <div style={{ padding: '10px 14px', background: '#ecfdf5', border: '1px solid #34d399', color: '#065f46', borderRadius: 8, marginBottom: 14, fontSize: 13 }}>
              ✓ {success}
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <span style={{ fontSize: 14, fontWeight: 700, color: '#1e293b' }}>
              {showForm ? 'New Leave Application' : 'My Leave History'}
            </span>
            <button
              type="button"
              onClick={() => setShowForm(!showForm)}
              style={{
                fontSize: 12,
                fontWeight: 600,
                padding: '6px 14px',
                borderRadius: 6,
                background: showForm ? '#e2e8f0' : '#4a0e2e',
                color: showForm ? '#1e293b' : '#fff',
                border: 'none',
                cursor: 'pointer',
              }}
            >
              {showForm ? 'View Leave History' : '＋ Apply for Leave'}
            </button>
          </div>

          {showForm ? (
            <form onSubmit={handleSubmit}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 14, marginBottom: 16 }}>
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#334155', marginBottom: 4 }}>
                    Leave Type *
                  </label>
                  <select
                    className="ax-input"
                    style={{ width: '100%' }}
                    value={form.leave_type}
                    onChange={(e) => setForm({ ...form, leave_type: e.target.value })}
                    required
                  >
                    {LEAVE_TYPES.map((t) => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                  <div>
                    <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#334155', marginBottom: 4 }}>
                      Start Date *
                    </label>
                    <input
                      type="date"
                      className="ax-input"
                      style={{ width: '100%' }}
                      value={form.start_date}
                      onChange={(e) => setForm({ ...form, start_date: e.target.value })}
                      required
                    />
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#334155', marginBottom: 4 }}>
                      End Date *
                    </label>
                    <input
                      type="date"
                      className="ax-input"
                      style={{ width: '100%' }}
                      value={form.end_date}
                      onChange={(e) => setForm({ ...form, end_date: e.target.value })}
                      required
                    />
                  </div>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#334155', marginBottom: 4 }}>
                    Reason / Justification * (min 5 characters)
                  </label>
                  <textarea
                    className="ax-input"
                    style={{ width: '100%', minHeight: 70, resize: 'vertical' }}
                    placeholder="Provide details for HR review..."
                    value={form.reason}
                    onChange={(e) => setForm({ ...form, reason: e.target.value })}
                    required
                    minLength={5}
                  />
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
                <button
                  type="button"
                  onClick={() => setShowForm(false)}
                  style={{ padding: '8px 16px', borderRadius: 6, background: '#f1f5f9', border: 'none', cursor: 'pointer' }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={busy}
                  style={{
                    padding: '8px 18px',
                    borderRadius: 6,
                    background: '#4a0e2e',
                    color: '#fff',
                    border: 'none',
                    fontWeight: 600,
                    cursor: busy ? 'not-allowed' : 'pointer',
                  }}
                >
                  {busy ? 'Submitting...' : 'Submit Request'}
                </button>
              </div>
            </form>
          ) : loading ? (
            <div style={{ textAlign: 'center', padding: 24, color: '#64748b' }}>Loading records...</div>
          ) : leaves.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 32, background: '#f8fafc', borderRadius: 8, color: '#64748b' }}>
              No leave requests submitted yet.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {leaves.map((l) => (
                <div
                  key={l.id}
                  style={{
                    padding: 14,
                    background: '#f8fafc',
                    borderRadius: 8,
                    border: '1px solid #e2e8f0',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                  }}
                >
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontWeight: 700, fontSize: 14, color: '#1e293b' }}>{l.leave_type}</span>
                      <span
                        style={{
                          fontSize: 11,
                          fontWeight: 700,
                          padding: '2px 8px',
                          borderRadius: 4,
                          background:
                            l.status === 'approved' ? '#dcfce7' : l.status === 'rejected' ? '#fee2e2' : l.status === 'cancelled' ? '#f1f5f9' : '#fef9c3',
                          color:
                            l.status === 'approved' ? '#166534' : l.status === 'rejected' ? '#991b1b' : l.status === 'cancelled' ? '#64748b' : '#854d0e',
                        }}
                      >
                        {l.status ? l.status.toUpperCase() : 'PENDING'}
                      </span>
                    </div>
                    <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
                      📅 {l.start_date} to {l.end_date} · Reason: {l.reason}
                    </div>
                    {l.review_notes && (
                      <div style={{ fontSize: 11, color: '#0369a1', marginTop: 3 }}>
                        HR Note: {l.review_notes}
                      </div>
                    )}
                  </div>
                  {l.status === 'pending' && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => handleCancelLeave(l.id)}
                      style={{
                        padding: '4px 10px',
                        borderRadius: 6,
                        background: '#fef2f2',
                        color: '#dc2626',
                        border: '1px solid #fecaca',
                        fontSize: 11,
                        fontWeight: 600,
                        cursor: 'pointer',
                      }}
                    >
                      Cancel
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

