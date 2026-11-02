import React, { useState, useEffect } from 'react'
import { useOutletContext } from 'react-router-dom'
import api from '../api.js'

const POPULAR_LOCATIONS = [
  'Dubai Marina',
  'Downtown Dubai',
  'Palm Jumeirah',
  'Dubai Hills Estate',
  'Business Bay',
  'DIFC',
  'Arabian Ranches',
  'Jumeirah Beach Residence',
  'Creek Harbour',
  'City Walk',
]

const PROPERTY_TYPES = [
  'Apartment',
  'Villa',
  'Townhouse',
  'Penthouse',
  'Duplex',
  'Studio',
]

export default function CustomerProfile() {
  const { customer, setCustomer } = useOutletContext()
  const [profile, setProfile] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [successMsg, setSuccessMsg] = useState('')
  const [errorMsg, setErrorMsg] = useState('')

  // Form state
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [contactMethod, setContactMethod] = useState('email')
  const [purpose, setPurpose] = useState('buy')
  const [propertyType, setPropertyType] = useState('Apartment')
  const [locations, setLocations] = useState([])
  const [bedroomsMin, setBedroomsMin] = useState('')
  const [bedroomsMax, setBedroomsMax] = useState('')
  const [budgetMin, setBudgetMin] = useState('')
  const [budgetMax, setBudgetMax] = useState('')

  // Password modal
  const [pwModalOpen, setPwModalOpen] = useState(false)
  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [pwError, setPwError] = useState('')
  const [pwSuccess, setPwSuccess] = useState('')
  const [pwSubmitting, setPwSubmitting] = useState(false)

  const loadProfile = () => {
    setLoading(true)
    api.customerProfile()
      .then((data) => {
        setProfile(data)
        setName(data.name || '')
        setPhone(data.phone || '')
        setContactMethod(data.preferred_contact_method || 'email')
        setPurpose(data.purpose || 'buy')
        setPropertyType(data.property_type || 'Apartment')
        setLocations(Array.isArray(data.preferred_locations) ? data.preferred_locations : [])
        setBedroomsMin(data.bedrooms_min ?? '')
        setBedroomsMax(data.bedrooms_max ?? '')
        setBudgetMin(data.budget_min ?? '')
        setBudgetMax(data.budget_max ?? '')
      })
      .catch((err) => setErrorMsg(err.message || 'Failed to load profile'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadProfile()
  }, [])

  const toggleLocation = (loc) => {
    setLocations((prev) =>
      prev.includes(loc) ? prev.filter((l) => l !== loc) : [...prev, loc]
    )
  }

  const handleSave = async (e) => {
    e.preventDefault()
    setSaving(true)
    setSuccessMsg('')
    setErrorMsg('')

    try {
      const payload = {
        name: name.trim() || undefined,
        phone: phone.trim() || undefined,
        preferred_contact_method: contactMethod,
        purpose,
        property_type: propertyType,
        preferred_locations: locations,
        bedrooms_min: bedroomsMin !== '' ? Number(bedroomsMin) : undefined,
        bedrooms_max: bedroomsMax !== '' ? Number(bedroomsMax) : undefined,
        budget_min: budgetMin !== '' ? Number(budgetMin) : undefined,
        budget_max: budgetMax !== '' ? Number(budgetMax) : undefined,
      }
      const updated = await api.customerUpdateProfile(payload)
      setProfile(updated)
      if (setCustomer) setCustomer(updated)
      setSuccessMsg('Your profile and preferences have been updated successfully.')
      setTimeout(() => setSuccessMsg(''), 4000)
    } catch (err) {
      setErrorMsg(err.message || 'Failed to update preferences')
    } finally {
      setSaving(false)
    }
  }

  const handleChangePassword = async (e) => {
    e.preventDefault()
    setPwSubmitting(true)
    setPwError('')
    setPwSuccess('')

    if (newPw !== confirmPw) {
      setPwError('New passwords do not match')
      setPwSubmitting(false)
      return
    }

    try {
      await api.customerChangePassword({
        current_password: currentPw,
        new_password: newPw,
        confirm_new_password: confirmPw,
      })
      setPwSuccess('Password changed successfully!')
      setCurrentPw('')
      setNewPw('')
      setConfirmPw('')
      setTimeout(() => {
        setPwSuccess('')
        setPwModalOpen(false)
      }, 1800)
    } catch (err) {
      setPwError(err.message || 'Failed to change password')
    } finally {
      setPwSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="py-12 text-center text-stone-400 text-sm">
        <div className="w-8 h-8 border-2 border-amber-600/40 border-t-amber-500 rounded-full animate-spin mx-auto mb-3" />
        Loading your preferences...
      </div>
    )
  }

  const completion = profile?.profile_completion || { percentage: 0, missing_fields: [] }

  return (
    <div className="max-w-4xl mx-auto space-y-8 animate-fade-in">
      <div>
        <span className="text-xs uppercase tracking-widest text-amber-500 font-semibold">
          Account Settings
        </span>
        <h1 className="text-2xl sm:text-3xl font-serif text-white mt-1">
          Profile & Real Estate Preferences
        </h1>
        <p className="text-xs sm:text-sm text-stone-400 mt-1">
          Tailor your property search criteria to ensure our sales specialists and LykAI concierge match you with relevant UAE properties.
        </p>
      </div>

      {/* Completion Indicator */}
      <div className="bg-[#181615] border border-amber-900/30 rounded-2xl p-5 shadow-lg flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-serif text-white">Profile Readiness</span>
            <span className="text-xs px-2 py-0.5 rounded-full bg-amber-950/80 border border-amber-800/40 text-amber-400 font-bold">
              {completion.percentage}% Complete
            </span>
          </div>
          <p className="text-xs text-stone-400">
            {completion.missing_fields?.length > 0
              ? `Missing fields: ${completion.missing_fields.map((f) => f.label).join(', ')}`
              : 'Your profile is fully complete. You will receive priority viewing slots and personalized recommendations.'}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setPwModalOpen(true)}
          className="text-xs px-3.5 py-2 rounded-lg border border-stone-700 bg-stone-900 hover:text-white text-stone-300 font-medium transition-colors shrink-0"
        >
          Change Password 🔑
        </button>
      </div>

      {successMsg && (
        <div className="p-4 rounded-xl bg-emerald-950/40 border border-emerald-800/50 text-emerald-200 text-xs">
          ✓ {successMsg}
        </div>
      )}

      {errorMsg && (
        <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-800/50 text-rose-200 text-xs">
          ✕ {errorMsg}
        </div>
      )}

      <form onSubmit={handleSave} className="space-y-6">
        {/* Card 1: Personal Details */}
        <div className="bg-[#181615] border border-stone-800/80 rounded-2xl p-6 space-y-4">
          <h2 className="text-base font-serif text-white border-b border-stone-800 pb-3 flex items-center gap-2">
            <span>👤</span> Personal Contact Details
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-stone-300 mb-1">Full Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Amina Al Falasi"
                className="w-full bg-stone-900 border border-stone-700/80 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-stone-300 mb-1">Email Address</label>
              <input
                type="email"
                disabled
                value={profile?.email || ''}
                className="w-full bg-stone-900/50 border border-stone-800 rounded-lg px-3 py-2 text-sm text-stone-500 cursor-not-allowed"
              />
              <span className="text-[10px] text-stone-500 mt-1 block">Account login identifier</span>
            </div>

            <div>
              <label className="block text-xs font-medium text-stone-300 mb-1">Phone Number (with Country Code)</label>
              <input
                type="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="+971 50 123 4567"
                className="w-full bg-stone-900 border border-stone-700/80 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-stone-300 mb-1">Preferred Contact Method</label>
              <select
                value={contactMethod}
                onChange={(e) => setContactMethod(e.target.value)}
                className="w-full bg-stone-900 border border-stone-700/80 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500"
              >
                <option value="email">Email</option>
                <option value="whatsapp">WhatsApp</option>
                <option value="phone">Phone Call</option>
              </select>
            </div>
          </div>
        </div>

        {/* Card 2: Property Preferences */}
        <div className="bg-[#181615] border border-stone-800/80 rounded-2xl p-6 space-y-5">
          <h2 className="text-base font-serif text-white border-b border-stone-800 pb-3 flex items-center gap-2">
            <span>🏡</span> Property Search Criteria
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-stone-300 mb-1">Purpose / Intent</label>
              <div className="grid grid-cols-4 gap-2">
                {[
                  { id: 'buy', label: 'Buy' },
                  { id: 'rent', label: 'Rent' },
                  { id: 'investment', label: 'Invest' },
                  { id: 'self_use', label: 'End-Use' },
                ].map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setPurpose(item.id)}
                    className={`py-2 text-xs rounded-lg border text-center transition-all ${
                      purpose === item.id
                        ? 'bg-amber-950/60 border-amber-600 text-amber-200 font-medium'
                        : 'bg-stone-900 border-stone-800 text-stone-400 hover:text-stone-200'
                    }`}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-stone-300 mb-1">Primary Property Type</label>
              <select
                value={propertyType}
                onChange={(e) => setPropertyType(e.target.value)}
                className="w-full bg-stone-900 border border-stone-700/80 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500"
              >
                {PROPERTY_TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-stone-300 mb-2">
              Preferred Dubai Communities / Locations
            </label>
            <div className="flex flex-wrap gap-2">
              {POPULAR_LOCATIONS.map((loc) => {
                const active = locations.includes(loc)
                return (
                  <button
                    type="button"
                    key={loc}
                    onClick={() => toggleLocation(loc)}
                    className={`px-3 py-1.5 rounded-lg text-xs transition-all ${
                      active
                        ? 'bg-amber-600/30 border border-amber-600 text-amber-300 font-medium shadow-sm'
                        : 'bg-stone-900 border border-stone-800 text-stone-400 hover:text-stone-200'
                    }`}
                  >
                    {active ? '✓ ' : '+ '} {loc}
                  </button>
                )
              })}
            </div>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div>
              <label className="block text-xs font-medium text-stone-300 mb-1">Min Bedrooms</label>
              <input
                type="number"
                min="0"
                max="10"
                value={bedroomsMin}
                onChange={(e) => setBedroomsMin(e.target.value)}
                placeholder="1"
                className="w-full bg-stone-900 border border-stone-700/80 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-stone-300 mb-1">Max Bedrooms</label>
              <input
                type="number"
                min="0"
                max="10"
                value={bedroomsMax}
                onChange={(e) => setBedroomsMax(e.target.value)}
                placeholder="4"
                className="w-full bg-stone-900 border border-stone-700/80 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-stone-300 mb-1">Min Budget (AED)</label>
              <input
                type="number"
                step="50000"
                value={budgetMin}
                onChange={(e) => setBudgetMin(e.target.value)}
                placeholder="1,500,000"
                className="w-full bg-stone-900 border border-stone-700/80 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-stone-300 mb-1">Max Budget (AED)</label>
              <input
                type="number"
                step="50000"
                value={budgetMax}
                onChange={(e) => setBudgetMax(e.target.value)}
                placeholder="5,000,000"
                className="w-full bg-stone-900 border border-stone-700/80 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500"
              />
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 pt-2">
          <button
            type="submit"
            disabled={saving}
            className="px-6 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-amber-600 to-amber-500 text-black hover:from-amber-500 hover:to-amber-400 transition-all shadow-lg shadow-amber-950/50 disabled:opacity-50"
          >
            {saving ? 'Saving Changes...' : 'Save Profile & Preferences'}
          </button>
        </div>
      </form>

      {/* Password Modal */}
      {pwModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="bg-[#181615] border border-stone-800 rounded-2xl w-full max-w-md p-6 text-stone-200 shadow-2xl">
            <div className="flex items-center justify-between border-b border-stone-800 pb-3 mb-4">
              <h3 className="text-base font-serif text-white">Change Account Password</h3>
              <button onClick={() => setPwModalOpen(false)} className="text-stone-400 hover:text-white">✕</button>
            </div>

            {pwSuccess && (
              <div className="mb-4 p-3 rounded-lg bg-emerald-950/40 border border-emerald-800 text-emerald-200 text-xs">
                {pwSuccess}
              </div>
            )}
            {pwError && (
              <div className="mb-4 p-3 rounded-lg bg-rose-950/40 border border-rose-800 text-rose-200 text-xs">
                {pwError}
              </div>
            )}

            <form onSubmit={handleChangePassword} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-stone-300 mb-1">Current Password</label>
                <input
                  type="password"
                  required
                  value={currentPw}
                  onChange={(e) => setCurrentPw(e.target.value)}
                  className="w-full bg-stone-900 border border-stone-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-stone-300 mb-1">New Password (min 6 chars)</label>
                <input
                  type="password"
                  required
                  minLength={6}
                  value={newPw}
                  onChange={(e) => setNewPw(e.target.value)}
                  className="w-full bg-stone-900 border border-stone-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-stone-300 mb-1">Confirm New Password</label>
                <input
                  type="password"
                  required
                  minLength={6}
                  value={confirmPw}
                  onChange={(e) => setConfirmPw(e.target.value)}
                  className="w-full bg-stone-900 border border-stone-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-amber-500"
                />
              </div>

              <div className="pt-2 flex items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setPwModalOpen(false)}
                  disabled={pwSubmitting}
                  className="px-4 py-2 rounded-lg text-xs font-medium text-stone-300 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={pwSubmitting}
                  className="px-5 py-2 rounded-lg text-xs font-semibold bg-amber-600 text-black hover:bg-amber-500 disabled:opacity-50"
                >
                  {pwSubmitting ? 'Updating...' : 'Update Password'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

