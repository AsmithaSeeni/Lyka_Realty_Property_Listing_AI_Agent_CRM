import React, { useState, useEffect } from 'react'
import api from '../api.js'

export default function CustomerMessages() {
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [subject, setSubject] = useState('')
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)

  const loadMessages = () => {
    setLoading(true)
    api.customerCommunications()
      .then((res) => setMessages(res.results || []))
      .catch((err) => setError(err.message || 'Failed to load messages'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadMessages()
  }, [])

  const handleSend = async (e) => {
    e.preventDefault()
    if (!text.trim()) return

    setSending(true)
    try {
      await api.customerSendCommunication({
        message: text.trim(),
        subject: subject.trim() || undefined,
      })
      setText('')
      setSubject('')
      loadMessages()
    } catch (err) {
      alert(err.message || 'Failed to send message')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <span className="text-xs uppercase tracking-widest text-amber-500 font-semibold">
            Concierge Communication
          </span>
          <h1 className="text-2xl sm:text-3xl font-serif text-white mt-1">
            Client & Specialist Dialogue
          </h1>
          <p className="text-xs sm:text-sm text-stone-400 mt-1">
            Direct communication channel with your assigned Lyka Realty sales specialist and advisory team.
          </p>
        </div>
        <button
          onClick={loadMessages}
          className="text-xs px-3 py-1.5 rounded-lg border border-stone-800 bg-stone-900 text-stone-300 hover:text-white"
        >
          ↻ Refresh
        </button>
      </div>

      {/* Message Thread */}
      <div className="bg-[#181615] border border-stone-800/80 rounded-2xl p-6 min-h-[400px] flex flex-col justify-between shadow-xl">
        <div className="space-y-4 mb-6 overflow-y-auto max-h-[500px] pr-2">
          {loading ? (
            <div className="py-12 text-center text-stone-400 text-xs">
              <div className="w-6 h-6 border-2 border-amber-600/40 border-t-amber-500 rounded-full animate-spin mx-auto mb-2" />
              Loading conversation thread...
            </div>
          ) : error ? (
            <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-800 text-rose-200 text-xs text-center">
              {error}
            </div>
          ) : messages.length === 0 ? (
            <div className="py-16 text-center text-stone-400">
              <span className="text-3xl block mb-2 opacity-50">💬</span>
              <h3 className="text-sm font-medium text-white">No Messages Yet</h3>
              <p className="text-xs text-stone-500 mt-1 max-w-sm mx-auto">
                Send a message to your assigned advisor below to inquire about listings, off-plan projects, or financing.
              </p>
            </div>
          ) : (
            messages.map((m) => {
              const isCust = m.sender_type === 'customer'
              return (
                <div
                  key={m.id}
                  className={`flex flex-col ${isCust ? 'items-end' : 'items-start'}`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[11px] font-medium text-stone-400">
                      {m.sender_name || (isCust ? 'You' : 'Lyka Advisor')}
                    </span>
                    <span className="text-[10px] text-stone-500">
                      {m.created_at ? new Date(m.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
                    </span>
                  </div>

                  <div
                    className={`p-4 rounded-2xl max-w-lg text-xs leading-relaxed shadow-md ${
                      isCust
                        ? 'bg-gradient-to-r from-amber-950/80 to-amber-900/60 border border-amber-800/60 text-stone-100 rounded-tr-none'
                        : 'bg-stone-900/90 border border-stone-800 text-stone-200 rounded-tl-none'
                    }`}
                  >
                    {m.subject && (
                      <div className="font-semibold text-white mb-1 pb-1 border-b border-stone-700/50">
                        {m.subject}
                      </div>
                    )}
                    <p className="whitespace-pre-wrap">{m.message}</p>
                  </div>
                </div>
              )
            })
          )}
        </div>

        {/* Composer */}
        <form onSubmit={handleSend} className="border-t border-stone-800/80 pt-4 space-y-3">
          <input
            type="text"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="Subject (optional)"
            className="w-full bg-stone-900 border border-stone-700/80 rounded-lg px-3 py-2 text-xs text-white placeholder-stone-500 focus:outline-none focus:border-amber-500"
          />

          <div className="flex items-end gap-2">
            <textarea
              rows={2}
              required
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Type your message to your property specialist..."
              className="flex-1 bg-stone-900 border border-stone-700/80 rounded-lg p-3 text-xs text-white placeholder-stone-500 focus:outline-none focus:border-amber-500 resize-none"
            />
            <button
              type="submit"
              disabled={sending || !text.trim()}
              className="px-5 py-3 rounded-lg text-xs font-semibold bg-gradient-to-r from-amber-600 to-amber-500 text-black hover:from-amber-500 hover:to-amber-400 transition-all shadow-md shadow-amber-950/50 disabled:opacity-50 shrink-0"
            >
              {sending ? 'Sending...' : 'Send Message'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

