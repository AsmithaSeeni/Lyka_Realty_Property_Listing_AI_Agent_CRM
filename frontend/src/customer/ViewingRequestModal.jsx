import React, { useState } from 'react'
import api from '../api.js'

export default function ViewingRequestModal({ property, isOpen, onClose, onSuccess }) {
  const [date, setDate] = useState(() => {
    const d = new Date()
    d.setDate(d.getDate() + 2)
    return d.toISOString().split('T')[0]
  })
  const [timeSlot, setTimeSlot] = useState('11:00')
  const [meetingMethod, setMeetingMethod] = useState('in_person')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  if (!isOpen || !property) return null

  const propId = property.property_id || property.id
  const propSource = property.source || 'record'
  const propTitle = property.title || property.property_type || 'Property'

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setError('')

    try {
      const startIso = `${date}T${timeSlot}:00`
      const endD = new Date(`${date}T${timeSlot}:00`)
      endD.setMinutes(endD.getMinutes() + 45)
      const endH = String(endD.getHours()).padStart(2, '0')
      const endM = String(endD.getMinutes()).padStart(2, '0')
      const endIso = `${date}T${endH}:${endM}:00`

      const payload = {
        property_id: Number(propId),
        property_source: propSource,
        start_at: startIso,
        end_at: endIso,
        timezone: 'Asia/Dubai',
        meeting_method: meetingMethod,
        notes: notes.trim() || undefined,
        idempotency_key: `vr-${propSource}-${propId}-${Date.now()}`,
      }

      const res = await api.customerRequestViewing(payload)
      if (onSuccess) onSuccess(res.appointment)
      onClose()
    } catch (err) {
      setError(err.message || 'Failed to submit viewing request')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div data-ui className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 animate-fade-in">
      <div className="bg-[#181615] border border-amber-900/40 rounded-2xl w-full max-w-lg p-6 text-stone-200 shadow-2xl">
        <div className="flex items-start justify-between border-b border-stone-800 pb-4 mb-5">
          <div>
            <span className="text-xs uppercase tracking-widest text-amber-500 font-semibold">Private Viewing</span>
            <h3 className="text-xl font-serif text-white mt-1">Schedule a Property Viewing</h3>
          </div>
          <button
            onClick={onClose}
            className="text-stone-400 hover:text-white p-1 rounded-lg transition-colors text-sm"
          >
            ✕
          </button>
        </div>

        <div className="bg-stone-900 rounded-xl p-3.5 border border-stone-800 mb-5 flex items-center gap-3">
          <div className="w-12 h-12 rounded-lg bg-amber-950/60 border border-amber-800/40 flex items-center justify-center font-serif text-amber-400 font-bold shrink-0">
            LR
          </div>
          <div className="min-w-0">
            <h4 className="text-sm font-medium text-white truncate">{propTitle}</h4>
            <p className="text-xs text-stone-400 truncate">{property.location || 'Dubai, UAE'}</p>
            {property.price && (
              <p className="text-xs font-semibold text-amber-400 mt-0.5">
                AED {property.price.toLocaleString?.() || property.price}
              </p>
            )}
          </div>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-rose-950/40 border border-rose-800/50 text-rose-200 text-xs">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-stone-300 mb-1">Preferred Date</label>
              <input
                type="date"
                required
                min={new Date().toISOString().split('T')[0]}
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="w-full bg-stone-900 border border-stone-700/80 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-stone-300 mb-1">Time Slot (UAE Time)</label>
              <select
                value={timeSlot}
                onChange={(e) => setTimeSlot(e.target.value)}
                className="w-full bg-stone-900 border border-stone-700/80 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500"
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
            <label className="block text-xs font-medium text-stone-300 mb-1">Meeting Type</label>
            <div className="grid grid-cols-3 gap-2">
              {[
                { id: 'in_person', label: 'In Person' },
                { id: 'video', label: 'Video Tour' },
                { id: 'phone', label: 'Consultation' },
              ].map((m) => (
                <button
                  type="button"
                  key={m.id}
                  onClick={() => setMeetingMethod(m.id)}
                  className={`py-2 px-2 text-xs rounded-lg border text-center transition-all ${
                    meetingMethod === m.id
                      ? 'bg-amber-950/70 border-amber-600 text-amber-200 font-medium'
                      : 'bg-stone-900 border-stone-800 text-stone-400 hover:text-stone-200'
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-stone-300 mb-1">Special Requests / Notes</label>
            <textarea
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="e.g. Prefer high floor unit, interested in flexible payment plans..."
              className="w-full bg-stone-900 border border-stone-700/80 rounded-lg p-2.5 text-xs text-white placeholder-stone-500 focus:outline-none focus:border-amber-500"
            />
          </div>

          <div className="pt-2 flex items-center justify-end gap-3 border-t border-stone-800">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="px-4 py-2 rounded-lg text-xs font-medium text-stone-300 hover:text-white transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-5 py-2 rounded-lg text-xs font-semibold bg-amber-600 text-black hover:bg-amber-500 transition-colors disabled:opacity-50"
            >
              {submitting ? 'Submitting...' : 'Confirm Request'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
