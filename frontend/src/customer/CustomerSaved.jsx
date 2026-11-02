import React, { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../api.js'
import ViewingRequestModal from './ViewingRequestModal.jsx'
import PropertyCard from '../components/ui/PropertyCard.jsx'

export default function CustomerSaved() {
  const navigate = useNavigate()
  const [saved, setSaved] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedPropForViewing, setSelectedPropForViewing] = useState(null)

  const loadSaved = () => {
    setLoading(true)
    api.savedProperties()
      .then((res) => setSaved(res.results || []))
      .catch((err) => setError(err.message || 'Failed to load saved properties'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadSaved()
  }, [])

  const handleUnsave = async (prop) => {
    try {
      const pid = prop.property_id || prop.id
      const source = prop.source || 'record'
      await api.unsaveProperty(pid, source)
      setSaved((prev) => prev.filter((p) => (p.property_id || p.id) !== pid))
    } catch (err) {
      alert(err.message || 'Failed to remove saved property')
    }
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <span className="text-xs uppercase tracking-widest text-amber-500 font-semibold">
            Shortlist Portfolio
          </span>
          <h1 className="text-2xl sm:text-3xl font-serif text-white mt-1">
            Saved Properties ({saved.length})
          </h1>
          <p className="text-xs sm:text-sm text-stone-400 mt-1">
            Review your bookmarked residences or request an exclusive private viewing directly.
          </p>
        </div>

        <Link
          to="/properties"
          className="px-4 py-2 rounded-xl text-xs font-semibold bg-gradient-to-r from-amber-600 to-amber-500 text-black hover:from-amber-500 hover:to-amber-400 transition-all shadow-md shadow-amber-950/40 text-center shrink-0"
        >
          Explore More Listings
        </Link>
      </div>

      {loading ? (
        <div className="py-12 text-center text-stone-400 text-sm">
          <div className="w-8 h-8 border-2 border-amber-600/40 border-t-amber-500 rounded-full animate-spin mx-auto mb-3" />
          Loading your shortlist...
        </div>
      ) : error ? (
        <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-800 text-rose-200 text-xs">
          ✕ {error}
        </div>
      ) : saved.length === 0 ? (
        <div className="bg-[#181615] border border-stone-800 rounded-2xl p-12 text-center text-stone-400">
          <span className="text-4xl block mb-2 opacity-50">♥</span>
          <h3 className="text-sm font-medium text-white">Your Shortlist is Empty</h3>
          <p className="text-xs text-stone-500 mt-1 max-w-sm mx-auto">
            Browse our Dubai luxury portfolio or ask LykAI to find properties tailored to your taste.
          </p>
          <div className="mt-4 flex items-center justify-center gap-3">
            <Link
              to="/properties"
              className="px-4 py-2 rounded-lg text-xs font-semibold bg-stone-800 hover:bg-stone-700 text-white"
            >
              Browse Properties
            </Link>
            <Link
              to="/chat"
              className="px-4 py-2 rounded-lg text-xs font-semibold bg-amber-600 text-black hover:bg-amber-500"
            >
              Talk to LykAI
            </Link>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {saved.map((p) => {
            const pid = p.property_id || p.id
            const isRec = p.source === 'record'
            const detailUrl = isRec ? `/properties/${pid}` : `/property/${pid}`

            return (
              <PropertyCard
                key={`${p.source || 'record'}-${pid}`}
                property={p}
                variant="saved"
                onSelect={() => navigate(detailUrl)}
                badge={
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      handleUnsave(p)
                    }}
                    className="w-7 h-7 rounded-full bg-black/60 text-stone-200 hover:text-rose-400 flex items-center justify-center text-sm transition-colors"
                    title="Remove from saved"
                  >
                    ♥
                  </button>
                }
                actions={
                  <div style={{ display: 'flex', gap: 8, width: '100%', marginTop: 4 }}>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        setSelectedPropForViewing(p)
                      }}
                      className="flex-1 py-2 text-xs font-semibold rounded-lg bg-gradient-to-r from-amber-600 to-amber-500 text-black hover:from-amber-500 hover:to-amber-400 transition-all shadow-sm"
                    >
                      Request Viewing
                    </button>
                    <Link
                      to={detailUrl}
                      onClick={(e) => e.stopPropagation()}
                      className="px-3 py-2 text-xs rounded-lg border border-slate-300 bg-slate-100 text-slate-700 hover:text-slate-900 transition-colors"
                    >
                      Details
                    </Link>
                  </div>
                }
              />
            )
          })}
        </div>
      )}

      {/* Viewing Request Modal */}
      {selectedPropForViewing && (
        <ViewingRequestModal
          property={selectedPropForViewing}
          isOpen={true}
          onClose={() => setSelectedPropForViewing(null)}
          onSuccess={() => {
            navigate('/portal/appointments')
          }}
        />
      )}
    </div>
  )
}

