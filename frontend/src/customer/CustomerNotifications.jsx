import React, { useState, useEffect } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import api from '../api.js'

export default function CustomerNotifications() {
  const { setUnreadCount } = useOutletContext()
  const [notifications, setNotifications] = useState([])
  const [unreadCount, setLocalUnreadCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadNotifications = () => {
    setLoading(true)
    api.customerNotifications()
      .then((res) => {
        setNotifications(res.results || [])
        setLocalUnreadCount(res.unread_count || 0)
        if (setUnreadCount) setUnreadCount(res.unread_count || 0)
      })
      .catch((err) => setError(err.message || 'Failed to load notifications'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadNotifications()
  }, [])

  const markRead = async (id) => {
    try {
      await api.customerMarkNotificationRead(id)
      setNotifications((prev) =>
        prev.map((n) => (n.id === id ? { ...n, is_read: true } : n))
      )
      setLocalUnreadCount((c) => Math.max(0, c - 1))
      if (setUnreadCount) setUnreadCount((c) => Math.max(0, c - 1))
    } catch {
      // ignore
    }
  }

  const markAllRead = async () => {
    try {
      await api.customerMarkAllNotificationsRead()
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })))
      setLocalUnreadCount(0)
      if (setUnreadCount) setUnreadCount(0)
    } catch {
      // ignore
    }
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6 animate-fade-in">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <span className="text-xs uppercase tracking-widest text-amber-500 font-semibold">
            Alerts & Activity
          </span>
          <h1 className="text-2xl sm:text-3xl font-serif text-white mt-1">
            Notification Center
          </h1>
          <p className="text-xs sm:text-sm text-stone-400 mt-1">
            Live updates on your viewing confirmations, reschedule requests, and concierge messages.
          </p>
        </div>

        {unreadCount > 0 && (
          <button
            onClick={markAllRead}
            className="text-xs px-3.5 py-1.5 rounded-lg border border-stone-700 bg-stone-900 hover:text-white text-stone-300 font-medium transition-colors shrink-0"
          >
            Mark All as Read ({unreadCount})
          </button>
        )}
      </div>

      {loading ? (
        <div className="py-12 text-center text-stone-400 text-sm">
          <div className="w-8 h-8 border-2 border-amber-600/40 border-t-amber-500 rounded-full animate-spin mx-auto mb-3" />
          Loading notifications...
        </div>
      ) : error ? (
        <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-800 text-rose-200 text-xs">
          ✕ {error}
        </div>
      ) : notifications.length === 0 ? (
        <div className="bg-[#181615] border border-stone-800 rounded-2xl p-12 text-center text-stone-400">
          <span className="text-4xl block mb-2 opacity-50">🔔</span>
          <h3 className="text-sm font-medium text-white">No Notifications</h3>
          <p className="text-xs text-stone-500 mt-1">You are all caught up!</p>
        </div>
      ) : (
        <div className="space-y-3">
          {notifications.map((n) => (
            <div
              key={n.id}
              onClick={() => !n.is_read && markRead(n.id)}
              className={`p-4 rounded-xl border transition-all ${
                n.is_read
                  ? 'bg-[#181615] border-stone-800/80 text-stone-400'
                  : 'bg-gradient-to-r from-[#1c1816] to-[#181615] border-amber-800/60 text-stone-200 shadow-md shadow-amber-950/20 cursor-pointer'
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-3">
                  <div
                    className={`w-8 h-8 rounded-lg flex items-center justify-center text-sm shrink-0 mt-0.5 ${
                      n.category === 'viewing'
                        ? 'bg-amber-950/80 text-amber-400 border border-amber-800/50'
                        : 'bg-stone-800 text-stone-300 border border-stone-700'
                    }`}
                  >
                    {n.category === 'viewing' ? '📅' : '🔔'}
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h4 className="text-sm font-medium text-white">{n.title}</h4>
                      {!n.is_read && (
                        <span className="w-2 h-2 rounded-full bg-amber-400" />
                      )}
                    </div>
                    <p className="text-xs mt-1 leading-relaxed text-stone-300">
                      {n.message}
                    </p>
                    <span className="text-[10px] text-stone-500 mt-2 block">
                      {n.created_at ? new Date(n.created_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : ''}
                    </span>
                  </div>
                </div>

                {n.action_url && (
                  <Link
                    to={n.action_url}
                    className="text-xs text-amber-400 hover:text-amber-300 font-medium shrink-0 pt-0.5"
                  >
                    View →
                  </Link>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

