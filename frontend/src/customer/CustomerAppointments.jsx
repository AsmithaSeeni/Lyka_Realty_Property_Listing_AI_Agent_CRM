import React, { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import api from '../api.js'

export default function CustomerAppointments() {
  const [appointments, setAppointments] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('all')

  // Reschedule Modal
  const [rescheduleTarget, setRescheduleTarget] = useState(null)
  const [newDate, setNewDate] = useState('')
  const [newTime, setNewTime] = useState('11:00')
  const [rescheduleReason, setRescheduleReason] = useState('')
  const [rescheduleSubmitting, setRescheduleSubmitting] = useState(false)
  const [rescheduleError, setRescheduleError] = useState('')

  // Cancel Modal
  const [cancelTarget, setCancelTarget] = useState(null)
  const [cancelReason, setCancelReason] = useState('')
  const [cancelSubmitting, setCancelSubmitting] = useState(false)
  const [cancelError, setCancelError] = useState('')

  const loadAppointments = () => {
    setLoading(true)
    api.customerAppointments()
      .then((res) => setAppointments(res.results || []))
      .catch((err) => setError(err.message || 'Failed to load viewing schedule'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadAppointments()
  }, [])

  const handleReschedule = async (e) => {
    e.preventDefault()
    setRescheduleSubmitting(true)
    setRescheduleError('')

    try {
      const startIso = `${newDate}T${newTime}:00`
      const endD = new Date(startIso)
      endD.setMinutes(endD.getMinutes() + 45)
      const endH = String(endD.getHours()).padStart(2, '0')
      const endM = String(endD.getMinutes()).padStart(2, '0')
      const endIso = `${newDate}T${endH}:${endM}:00`

      await api.customerRescheduleViewing(rescheduleTarget.id, {
        new_start_at: startIso,
        new_end_at: endIso,
        reason: rescheduleReason.trim() || undefined,
      })
      setRescheduleTarget(null)
      loadAppointments()
    } catch (err) {
      setRescheduleError(err.message || 'Failed to request reschedule')
    } finally {
      setRescheduleSubmitting(false)
    }
  }

  const handleCancel = async (e) => {
    e.preventDefault()
    setCancelSubmitting(true)
    setCancelError('')

    try {
      await api.customerCancelViewing(cancelTarget.id, {
        reason: cancelReason.trim() || undefined,
      })
      setCancelTarget(null)
      loadAppointments()
    } catch (err) {
      setCancelError(err.message || 'Failed to cancel viewing')
    } finally {
      setCancelSubmitting(false)
    }
  }

  const filtered = appointments.filter((a) => {
    if (filter === 'all') return true
    if (filter === 'confirmed') return a.customer_confirmation_status === 'confirmed' && a.status !== 'cancelled'
    if (filter === 'pending') return a.customer_confirmation_status === 'pending' && a.status !== 'cancelled'
    if (filter === 'rescheduled') return a.customer_confirmation_status === 'reschedule_requested' || a.status === 'rescheduled'
    if (filter === 'cancelled') return a.status === 'cancelled'
    return true
  })

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <span className="text-xs uppercase tracking-widest text-amber-500 font-semibold">
            Viewing Schedule
          </span>
          <h1 className="text-2xl sm:text-3xl font-serif text-white mt-1">
            My Property Viewings
          </h1>
          <p className="text-xs sm:text-sm text-stone-400 mt-1">
            Manage your requested and confirmed in-person or virtual property viewings across Dubai.
          </p>
        </div>

        <Link
          to="/properties"
          className="px-4 py-2 rounded-xl text-xs font-semibold bg-gradient-to-r from-amber-600 to-amber-500 text-black hover:from-amber-500 hover:to-amber-400 transition-all shadow-md shadow-amber-950/40 text-center shrink-0"
        >
          + Request New Viewing
        </Link>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-2 border-b border-stone-800 pb-2 overflow-x-auto scrollbar-none">
        {[
          { id: 'all', label: 'All Viewings', count: appointments.length },
          { id: 'confirmed', label: 'Confirmed', count: appointments.filter((a) => a.customer_confirmation_status === 'confirmed' && a.status !== 'cancelled').length },
          { id: 'pending', label: 'Pending Agent', count: appointments.filter((a) => a.customer_confirmation_status === 'pending' && a.status !== 'cancelled').length },
          { id: 'rescheduled', label: 'Reschedule Requested', count: appointments.filter((a) => a.customer_confirmation_status === 'reschedule_requested' || a.status === 'rescheduled').length },
          { id: 'cancelled', label: 'Cancelled', count: appointments.filter((a) => a.status === 'cancelled').length },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setFilter(tab.id)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              filter === tab.id
                ? 'bg-amber-950/70 text-amber-300 border border-amber-800/60'
                : 'text-stone-400 hover:text-stone-200'
            }`}
          >
            {tab.label} ({tab.count})
          </button>
        ))}
      </div>

      {loading ? (
        <div className="py-12 text-center text-stone-400 text-sm">
          <div className="w-8 h-8 border-2 border-amber-600/40 border-t-amber-500 rounded-full animate-spin mx-auto mb-3" />
          Loading viewing schedule...
        </div>
      ) : error ? (
        <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-800/50 text-rose-200 text-xs">
          ✕ {error}
        </div>
      ) : filtered.length === 0 ? (
        <div className="bg-[#181615] border border-stone-800 rounded-2xl p-12 text-center text-stone-400">
          <span className="text-4xl block mb-2 opacity-50">📅</span>
          <h3 className="text-sm font-medium text-white">No Viewings Found</h3>
          <p className="text-xs text-stone-500 mt-1 max-w-sm mx-auto">
            You don't have any viewings in this category. Schedule a viewing from any property page or your saved shortlist.
          </p>
          <Link
            to="/properties"
            className="mt-4 inline-block px-4 py-2 rounded-lg text-xs font-semibold bg-stone-800 hover:bg-stone-700 text-white"
          >
            Browse Properties
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {filtered.map((appt) => {
            const isConfirmed = appt.customer_confirmation_status === 'confirmed' && appt.status !== 'cancelled'
            const isPending = appt.customer_confirmation_status === 'pending' && appt.status !== 'cancelled'
            const isResched = appt.customer_confirmation_status === 'reschedule_requested' || appt.status === 'rescheduled'
            const isCancelled = appt.status === 'cancelled'

            return (
              <div
                key={appt.id}
                className="bg-[#181615] border border-stone-800/80 rounded-2xl p-5 flex flex-col justify-between hover:border-amber-900/30 transition-all shadow-lg"
              >
                <div>
                  <div className="flex items-start justify-between gap-3 mb-3">
                    <span
                      className={`text-[10px] uppercase tracking-wider font-bold px-2 py-0.5 rounded-full ${
                        isConfirmed
                          ? 'bg-emerald-950/80 text-emerald-400 border border-emerald-800/50'
                          : isResched
                          ? 'bg-sky-950/80 text-sky-400 border border-sky-800/50'
                          : isCancelled
                          ? 'bg-stone-900 text-stone-500 border border-stone-800'
                          : 'bg-amber-950/80 text-amber-400 border border-amber-800/50'
                      }`}
                    >
                      {isConfirmed
                        ? 'Confirmed Viewing'
                        : isResched
                        ? 'Reschedule Requested'
                        : isCancelled
                        ? 'Cancelled'
                        : 'Pending Agent Confirmation'}
                    </span>

                    <span className="text-xs text-stone-400 flex items-center gap-1">
                      {appt.meeting_method === 'video' ? '🎥 Video Tour' : appt.meeting_method === 'phone' ? '📞 Phone' : '📍 In Person'}
                    </span>
                  </div>

                  <h3 className="text-base font-serif text-white font-medium">
                    {appt.property_title || 'Private Residence'}
                  </h3>
                  <p className="text-xs text-stone-400 mt-0.5">
                    📍 {appt.property_location || 'Dubai, UAE'}
                  </p>

                  <div className="mt-4 p-3 rounded-xl bg-stone-900/70 border border-stone-800 text-xs space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-stone-400">Date & Time:</span>
                      <span className="text-white font-medium">
                        {appt.start_at_local ? new Date(appt.start_at_local).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : appt.start_at}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-stone-400">Property Specialist:</span>
                      <span className="text-amber-400 font-medium">{appt.agent_name || 'Lyka Specialist'}</span>
                    </div>
                    {appt.notes && (
                      <div className="pt-1.5 border-t border-stone-800/80 text-stone-400 italic">
                        "{appt.notes}"
                      </div>
                    )}
                    {appt.cancellation_reason && (
                      <div className="pt-1.5 border-t border-stone-800/80 text-rose-300">
                        Reason: {appt.cancellation_reason}
                      </div>
                    )}
                  </div>
                </div>

                <div className="mt-5 pt-4 border-t border-stone-800 flex items-center justify-between gap-2">
                  {appt.property_id ? (
                    <Link
                      to={`/properties/${appt.property_id}`}
                      className="text-xs text-amber-400 hover:underline font-medium"
                    >
                      View Listing →
                    </Link>
                  ) : <span />}

                  {!isCancelled && (
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => {
                          setRescheduleTarget(appt)
                          setNewDate(new Date().toISOString().split('T')[0])
                        }}
                        className="text-xs px-2.5 py-1 rounded bg-stone-900 hover:bg-stone-800 text-stone-300 border border-stone-700 transition-colors"
                      >
                        Reschedule
                      </button>
                      <button
                        type="button"
                        onClick={() => setCancelTarget(appt)}
                        className="text-xs px-2.5 py-1 rounded bg-rose-950/30 hover:bg-rose-950/60 text-rose-300 border border-rose-900/40 transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Reschedule Modal */}
      {rescheduleTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="bg-[#181615] border border-stone-800 rounded-2xl w-full max-w-md p-6 text-stone-200 shadow-2xl">
            <div className="flex items-center justify-between border-b border-stone-800 pb-3 mb-4">
              <h3 className="text-base font-serif text-white">Reschedule Viewing</h3>
              <button onClick={() => setRescheduleTarget(null)} className="text-stone-400 hover:text-white">✕</button>
            </div>

            {rescheduleError && (
              <div className="mb-4 p-3 rounded-lg bg-rose-950/40 border border-rose-800 text-rose-200 text-xs">
                {rescheduleError}
              </div>
            )}

            <form onSubmit={handleReschedule} className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-stone-300 mb-1">New Date</label>
                  <input
                    type="date"
                    required
                    min={new Date().toISOString().split('T')[0]}
                    value={newDate}
                    onChange={(e) => setNewDate(e.target.value)}
                    className="w-full bg-stone-900 border border-stone-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-stone-300 mb-1">New Time Slot</label>
                  <select
                    value={newTime}
                    onChange={(e) => setNewTime(e.target.value)}
                    className="w-full bg-stone-900 border border-stone-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500"
                  >
                    <option value="09:30">09:30 AM</option>
                    <option value="11:00">11:00 AM</option>
                    <option value="13:30">01:30 PM</option>
                    <option value="15:00">03:00 PM</option>
                    <option value="16:30">04:30 PM</option>
                    <option value="18:00">06:00 PM</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-stone-300 mb-1">Reason for Reschedule</label>
                <textarea
                  rows={2}
                  value={rescheduleReason}
                  onChange={(e) => setRescheduleReason(e.target.value)}
                  placeholder="e.g. Schedule conflict, traveling..."
                  className="w-full bg-stone-900 border border-stone-700 rounded-lg p-2.5 text-xs text-white placeholder-stone-500 focus:outline-none focus:border-amber-500"
                />
              </div>

              <div className="pt-2 flex items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setRescheduleTarget(null)}
                  disabled={rescheduleSubmitting}
                  className="px-4 py-2 rounded-lg text-xs font-medium text-stone-300 hover:text-white"
                >
                  Close
                </button>
                <button
                  type="submit"
                  disabled={rescheduleSubmitting}
                  className="px-5 py-2 rounded-lg text-xs font-semibold bg-amber-600 text-black hover:bg-amber-500 disabled:opacity-50"
                >
                  {rescheduleSubmitting ? 'Requesting...' : 'Request Reschedule'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Cancel Modal */}
      {cancelTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="bg-[#181615] border border-stone-800 rounded-2xl w-full max-w-md p-6 text-stone-200 shadow-2xl">
            <div className="flex items-center justify-between border-b border-stone-800 pb-3 mb-4">
              <h3 className="text-base font-serif text-white">Cancel Viewing</h3>
              <button onClick={() => setCancelTarget(null)} className="text-stone-400 hover:text-white">✕</button>
            </div>

            {cancelError && (
              <div className="mb-4 p-3 rounded-lg bg-rose-950/40 border border-rose-800 text-rose-200 text-xs">
                {cancelError}
              </div>
            )}

            <form onSubmit={handleCancel} className="space-y-4">
              <p className="text-xs text-stone-400">
                Are you sure you want to cancel the scheduled viewing for <strong className="text-white">{cancelTarget.property_title || 'this property'}</strong>?
              </p>

              <div>
                <label className="block text-xs font-medium text-stone-300 mb-1">Reason for Cancellation</label>
                <textarea
                  rows={2}
                  value={cancelReason}
                  onChange={(e) => setCancelReason(e.target.value)}
                  placeholder="e.g. Changed preferences, already viewed another property..."
                  className="w-full bg-stone-900 border border-stone-700 rounded-lg p-2.5 text-xs text-white placeholder-stone-500 focus:outline-none focus:border-amber-500"
                />
              </div>

              <div className="pt-2 flex items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setCancelTarget(null)}
                  disabled={cancelSubmitting}
                  className="px-4 py-2 rounded-lg text-xs font-medium text-stone-300 hover:text-white"
                >
                  Keep Viewing
                </button>
                <button
                  type="submit"
                  disabled={cancelSubmitting}
                  className="px-5 py-2 rounded-lg text-xs font-semibold bg-rose-700 text-white hover:bg-rose-600 disabled:opacity-50"
                >
                  {cancelSubmitting ? 'Cancelling...' : 'Confirm Cancellation'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

