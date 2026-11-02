import React, { useState } from 'react'
import api from '../api.js'

export default function MustChangePasswordModal({ agent, onPasswordChanged }) {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  if (!agent?.must_change_password) {
    return null
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setSuccess('')

    if (!currentPassword) {
      setError('Please enter your current temporary password.')
      return
    }
    if (newPassword.length < 8) {
      setError('New password must be at least 8 characters long.')
      return
    }
    if (newPassword === currentPassword) {
      setError('New password must be different from current password.')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('New passwords do not match.')
      return
    }

    setBusy(true)
    try {
      await api.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      })
      setSuccess('Password updated successfully. Unlocking workspace...')
      setTimeout(() => {
        if (onPasswordChanged) {
          onPasswordChanged()
        } else {
          window.location.reload()
        }
      }, 1200)
    } catch (err) {
      setError(err.message || 'Failed to change password. Please verify your current password.')
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
        background: 'rgba(15, 23, 42, 0.85)',
        backdropFilter: 'blur(8px)',
        zIndex: 999999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 20,
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: 480,
          background: '#ffffff',
          borderRadius: 16,
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.35)',
          overflow: 'hidden',
          border: '1px solid #e2e8f0',
        }}
      >
        <div
          style={{
            background: 'linear-gradient(135deg, #4a0e2e 0%, #2b081b 100%)',
            padding: '24px 28px',
            color: '#fff',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
            <span style={{ fontSize: 22 }}>🔒</span>
            <span
              style={{
                fontSize: 12,
                fontWeight: 700,
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                color: '#d4af37',
              }}
            >
              Security Policy Required
            </span>
          </div>
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: '#fff' }}>
            Set Your New Password
          </h2>
          <p style={{ margin: '6px 0 0', fontSize: 13, color: '#f3e8f4', opacity: 0.9 }}>
            Your account credentials were created or reset by administration. A personal password update is mandatory to continue.
          </p>
        </div>

        <form onSubmit={handleSubmit} style={{ padding: '24px 28px' }}>
          {error && (
            <div
              style={{
                padding: '10px 14px',
                background: '#fef2f2',
                border: '1px solid #fecaca',
                borderRadius: 8,
                color: '#dc2626',
                fontSize: 13,
                marginBottom: 16,
              }}
            >
              ⚠️ {error}
            </div>
          )}

          {success && (
            <div
              style={{
                padding: '10px 14px',
                background: '#f0fdf4',
                border: '1px solid #bbf7d0',
                borderRadius: 8,
                color: '#16a34a',
                fontSize: 13,
                marginBottom: 16,
              }}
            >
              ✓ {success}
            </div>
          )}

          <div style={{ marginBottom: 16 }}>
            <label
              style={{
                display: 'block',
                fontSize: 12,
                fontWeight: 600,
                color: '#334155',
                marginBottom: 6,
              }}
            >
              Current / Temporary Password *
            </label>
            <input
              type="password"
              className="ax-input"
              style={{ width: '100%', boxSizing: 'border-box' }}
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              placeholder="Enter current password"
              required
              autoFocus
            />
          </div>

          <div style={{ marginBottom: 16 }}>
            <label
              style={{
                display: 'block',
                fontSize: 12,
                fontWeight: 600,
                color: '#334155',
                marginBottom: 6,
              }}
            >
              New Secure Password *
            </label>
            <input
              type="password"
              className="ax-input"
              style={{ width: '100%', boxSizing: 'border-box' }}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="Minimum 8 characters"
              required
              minLength={8}
            />
            <span style={{ fontSize: 11, color: '#64748b', marginTop: 4, display: 'block' }}>
              Must be at least 8 characters long and different from current password.
            </span>
          </div>

          <div style={{ marginBottom: 20 }}>
            <label
              style={{
                display: 'block',
                fontSize: 12,
                fontWeight: 600,
                color: '#334155',
                marginBottom: 6,
              }}
            >
              Confirm New Password *
            </label>
            <input
              type="password"
              className="ax-input"
              style={{ width: '100%', boxSizing: 'border-box' }}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Re-type new password"
              required
              minLength={8}
            />
          </div>

          <button
            type="submit"
            disabled={busy}
            style={{
              width: '100%',
              padding: '12px 16px',
              borderRadius: 8,
              background: 'linear-gradient(135deg, #4a0e2e 0%, #701a45 100%)',
              color: '#fff',
              border: 'none',
              fontWeight: 700,
              fontSize: 14,
              cursor: busy ? 'not-allowed' : 'pointer',
              opacity: busy ? 0.7 : 1,
              boxShadow: '0 4px 6px -1px rgba(74, 14, 46, 0.25)',
            }}
          >
            {busy ? 'Updating Password...' : 'Save Password & Access CRM'}
          </button>
        </form>
      </div>
    </div>
  )
}

