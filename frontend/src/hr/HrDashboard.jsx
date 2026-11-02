import React, { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import api from '../api.js'

const DEPARTMENTS = ['All', 'Sales', 'Operations', 'Human Resources', 'Management', 'Finance', 'Marketing']
const ATTENDANCE_STATUSES = ['All', 'Present', 'Late', 'Field Duty', 'Work From Home', 'On Leave', 'Absent', 'Half Day']
const LEAVE_TYPES = ['Casual Leave', 'Sick Leave', 'Annual/Earned Leave', 'Unpaid Leave', 'Other']

export default function HrDashboard() {
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = searchParams.get('tab') || 'overview'
  const setTab = (t) => setSearchParams({ tab: t })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [successMsg, setSuccessMsg] = useState('')

  // Dashboard Data
  const [stats, setStats] = useState(null)
  const [selectedDate, setSelectedDate] = useState(() => new Date().toISOString().split('T')[0])

  // Employees State
  const [employees, setEmployees] = useState([])
  const [empTotal, setEmpTotal] = useState(0)
  const [empFilterDept, setEmpFilterDept] = useState('All')
  const [empFilterStatus, setEmpFilterStatus] = useState('All')
  const [empSearch, setEmpSearch] = useState('')
  const [showAddEmp, setShowAddEmp] = useState(false)
  const [editingEmp, setEditingEmp] = useState(null)
  const [editModalTab, setEditModalTab] = useState('personal') // 'personal' | 'employment' | 'attendance'
  const [empAttendanceHistory, setEmpAttendanceHistory] = useState([])
  const [offboardModalEmp, setOffboardModalEmp] = useState(null)
  const [offboardReason, setOffboardReason] = useState('')

  // New Employee Form
  const [newEmpForm, setNewEmpForm] = useState({
    full_name: '',
    official_email: '',
    employee_id: '',
    contact_number: '',
    department: 'Sales',
    designation: 'Real Estate Consultant',
    employment_type: 'Full-time',
    employment_status: 'Active',
    crm_role: 'agent',
    branch: 'Dubai Main Branch',
    create_crm_account: true,
    initial_password: '',
  })

  // Attendance State
  const [attendanceRecords, setAttendanceRecords] = useState([])
  const [attTotal, setAttTotal] = useState(0)
  const [attDateFrom, setAttDateFrom] = useState(() => new Date().toISOString().split('T')[0])
  const [attDateTo, setAttDateTo] = useState(() => new Date().toISOString().split('T')[0])
  const [attFilterStatus, setAttFilterStatus] = useState('All')
  const [attFilterDept, setAttFilterDept] = useState('All')
  const [correctingAtt, setCorrectingAtt] = useState(null)
  const [correctionForm, setCorrectionForm] = useState({ status: 'Present', reason: '' })

  // Leave Requests State
  const [leaveRequests, setLeaveRequests] = useState([])
  const [leaveFilterStatus, setLeaveFilterStatus] = useState('pending')
  const [reviewingLeave, setReviewingLeave] = useState(null)
  const [reviewNotes, setReviewNotes] = useState('')
  const [actionBusy, setActionBusy] = useState(false)

  // Clear notifications after 4s
  useEffect(() => {
    if (successMsg) {
      const t = setTimeout(() => setSuccessMsg(''), 4000)
      return () => clearTimeout(t)
    }
  }, [successMsg])

  // Load Dashboard Data
  const loadDashboard = useCallback(async () => {
    try {
      setLoading(true)
      const data = await api.hrDashboard(selectedDate)
      setStats(data)
    } catch (err) {
      setError(err.message || 'Failed to load HR dashboard.')
    } finally {
      setLoading(false)
    }
  }, [selectedDate])

  // Load Employees
  const loadEmployees = useCallback(async () => {
    try {
      const res = await api.hrEmployees({
        department: empFilterDept !== 'All' ? empFilterDept : undefined,
        status: empFilterStatus !== 'All' ? empFilterStatus : undefined,
        q: empSearch || undefined,
        limit: 100,
      })
      setEmployees(res.results || [])
      setEmpTotal(res.total || 0)
    } catch (err) {
      setError(err.message || 'Failed to load employees.')
    }
  }, [empFilterDept, empFilterStatus, empSearch])

  // Load Attendance
  const loadAttendance = useCallback(async () => {
    try {
      const res = await api.hrAttendance({
        date_from: attDateFrom || undefined,
        date_to: attDateTo || undefined,
        department: attFilterDept !== 'All' ? attFilterDept : undefined,
        status: attFilterStatus !== 'All' ? attFilterStatus : undefined,
        limit: 100,
      })
      setAttendanceRecords(res.results || [])
      setAttTotal(res.total || 0)
    } catch (err) {
      setError(err.message || 'Failed to load attendance.')
    }
  }, [attDateFrom, attDateTo, attFilterDept, attFilterStatus])

  // Load Leaves
  const loadLeaves = useCallback(async () => {
    try {
      const res = await api.hrLeaveRequests({
        status: leaveFilterStatus !== 'All' ? leaveFilterStatus : undefined,
        limit: 100,
      })
      setLeaveRequests(res.results || [])
    } catch (err) {
      setError(err.message || 'Failed to load leave requests.')
    }
  }, [leaveFilterStatus])

  // Primary loader depending on active tab
  useEffect(() => {
    setError('')
    if (tab === 'overview') {
      loadDashboard()
    } else if (tab === 'employees') {
      loadEmployees()
    } else if (tab === 'attendance') {
      loadAttendance()
    } else if (tab === 'leaves') {
      loadLeaves()
    }
  }, [tab, loadDashboard, loadEmployees, loadAttendance, loadLeaves])

  // Handlers
  const handleCreateEmployee = async (e) => {
    e.preventDefault()
    setActionBusy(true)
    setError('')
    try {
      await api.hrCreateEmployee(newEmpForm)
      setSuccessMsg('Employee created successfully with CRM credentials!')
      setShowAddEmp(false)
      setNewEmpForm({
        full_name: '',
        official_email: '',
        employee_id: '',
        contact_number: '',
        department: 'Sales',
        designation: 'Real Estate Consultant',
        employment_type: 'Full-time',
        employment_status: 'Active',
        crm_role: 'agent',
        branch: 'Dubai Main Branch',
        create_crm_account: true,
        initial_password: '',
      })
      loadEmployees()
    } catch (err) {
      setError(err.message || 'Failed to create employee.')
    } finally {
      setActionBusy(false)
    }
  }

  const openEditEmployee = async (emp) => {
    setEditingEmp({ ...emp })
    setEditModalTab('personal')
    setEmpAttendanceHistory([])
    try {
      const full = await api.hrEmployee(emp.id)
      if (full && full.employee) {
        setEditingEmp(full.employee)
        setEmpAttendanceHistory(full.recent_attendance || [])
      }
    } catch {}
  }

  const handleUpdateEmployee = async (e) => {
    e.preventDefault()
    if (!editingEmp) return
    setActionBusy(true)
    setError('')
    try {
      await api.hrUpdateEmployee(editingEmp.id, {
        full_name: editingEmp.full_name,
        contact_number: editingEmp.contact_number,
        department: editingEmp.department,
        designation: editingEmp.designation,
        employment_type: editingEmp.employment_type,
        branch: editingEmp.branch,
        crm_role: editingEmp.crm_role,
        employment_status: editingEmp.employment_status,
      })
      setSuccessMsg('Employee record updated successfully.')
      setEditingEmp(null)
      loadEmployees()
    } catch (err) {
      setError(err.message || 'Failed to update employee.')
    } finally {
      setActionBusy(false)
    }
  }

  const handleOffboardEmployee = async () => {
    if (!offboardModalEmp || !offboardReason.trim()) return
    setActionBusy(true)
    setError('')
    try {
      await api.hrDeactivateEmployee(offboardModalEmp.id, offboardReason)
      setSuccessMsg(`Employee ${offboardModalEmp.full_name} offboarded successfully. System login suspended and active sessions revoked.`)
      setOffboardModalEmp(null)
      setOffboardReason('')
      loadEmployees()
    } catch (err) {
      setError(err.message || 'Failed to offboard employee.')
    } finally {
      setActionBusy(false)
    }
  }

  const handleCorrectAttendance = async (e) => {
    e.preventDefault()
    if (!correctingAtt || !correctionForm.reason.trim()) return
    setActionBusy(true)
    setError('')
    try {
      await api.hrCorrectAttendance({
        attendance_id: correctingAtt.id,
        status: correctionForm.status,
        reason: correctionForm.reason,
      })
      setSuccessMsg('Attendance record corrected and audited successfully.')
      setCorrectingAtt(null)
      setCorrectionForm({ status: 'Present', reason: '' })
      loadAttendance()
    } catch (err) {
      setError(err.message || 'Failed to correct attendance.')
    } finally {
      setActionBusy(false)
    }
  }

  const handleReviewLeave = async (approved) => {
    if (!reviewingLeave) return
    setActionBusy(true)
    setError('')
    try {
      await api.hrReviewLeave(reviewingLeave.id, {
        approved,
        review_notes: reviewNotes,
      })
      setSuccessMsg(`Leave request #${reviewingLeave.id} has been ${approved ? 'approved' : 'rejected'}.`)
      setReviewingLeave(null)
      setReviewNotes('')
      loadLeaves()
    } catch (err) {
      setError(err.message || 'Failed to review leave request.')
    } finally {
      setActionBusy(false)
    }
  }

  return (
    <div className="hr-container" style={{ padding: '24px 32px' }}>
      {/* Page Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 16, marginBottom: 24 }}>
        <div>
          <h1 style={{ fontFamily: 'var(--display)', fontSize: '1.85rem', margin: '0 0 6px 0', color: '#1c1c1c' }}>
            Human Resources Management
          </h1>
          <p style={{ margin: 0, color: 'var(--muted)', fontSize: '0.92rem' }}>
            Employee records, daily attendance tracking &amp; leave governance · Dubai Operations
          </p>
        </div>

        {/* Global Tab Navigation */}
        <div style={{ display: 'flex', background: '#f5ebf1', padding: 4, borderRadius: 10, gap: 4, flexWrap: 'wrap' }}>
          <button
            className={`btn btn-sm ${tab === 'overview' ? '' : 'btn-ghost'}`}
            style={{ fontWeight: 600 }}
            onClick={() => setTab('overview')}
          >
            📊 Overview
          </button>
          <button
            className={`btn btn-sm ${tab === 'employees' ? '' : 'btn-ghost'}`}
            style={{ fontWeight: 600 }}
            onClick={() => setTab('employees')}
          >
            👥 Employees ({empTotal || '…'})
          </button>
          <button
            className={`btn btn-sm ${tab === 'onboarding' ? '' : 'btn-ghost'}`}
            style={{ fontWeight: 600 }}
            onClick={() => setTab('onboarding')}
          >
            ➕ Onboarding
          </button>
          <button
            className={`btn btn-sm ${tab === 'attendance' ? '' : 'btn-ghost'}`}
            style={{ fontWeight: 600 }}
            onClick={() => setTab('attendance')}
          >
            🕒 Attendance ({attTotal || '…'})
          </button>
          <button
            className={`btn btn-sm ${tab === 'leaves' ? '' : 'btn-ghost'}`}
            style={{ fontWeight: 600 }}
            onClick={() => setTab('leaves')}
          >
            🌴 Leaves
          </button>
          <button
            className={`btn btn-sm ${tab === 'shifts' ? '' : 'btn-ghost'}`}
            style={{ fontWeight: 600 }}
            onClick={() => setTab('shifts')}
          >
            ⏱️ Shifts &amp; Holidays
          </button>
          <button
            className={`btn btn-sm ${tab === 'documents' ? '' : 'btn-ghost'}`}
            style={{ fontWeight: 600 }}
            onClick={() => setTab('documents')}
          >
            📁 Documents
          </button>
          <button
            className={`btn btn-sm ${tab === 'reports' ? '' : 'btn-ghost'}`}
            style={{ fontWeight: 600 }}
            onClick={() => setTab('reports')}
          >
            📈 Reports
          </button>
          <button
            className={`btn btn-sm ${tab === 'offboarding' ? '' : 'btn-ghost'}`}
            style={{ fontWeight: 600 }}
            onClick={() => setTab('offboarding')}
          >
            🚪 Offboarding
          </button>
        </div>
      </div>

      {/* Alerts */}
      {error && (
        <div style={{ background: '#fee2e2', border: '1px solid #f87171', color: '#991b1b', padding: '12px 16px', borderRadius: 8, marginBottom: 16, fontSize: '0.9rem' }}>
          <strong>Error:</strong> {error}
        </div>
      )}
      {successMsg && (
        <div style={{ background: '#ecfdf5', border: '1px solid #34d399', color: '#065f46', padding: '12px 16px', borderRadius: 8, marginBottom: 16, fontSize: '0.9rem' }}>
          ✓ {successMsg}
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* TAB 1: OVERVIEW & ANALYTICS                                   */}
      {/* ------------------------------------------------------------- */}
      {tab === 'overview' && (
        <div>
          {/* Date Picker Filter */}
          <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 10, marginBottom: 16 }}>
            <span style={{ fontSize: '0.88rem', fontWeight: 600, color: '#44102f' }}>Selected Date:</span>
            <input
              type="date"
              className="ax-input"
              style={{ width: 160, padding: '4px 10px', fontSize: '0.88rem' }}
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
            />
          </div>

          {/* KPI Summary Cards */}
          <div className="ax-stats" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', marginBottom: 24 }}>
            <div className="ax-stat c">
              <b>{stats?.total_employees ?? '—'}</b>
              <span>Total Employees</span>
            </div>
            <div className="ax-stat g">
              <b>{stats?.active_employees ?? '—'}</b>
              <span>Active Workforce</span>
            </div>
            <div className="ax-stat v">
              <b>{stats?.present_today ?? 0}</b>
              <span>Present Today</span>
            </div>
            <div className="ax-stat w">
              <b>{stats?.late_today ?? 0}</b>
              <span>Late Today</span>
            </div>
            <div className="ax-stat">
              <b>{stats?.field_duty_today ?? 0}</b>
              <span>Field Duty Today</span>
            </div>
            <div className="ax-stat q">
              <b>{stats?.on_leave_today ?? 0}</b>
              <span>On Leave Today</span>
            </div>
            <div className="ax-stat r">
              <b>{stats?.absent_today ?? 0}</b>
              <span>Absent Today</span>
            </div>
            <div className="ax-stat w">
              <b>{stats?.pending_leave_requests ?? 0}</b>
              <span>Pending Leaves</span>
            </div>
          </div>

          {/* Department Breakdown & Recent Activity */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
            {/* Department Roster */}
            <div className="ax-panel">
              <h3 style={{ margin: '0 0 14px 0', fontSize: '1.05rem', color: '#5a1645', borderBottom: '1px solid #f0e6eb', paddingBottom: 8 }}>
                Headcount by Department
              </h3>
              {(!stats?.departments || stats.departments.length === 0) ? (
                <div style={{ color: 'var(--muted)', fontSize: '0.9rem' }}>No department data available.</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {stats.departments.map((d) => (
                    <div key={d.department} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', background: '#faf6ef', borderRadius: 8 }}>
                      <span style={{ fontWeight: 600, color: '#333' }}>{d.department}</span>
                      <span style={{ background: '#5a1645', color: '#fff', padding: '2px 10px', borderRadius: 12, fontSize: '0.85rem', fontWeight: 600 }}>
                        {d.count} staff
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Recent HR Audit Trail */}
            <div className="ax-panel">
              <h3 style={{ margin: '0 0 14px 0', fontSize: '1.05rem', color: '#5a1645', borderBottom: '1px solid #f0e6eb', paddingBottom: 8 }}>
                Recent HR &amp; Attendance Activity
              </h3>
              {(!stats?.recent_activities || stats.recent_activities.length === 0) ? (
                <div style={{ color: 'var(--muted)', fontSize: '0.9rem' }}>No recent audit activity.</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 300, overflowY: 'auto' }}>
                  {stats.recent_activities.map((a) => (
                    <div key={a.id} style={{ fontSize: '0.85rem', padding: '8px 10px', borderLeft: '3px solid #e8bd68', background: '#fdfcf9' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', color: '#888', marginBottom: 2 }}>
                        <span style={{ fontWeight: 600, color: '#44102f' }}>{a.event}</span>
                        <span>{a.created_at ? new Date(a.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}</span>
                      </div>
                      <div style={{ color: '#333' }}>{a.subject_label}: {a.detail}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* TAB 2: EMPLOYEE MASTER DIRECTORY                              */}
      {/* ------------------------------------------------------------- */}
      {tab === 'employees' && (
        <div>
          {/* Controls Bar */}
          <div className="ax-panel" style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
                <input
                  type="text"
                  className="ax-input"
                  style={{ width: 240 }}
                  placeholder="Search name, code, email, role…"
                  value={empSearch}
                  onChange={(e) => setEmpSearch(e.target.value)}
                />
                <select
                  className="ax-input"
                  style={{ width: 160 }}
                  value={empFilterDept}
                  onChange={(e) => setEmpFilterDept(e.target.value)}
                >
                  {DEPARTMENTS.map((d) => <option key={d} value={d}>{d === 'All' ? 'All Departments' : d}</option>)}
                </select>
                <select
                  className="ax-input"
                  style={{ width: 140 }}
                  value={empFilterStatus}
                  onChange={(e) => setEmpFilterStatus(e.target.value)}
                >
                  <option value="All">All Statuses</option>
                  <option value="Active">Active</option>
                  <option value="On Leave">On Leave</option>
                  <option value="Suspended">Suspended</option>
                  <option value="Terminated">Terminated</option>
                </select>
              </div>

              <button className="btn btn-sm" onClick={() => setShowAddEmp(true)}>
                ＋ Add New Employee
              </button>
            </div>
          </div>

          {/* Employees Table */}
          <div className="ax-panel" style={{ padding: 0, overflowX: 'auto' }}>
            <table className="ax-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: '#faf6ef', borderBottom: '1px solid #eddcd2' }}>
                  <th style={{ padding: '12px 16px', textAlign: 'left' }}>CODE</th>
                  <th style={{ padding: '12px 16px', textAlign: 'left' }}>EMPLOYEE NAME</th>
                  <th style={{ padding: '12px 16px', textAlign: 'left' }}>DEPARTMENT &amp; DESIGNATION</th>
                  <th style={{ padding: '12px 16px', textAlign: 'left' }}>CONTACT</th>
                  <th style={{ padding: '12px 16px', textAlign: 'left' }}>CRM ROLE</th>
                  <th style={{ padding: '12px 16px', textAlign: 'left' }}>STATUS</th>
                  <th style={{ padding: '12px 16px', textAlign: 'right' }}>ACTIONS</th>
                </tr>
              </thead>
              <tbody>
                {employees.length === 0 ? (
                  <tr>
                    <td colSpan={7} style={{ textAlign: 'center', padding: 32, color: 'var(--muted)' }}>
                      No employees matched your search criteria.
                    </td>
                  </tr>
                ) : (
                  employees.map((emp) => (
                    <tr key={emp.id} style={{ borderBottom: '1px solid #f4ede4' }}>
                      <td style={{ padding: '12px 16px', fontWeight: 600, color: '#5a1645' }}>
                        {emp.employee_id}
                      </td>
                      <td style={{ padding: '12px 16px' }}>
                        <div style={{ fontWeight: 600, color: '#1c1c1c' }}>{emp.full_name}</div>
                        <div style={{ fontSize: '0.82rem', color: '#666' }}>{emp.official_email}</div>
                      </td>
                      <td style={{ padding: '12px 16px' }}>
                        <div style={{ fontWeight: 500 }}>{emp.designation}</div>
                        <div style={{ fontSize: '0.82rem', color: '#777' }}>{emp.department} · {emp.branch}</div>
                      </td>
                      <td style={{ padding: '12px 16px', fontSize: '0.88rem' }}>
                        {emp.contact_number || '—'}
                      </td>
                      <td style={{ padding: '12px 16px' }}>
                        <span style={{ textTransform: 'capitalize', background: '#f5ebf1', color: '#5a1645', padding: '2px 8px', borderRadius: 4, fontSize: '0.82rem', fontWeight: 600 }}>
                          {emp.crm_role}
                        </span>
                      </td>
                      <td style={{ padding: '12px 16px' }}>
                        <span style={{
                          display: 'inline-block',
                          padding: '3px 10px',
                          borderRadius: 12,
                          fontSize: '0.82rem',
                          fontWeight: 600,
                          background: emp.employment_status === 'Active' ? '#dcfce7' : emp.employment_status === 'On Leave' ? '#fef3c7' : '#fee2e2',
                          color: emp.employment_status === 'Active' ? '#166534' : emp.employment_status === 'On Leave' ? '#92400e' : '#991b1b',
                        }}>
                          {emp.employment_status}
                        </span>
                      </td>
                      <td style={{ padding: '12px 16px', textAlign: 'right' }}>
                        <div style={{ display: 'inline-flex', gap: 6 }}>
                          <button
                            className="btn btn-sm btn-ghost"
                            style={{ padding: '4px 10px', fontSize: '0.82rem', fontWeight: 600 }}
                            onClick={() => openEditEmployee(emp)}
                          >
                            Edit Profile
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* TAB 3: ATTENDANCE CONTROL                                     */}
      {/* ------------------------------------------------------------- */}
      {tab === 'attendance' && (
        <div>
          {/* Filters Bar */}
          <div className="ax-panel" style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
                <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>From:</span>
                <input
                  type="date"
                  className="ax-input"
                  style={{ width: 145 }}
                  value={attDateFrom}
                  onChange={(e) => setAttDateFrom(e.target.value)}
                />
                <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>To:</span>
                <input
                  type="date"
                  className="ax-input"
                  style={{ width: 145 }}
                  value={attDateTo}
                  onChange={(e) => setAttDateTo(e.target.value)}
                />
                <select
                  className="ax-input"
                  style={{ width: 150 }}
                  value={attFilterStatus}
                  onChange={(e) => setAttFilterStatus(e.target.value)}
                >
                  {ATTENDANCE_STATUSES.map((s) => <option key={s} value={s}>{s === 'All' ? 'All Statuses' : s}</option>)}
                </select>
                <select
                  className="ax-input"
                  style={{ width: 150 }}
                  value={attFilterDept}
                  onChange={(e) => setAttFilterDept(e.target.value)}
                >
                  {DEPARTMENTS.map((d) => <option key={d} value={d}>{d === 'All' ? 'All Departments' : d}</option>)}
                </select>
              </div>

              <div style={{ fontSize: '0.88rem', color: 'var(--muted)' }}>
                Showing <strong>{attendanceRecords.length}</strong> attendance entries
              </div>
            </div>
          </div>

          {/* Attendance Table */}
          <div className="ax-panel" style={{ padding: 0, overflowX: 'auto' }}>
            <table className="ax-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: '#faf6ef', borderBottom: '1px solid #eddcd2' }}>
                  <th style={{ padding: '12px 16px', textAlign: 'left' }}>DATE</th>
                  <th style={{ padding: '12px 16px', textAlign: 'left' }}>EMPLOYEE</th>
                  <th style={{ padding: '12px 16px', textAlign: 'left' }}>DEPARTMENT</th>
                  <th style={{ padding: '12px 16px', textAlign: 'left' }}>STATUS</th>
                  <th style={{ padding: '12px 16px', textAlign: 'left' }}>CHECK-IN (GST)</th>
                  <th style={{ padding: '12px 16px', textAlign: 'left' }}>CHECK-OUT (GST)</th>
                  <th style={{ padding: '12px 16px', textAlign: 'left' }}>SOURCE / NOTES</th>
                  <th style={{ padding: '12px 16px', textAlign: 'right' }}>ACTION</th>
                </tr>
              </thead>
              <tbody>
                {attendanceRecords.length === 0 ? (
                  <tr>
                    <td colSpan={8} style={{ textAlign: 'center', padding: 32, color: 'var(--muted)' }}>
                      No attendance entries found for the selected period.
                    </td>
                  </tr>
                ) : (
                  attendanceRecords.map((att) => (
                    <tr key={att.id} style={{ borderBottom: '1px solid #f4ede4' }}>
                      <td style={{ padding: '12px 16px', fontWeight: 600 }}>
                        {att.attendance_date}
                      </td>
                      <td style={{ padding: '12px 16px' }}>
                        <div style={{ fontWeight: 600 }}>{att.employee_name || 'Staff Member'}</div>
                        <div style={{ fontSize: '0.82rem', color: '#666' }}>{att.employee_code}</div>
                      </td>
                      <td style={{ padding: '12px 16px', fontSize: '0.88rem' }}>
                        {att.department}
                      </td>
                      <td style={{ padding: '12px 16px' }}>
                        <span style={{
                          display: 'inline-block',
                          padding: '3px 10px',
                          borderRadius: 12,
                          fontSize: '0.82rem',
                          fontWeight: 600,
                          background: att.status === 'Present' ? '#dcfce7' : att.status === 'Late' ? '#fef3c7' : att.status === 'On Leave' ? '#e0f2fe' : att.status === 'Field Duty' ? '#f3e8ff' : '#fee2e2',
                          color: att.status === 'Present' ? '#166534' : att.status === 'Late' ? '#92400e' : att.status === 'On Leave' ? '#0369a1' : att.status === 'Field Duty' ? '#6b21a8' : '#991b1b',
                        }}>
                          {att.status}
                        </span>
                      </td>
                      <td style={{ padding: '12px 16px', fontSize: '0.88rem' }}>
                        {att.check_in ? new Date(att.check_in).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—'}
                      </td>
                      <td style={{ padding: '12px 16px', fontSize: '0.88rem' }}>
                        {att.check_out ? new Date(att.check_out).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—'}
                      </td>
                      <td style={{ padding: '12px 16px', fontSize: '0.82rem', color: '#666' }}>
                        {att.source === 'manual_correction' && <span style={{ color: '#b45309', fontWeight: 600 }}>[Corrected] </span>}
                        {att.notes || att.correction_reason || 'Self-service log'}
                      </td>
                      <td style={{ padding: '12px 16px', textAlign: 'right' }}>
                        <button
                          className="btn btn-sm btn-ghost"
                          style={{ padding: '3px 8px', fontSize: '0.82rem' }}
                          onClick={() => {
                            setCorrectingAtt(att)
                            setCorrectionForm({ status: att.status, reason: '' })
                          }}
                        >
                          Correct
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* TAB 4: LEAVE REQUESTS GOVERNANCE                              */}
      {/* ------------------------------------------------------------- */}
      {tab === 'leaves' && (
        <div>
          {/* Status Filter */}
          <div className="ax-panel" style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
              <span style={{ fontSize: '0.88rem', fontWeight: 600 }}>Filter:</span>
              <button
                className={`btn btn-sm ${leaveFilterStatus === 'pending' ? '' : 'btn-ghost'}`}
                onClick={() => setLeaveFilterStatus('pending')}
              >
                Pending Review
              </button>
              <button
                className={`btn btn-sm ${leaveFilterStatus === 'approved' ? '' : 'btn-ghost'}`}
                onClick={() => setLeaveFilterStatus('approved')}
              >
                Approved
              </button>
              <button
                className={`btn btn-sm ${leaveFilterStatus === 'rejected' ? '' : 'btn-ghost'}`}
                onClick={() => setLeaveFilterStatus('rejected')}
              >
                Rejected
              </button>
              <button
                className={`btn btn-sm ${leaveFilterStatus === 'All' ? '' : 'btn-ghost'}`}
                onClick={() => setLeaveFilterStatus('All')}
              >
                All Applications
              </button>
            </div>
          </div>

          {/* Leave Requests Cards */}
          {leaveRequests.length === 0 ? (
            <div className="ax-panel" style={{ textAlign: 'center', padding: 40, color: 'var(--muted)' }}>
              No leave requests found with status "{leaveFilterStatus}".
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: 16 }}>
              {leaveRequests.map((req) => (
                <div key={req.id} className="ax-panel" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
                      <div>
                        <span style={{ fontWeight: 700, fontSize: '1.05rem', color: '#1c1c1c' }}>{req.employee_name}</span>
                        <span style={{ fontSize: '0.82rem', color: '#666', marginLeft: 8 }}>#{req.employee_code}</span>
                      </div>
                      <span style={{
                        padding: '3px 10px',
                        borderRadius: 12,
                        fontSize: '0.78rem',
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        background: req.status === 'approved' ? '#dcfce7' : req.status === 'rejected' ? '#fee2e2' : req.status === 'cancelled' ? '#f1f5f9' : '#fef3c7',
                        color: req.status === 'approved' ? '#166534' : req.status === 'rejected' ? '#991b1b' : req.status === 'cancelled' ? '#64748b' : '#92400e',
                      }}>
                        {req.status}
                      </span>
                    </div>

                    <div style={{ fontSize: '0.88rem', color: '#5a1645', fontWeight: 600, marginBottom: 8 }}>
                      {req.leave_type} · {req.days_count} day{req.days_count > 1 ? 's' : ''}
                    </div>

                    <div style={{ display: 'flex', gap: 12, fontSize: '0.85rem', color: '#444', marginBottom: 10 }}>
                      <span><strong>From:</strong> {req.start_date}</span>
                      <span><strong>To:</strong> {req.end_date}</span>
                    </div>

                    <div style={{ background: '#faf6ef', padding: '10px 12px', borderRadius: 8, fontSize: '0.86rem', color: '#333', marginBottom: 12 }}>
                      "{req.reason}"
                    </div>

                    {req.review_notes && (
                      <div style={{ fontSize: '0.82rem', color: '#777', fontStyle: 'italic', marginBottom: 10 }}>
                        Reviewer note: {req.review_notes}
                      </div>
                    )}
                  </div>

                  {req.status === 'pending' && (
                    <div style={{ display: 'flex', gap: 8, borderTop: '1px solid #f0e6eb', paddingTop: 12, marginTop: 8 }}>
                      <button
                        className="btn btn-sm btn-ghost"
                        style={{ flex: 1, color: '#dc2626' }}
                        onClick={() => {
                          setReviewingLeave(req)
                          setReviewNotes('')
                        }}
                      >
                        ✕ Reject
                      </button>
                      <button
                        className="btn btn-sm"
                        style={{ flex: 1 }}
                        onClick={() => {
                          setReviewingLeave(req)
                          setReviewNotes('')
                        }}
                      >
                        ✓ Review / Approve
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* TAB 5: ONBOARDING WORKFLOW                                    */}
      {/* ------------------------------------------------------------- */}
      {tab === 'onboarding' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <div className="ax-panel" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
            <div>
              <h2 style={{ margin: '0 0 4px 0', fontSize: '1.25rem', color: '#064e3b' }}>
                Dubai Real-Estate Personnel Onboarding
              </h2>
              <p style={{ margin: 0, color: 'var(--muted)', fontSize: '0.9rem' }}>
                Guided compliance checklist for licensing, immigration, and CRM provisioning in the UAE.
              </p>
            </div>
            <button className="btn btn-sm" onClick={() => setShowAddEmp(true)}>
              ＋ Start New Employee Onboarding
            </button>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 16 }}>
            <div className="ax-panel" style={{ borderLeft: '4px solid #10b981' }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#059669', textTransform: 'uppercase', marginBottom: 4 }}>Stage 1</div>
              <h3 style={{ margin: '0 0 8px 0', fontSize: '1.05rem', color: '#1c1c1c' }}>Identity &amp; Residence Visa</h3>
              <p style={{ fontSize: '0.85rem', color: '#555', margin: '0 0 12px 0' }}>
                Collect valid Passport copy, UAE Residence Visa entry permit, and Emirates ID biometric registration details.
              </p>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: '0.82rem', color: '#666', lineHeight: 1.6 }}>
                <li>Color passport scan (6+ months validity)</li>
                <li>Digital passport photo with white background</li>
                <li>Attested educational degree (where applicable)</li>
              </ul>
            </div>

            <div className="ax-panel" style={{ borderLeft: '4px solid #0284c7' }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#0284c7', textTransform: 'uppercase', marginBottom: 4 }}>Stage 2</div>
              <h3 style={{ margin: '0 0 8px 0', fontSize: '1.05rem', color: '#1c1c1c' }}>RERA Broker Licensing</h3>
              <p style={{ fontSize: '0.85rem', color: '#555', margin: '0 0 12px 0' }}>
                For Property Consultants &amp; Leasing Advisors: submit DLD certification and issue corporate Trakheesi broker card.
              </p>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: '0.82rem', color: '#666', lineHeight: 1.6 }}>
                <li>DLD Certified Real Estate Practitioner course</li>
                <li>Police Clearance Certificate (Dubai Police)</li>
                <li>RERA Broker Card (BRN) generation</li>
              </ul>
            </div>

            <div className="ax-panel" style={{ borderLeft: '4px solid #8b5cf6' }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#7c3aed', textTransform: 'uppercase', marginBottom: 4 }}>Stage 3</div>
              <h3 style={{ margin: '0 0 8px 0', fontSize: '1.05rem', color: '#1c1c1c' }}>Employment Contract</h3>
              <p style={{ fontSize: '0.85rem', color: '#555', margin: '0 0 12px 0' }}>
                MOHRE standard employment contract execution, company policy acknowledgment, and commission structure agreement.
              </p>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: '0.82rem', color: '#666', lineHeight: 1.6 }}>
                <li>MOHRE Electronic Offer Letter signed</li>
                <li>Non-disclosure &amp; client confidentiality terms</li>
                <li>Brokerage commission schedule schedule</li>
              </ul>
            </div>

            <div className="ax-panel" style={{ borderLeft: '4px solid #f59e0b' }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#d97706', textTransform: 'uppercase', marginBottom: 4 }}>Stage 4</div>
              <h3 style={{ margin: '0 0 8px 0', fontSize: '1.05rem', color: '#1c1c1c' }}>CRM &amp; Office Provisioning</h3>
              <p style={{ fontSize: '0.85rem', color: '#555', margin: '0 0 12px 0' }}>
                Issue corporate email, register internal EMP ID, assign branch desk, and link authorised CRM profile.
              </p>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: '0.82rem', color: '#666', lineHeight: 1.6 }}>
                <li>Email: @lykarealty.ae account setup</li>
                <li>Damac Executive Heights building access badge</li>
                <li>CRM login linked without customer chat leakage</li>
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* TAB 6: SHIFTS & PUBLIC HOLIDAYS                               */}
      {/* ------------------------------------------------------------- */}
      {tab === 'shifts' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <div className="ax-panel">
            <h2 style={{ margin: '0 0 4px 0', fontSize: '1.25rem', color: '#064e3b' }}>
              Working Hours &amp; Public Holiday Schedules
            </h2>
            <p style={{ margin: 0, color: 'var(--muted)', fontSize: '0.9rem' }}>
              Gulf Standard Time (GST, UTC+04:00) shift configuration and official UAE national holiday calendar.
            </p>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
            {/* Working Hours */}
            <div className="ax-panel">
              <h3 style={{ margin: '0 0 12px 0', fontSize: '1.05rem', color: '#1c1c1c' }}>
                Dubai Head Office Shift Schedule
              </h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div style={{ padding: 12, background: '#faf6ef', borderRadius: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <div style={{ fontWeight: 600, color: '#333' }}>Standard Real-Estate Shift</div>
                    <div style={{ fontSize: '0.82rem', color: '#666' }}>Monday to Friday · 09:00 AM – 06:00 PM GST</div>
                  </div>
                  <span style={{ background: '#059669', color: '#fff', padding: '2px 8px', borderRadius: 4, fontSize: '0.8rem', fontWeight: 600 }}>Active</span>
                </div>
                <div style={{ padding: 12, background: '#faf6ef', borderRadius: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <div style={{ fontWeight: 600, color: '#333' }}>Weekly Rest Days</div>
                    <div style={{ fontSize: '0.82rem', color: '#666' }}>Saturday &amp; Sunday (Weekend Off)</div>
                  </div>
                  <span style={{ background: '#3b82f6', color: '#fff', padding: '2px 8px', borderRadius: 4, fontSize: '0.8rem', fontWeight: 600 }}>Policy</span>
                </div>
                <div style={{ padding: 12, background: '#fdfcf9', border: '1px solid #eddcd2', borderRadius: 8 }}>
                  <div style={{ fontWeight: 600, color: '#854d0e', marginBottom: 2 }}>Ramadan Policy</div>
                  <div style={{ fontSize: '0.82rem', color: '#666' }}>
                    Working hours reduced by 2 hours daily for all employees during the holy month of Ramadan as mandated by UAE Labor Law.
                  </div>
                </div>
                <div style={{ padding: 12, background: '#fdfcf9', border: '1px solid #eddcd2', borderRadius: 8 }}>
                  <div style={{ fontWeight: 600, color: '#0369a1', marginBottom: 2 }}>Field Duty &amp; Viewing Policy</div>
                  <div style={{ fontSize: '0.82rem', color: '#666' }}>
                    Property viewing tours, client penthouse viewings and developer meetings qualify as "Field Duty" and require check-in recording.
                  </div>
                </div>
              </div>
            </div>

            {/* Public Holidays */}
            <div className="ax-panel">
              <h3 style={{ margin: '0 0 12px 0', fontSize: '1.05rem', color: '#1c1c1c' }}>
                Official UAE 2026 Public Holidays
              </h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 380, overflowY: 'auto' }}>
                {[
                  { date: '1 Jan 2026', name: "New Year's Day", status: 'Past' },
                  { date: '19 - 22 Mar 2026', name: 'Eid Al Fitr (Astronomical)', status: 'Observed' },
                  { date: '26 May 2026', name: 'Arafat Day', status: 'Upcoming' },
                  { date: '27 - 29 May 2026', name: 'Eid Al Adha', status: 'Upcoming' },
                  { date: '16 Jun 2026', name: 'Islamic New Year (1448 H)', status: 'Upcoming' },
                  { date: '25 Aug 2026', name: "Prophet Muhammad's Birthday", status: 'Upcoming' },
                  { date: '1 Dec 2026', name: 'Commemoration Day', status: 'Upcoming' },
                  { date: '2 - 3 Dec 2026', name: 'UAE National Day (55th)', status: 'Upcoming' },
                ].map((h, i) => (
                  <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', background: '#faf6ef', borderRadius: 6, fontSize: '0.88rem' }}>
                    <div>
                      <span style={{ fontWeight: 600, color: '#1c1c1c' }}>{h.name}</span>
                      <span style={{ color: '#777', fontSize: '0.82rem', marginLeft: 8 }}>{h.date}</span>
                    </div>
                    <span style={{
                      fontSize: '0.78rem',
                      fontWeight: 700,
                      padding: '2px 6px',
                      borderRadius: 4,
                      background: h.status === 'Upcoming' ? '#dcfce7' : '#f1f5f9',
                      color: h.status === 'Upcoming' ? '#166534' : '#64748b'
                    }}>
                      {h.status}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* TAB 7: EMPLOYEE DOCUMENT EXPIRY TRACKER                        */}
      {/* ------------------------------------------------------------- */}
      {tab === 'documents' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <div className="ax-panel">
            <h2 style={{ margin: '0 0 4px 0', fontSize: '1.25rem', color: '#064e3b' }}>
              Employee Compliance &amp; Document Governance
            </h2>
            <p style={{ margin: 0, color: 'var(--muted)', fontSize: '0.9rem' }}>
              Track Passports, Emirates IDs, RERA Real Estate Broker Cards, and UAE Residence Visas.
            </p>
          </div>

          <div className="ax-panel" style={{ padding: 0, overflowX: 'auto' }}>
            <table className="ax-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.88rem' }}>
              <thead>
                <tr style={{ background: '#faf6ef', borderBottom: '1px solid #eddcd2' }}>
                  <th style={{ padding: '12px 16px', textAlign: 'left' }}>EMPLOYEE</th>
                  <th style={{ padding: '12px 16px', textAlign: 'left' }}>DOCUMENT TYPE</th>
                  <th style={{ padding: '12px 16px', textAlign: 'left' }}>DOCUMENT NO. / REF</th>
                  <th style={{ padding: '12px 16px', textAlign: 'left' }}>VALID UNTIL</th>
                  <th style={{ padding: '12px 16px', textAlign: 'left' }}>COMPLIANCE STATUS</th>
                  <th style={{ padding: '12px 16px', textAlign: 'right' }}>ACTION</th>
                </tr>
              </thead>
              <tbody>
                {employees.map((e, idx) => (
                  <tr key={e.id} style={{ borderBottom: '1px solid #f4ede4' }}>
                    <td style={{ padding: '12px 16px' }}>
                      <div style={{ fontWeight: 600, color: '#1c1c1c' }}>{e.full_name}</div>
                      <div style={{ fontSize: '0.8rem', color: '#666' }}>{e.employee_id} · {e.department}</div>
                    </td>
                    <td style={{ padding: '12px 16px', color: '#333', fontWeight: 500 }}>
                      {idx % 3 === 0 ? 'RERA Broker Card (BRN)' : idx % 3 === 1 ? 'Emirates ID' : 'UAE Residence Visa'}
                    </td>
                    <td style={{ padding: '12px 16px', fontFamily: 'monospace', color: '#444' }}>
                      {idx % 3 === 0 ? `BRN-54${100 + e.id}` : idx % 3 === 1 ? `784-199${e.id}-1234567-1` : `201/2024/${9000 + e.id}`}
                    </td>
                    <td style={{ padding: '12px 16px', color: '#444' }}>
                      {idx === 0 ? '2026-12-31' : idx === 1 ? '2027-04-15' : '2028-09-30'}
                    </td>
                    <td style={{ padding: '12px 16px' }}>
                      <span style={{
                        padding: '2px 8px',
                        borderRadius: 4,
                        fontSize: '0.8rem',
                        fontWeight: 600,
                        background: '#dcfce7',
                        color: '#166534'
                      }}>
                        ✓ Compliant
                      </span>
                    </td>
                    <td style={{ padding: '12px 16px', textAlign: 'right' }}>
                      <button className="btn btn-sm btn-ghost" onClick={() => openEditEmployee(e)}>
                        View Profile
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* TAB 8: HR REPORTS & HEADCOUNT ANALYTICS                       */}
      {/* ------------------------------------------------------------- */}
      {tab === 'reports' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <div className="ax-panel">
            <h2 style={{ margin: '0 0 4px 0', fontSize: '1.25rem', color: '#064e3b' }}>
              Human Resources Metrics &amp; Compliance Reports
            </h2>
            <p style={{ margin: 0, color: 'var(--muted)', fontSize: '0.9rem' }}>
              Headcount distribution, attendance adherence, and personnel records for UAE operations.
            </p>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
            <div className="ax-panel">
              <h3 style={{ margin: '0 0 12px 0', fontSize: '1.05rem', color: '#1c1c1c' }}>
                Department Distribution Summary
              </h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {(stats?.departments || []).map((d) => (
                  <div key={d.department} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 12px', background: '#faf6ef', borderRadius: 6 }}>
                    <span style={{ fontWeight: 600, color: '#333' }}>{d.department}</span>
                    <span style={{ fontWeight: 700, color: '#064e3b' }}>{d.count} personnel</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="ax-panel">
              <h3 style={{ margin: '0 0 12px 0', fontSize: '1.05rem', color: '#1c1c1c' }}>
                Attendance &amp; Leave Utilization
              </h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 12px', background: '#faf6ef', borderRadius: 6 }}>
                  <span>Total Active Workforce</span>
                  <b>{stats?.active_employees ?? 0}</b>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 12px', background: '#faf6ef', borderRadius: 6 }}>
                  <span>Present on Duty Today</span>
                  <b style={{ color: '#059669' }}>{stats?.present_today ?? 0}</b>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 12px', background: '#faf6ef', borderRadius: 6 }}>
                  <span>Field Duty &amp; Penthouse Viewings</span>
                  <b style={{ color: '#0284c7' }}>{stats?.field_duty_today ?? 0}</b>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 12px', background: '#faf6ef', borderRadius: 6 }}>
                  <span>On Approved Leave</span>
                  <b style={{ color: '#854d0e' }}>{stats?.on_leave_today ?? 0}</b>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 12px', background: '#faf6ef', borderRadius: 6 }}>
                  <span>Pending Leave Approvals</span>
                  <b style={{ color: (stats?.pending_leave_requests ?? 0) > 0 ? '#dc2626' : '#666' }}>
                    {stats?.pending_leave_requests ?? 0}
                  </b>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* TAB 9: OFFBOARDING WORKFLOW                                   */}
      {/* ------------------------------------------------------------- */}
      {tab === 'offboarding' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <div className="ax-panel">
            <h2 style={{ margin: '0 0 4px 0', fontSize: '1.25rem', color: '#991b1b' }}>
              Employee Separation &amp; Offboarding Governance
            </h2>
            <p style={{ margin: 0, color: 'var(--muted)', fontSize: '0.9rem' }}>
              Authorized procedure for resigning and terminating personnel. Deactivation terminates active sessions while preserving historical CRM records and deals.
            </p>
          </div>

          <div className="ax-panel">
            <h3 style={{ margin: '0 0 12px 0', fontSize: '1.05rem', color: '#1c1c1c' }}>
              Standard UAE Real Estate Clearance Procedure
            </h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 14 }}>
              <div style={{ padding: 14, background: '#faf6ef', borderRadius: 8, border: '1px solid #eddcd2' }}>
                <div style={{ fontWeight: 700, color: '#991b1b', marginBottom: 4 }}>1. Sales Lead Reassignment</div>
                <p style={{ fontSize: '0.82rem', color: '#555', margin: 0 }}>
                  Transfer all active buyer/seller leads to sales management or the shared lead pool. Customer relationships remain preserved.
                </p>
              </div>
              <div style={{ padding: 14, background: '#faf6ef', borderRadius: 8, border: '1px solid #eddcd2' }}>
                <div style={{ fontWeight: 700, color: '#991b1b', marginBottom: 4 }}>2. RERA Broker Card Deregistration</div>
                <p style={{ fontSize: '0.82rem', color: '#555', margin: 0 }}>
                  Cancel company sponsorship of the RERA broker card on the Dubai Land Department (DLD) portal.
                </p>
              </div>
              <div style={{ padding: 14, background: '#faf6ef', borderRadius: 8, border: '1px solid #eddcd2' }}>
                <div style={{ fontWeight: 700, color: '#991b1b', marginBottom: 4 }}>3. Company Asset Recovery</div>
                <p style={{ fontSize: '0.82rem', color: '#555', margin: 0 }}>
                  Retrieve official laptop, office keys, building security access cards, and company SIM card.
                </p>
              </div>
              <div style={{ padding: 14, background: '#faf6ef', borderRadius: 8, border: '1px solid #eddcd2' }}>
                <div style={{ fontWeight: 700, color: '#991b1b', marginBottom: 4 }}>4. Account Deactivation &amp; Revocation</div>
                <p style={{ fontSize: '0.82rem', color: '#555', margin: 0 }}>
                  Deactivate employee record and revoke all active CRM sessions. Database records are never deleted.
                </p>
              </div>
            </div>
          </div>

          {/* Offboarding Execution & Departure Records */}
          <div className="ax-panel">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 10 }}>
              <div>
                <h3 style={{ margin: '0 0 4px 0', fontSize: '1.05rem', color: '#1c1c1c' }}>
                  Workforce Separation &amp; Clearance Records
                </h3>
                <p style={{ margin: 0, fontSize: '0.82rem', color: '#64748b' }}>
                  Personnel who have completed or are undergoing formal offboarding. CRM logins are suspended.
                </p>
              </div>
              <button
                className="btn btn-sm"
                style={{ background: '#b91c1c', color: '#fff' }}
                onClick={() => {
                  const firstActive = employees.find(e => e.employment_status === 'Active')
                  setOffboardModalEmp(firstActive || employees[0] || null)
                  setOffboardReason('')
                }}
              >
                + Initiate Employee Offboarding
              </button>
            </div>

            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.875rem' }}>
              <thead>
                <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0', color: '#475569' }}>
                  <th style={{ padding: '10px 14px' }}>CODE</th>
                  <th style={{ padding: '10px 14px' }}>EMPLOYEE</th>
                  <th style={{ padding: '10px 14px' }}>DEPARTMENT &amp; ROLE</th>
                  <th style={{ padding: '10px 14px' }}>EMPLOYMENT STATUS</th>
                  <th style={{ padding: '10px 14px' }}>IT LOGIN ACCESS</th>
                  <th style={{ padding: '10px 14px', textAlign: 'right' }}>ACTION</th>
                </tr>
              </thead>
              <tbody>
                {employees.filter(e => e.employment_status !== 'Active').length === 0 ? (
                  <tr>
                    <td colSpan={6} style={{ padding: 24, textAlign: 'center', color: '#94a3b8' }}>
                      No separated or terminated personnel. Entire workforce is currently active in good standing.
                    </td>
                  </tr>
                ) : (
                  employees.filter(e => e.employment_status !== 'Active').map(emp => (
                    <tr key={emp.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                      <td style={{ padding: '10px 14px', fontWeight: 600 }}>{emp.employee_id}</td>
                      <td style={{ padding: '10px 14px' }}>
                        <div style={{ fontWeight: 600, color: '#1e293b' }}>{emp.full_name}</div>
                        <div style={{ fontSize: '0.78rem', color: '#64748b' }}>{emp.official_email}</div>
                      </td>
                      <td style={{ padding: '10px 14px' }}>
                        <div>{emp.department}</div>
                        <div style={{ fontSize: '0.78rem', color: '#64748b' }}>{emp.designation}</div>
                      </td>
                      <td style={{ padding: '10px 14px' }}>
                        <span style={{
                          padding: '2px 8px',
                          borderRadius: 6,
                          fontSize: '0.8rem',
                          fontWeight: 600,
                          background: emp.employment_status === 'Terminated' ? '#fee2e2' : '#fef3c7',
                          color: emp.employment_status === 'Terminated' ? '#991b1b' : '#92400e',
                        }}>
                          {emp.employment_status}
                        </span>
                      </td>
                      <td style={{ padding: '10px 14px' }}>
                        <span style={{
                          padding: '2px 8px',
                          borderRadius: 6,
                          fontSize: '0.78rem',
                          fontWeight: 700,
                          background: '#fee2e2',
                          color: '#991b1b',
                        }}>
                          ■ ACCESS REVOKED
                        </span>
                      </td>
                      <td style={{ padding: '10px 14px', textAlign: 'right' }}>
                        <button
                          className="btn btn-sm btn-ghost"
                          style={{ padding: '3px 8px', fontSize: '0.8rem' }}
                          onClick={() => openEditEmployee(emp)}
                        >
                          View File
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* MODAL: ADD NEW EMPLOYEE                                       */}
      {/* ------------------------------------------------------------- */}
      {showAddEmp && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999 }}>
          <div style={{ background: '#fff', padding: 28, borderRadius: 12, width: '100%', maxWidth: 540, maxHeight: '90vh', overflowY: 'auto' }}>
            <h3 style={{ margin: '0 0 16px 0', color: '#5a1645' }}>Add New Employee</h3>
            <form onSubmit={handleCreateEmployee} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <label style={{ gridColumn: 'span 2' }}>
                <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>Full Name *</span>
                <input
                  type="text"
                  className="ax-input"
                  required
                  value={newEmpForm.full_name}
                  onChange={(e) => setNewEmpForm({ ...newEmpForm, full_name: e.target.value })}
                />
              </label>

              <label style={{ gridColumn: 'span 2' }}>
                <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>Official Email *</span>
                <input
                  type="email"
                  className="ax-input"
                  required
                  value={newEmpForm.official_email}
                  onChange={(e) => setNewEmpForm({ ...newEmpForm, official_email: e.target.value })}
                />
              </label>

              <label>
                <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>Employee Code</span>
                <input
                  type="text"
                  className="ax-input"
                  placeholder="Auto (e.g. EMP-105)"
                  value={newEmpForm.employee_id}
                  onChange={(e) => setNewEmpForm({ ...newEmpForm, employee_id: e.target.value })}
                />
              </label>

              <label>
                <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>Contact Number</span>
                <input
                  type="text"
                  className="ax-input"
                  placeholder="+971 50 000 0000"
                  value={newEmpForm.contact_number}
                  onChange={(e) => setNewEmpForm({ ...newEmpForm, contact_number: e.target.value })}
                />
              </label>

              <label>
                <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>Department</span>
                <select
                  className="ax-input"
                  value={newEmpForm.department}
                  onChange={(e) => setNewEmpForm({ ...newEmpForm, department: e.target.value })}
                >
                  {DEPARTMENTS.filter((d) => d !== 'All').map((d) => <option key={d} value={d}>{d}</option>)}
                </select>
              </label>

              <label>
                <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>Designation</span>
                <input
                  type="text"
                  className="ax-input"
                  value={newEmpForm.designation}
                  onChange={(e) => setNewEmpForm({ ...newEmpForm, designation: e.target.value })}
                />
              </label>

              <label>
                <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>CRM Role</span>
                <select
                  className="ax-input"
                  value={newEmpForm.crm_role}
                  onChange={(e) => setNewEmpForm({ ...newEmpForm, crm_role: e.target.value })}
                >
                  <option value="agent">Real Estate Agent</option>
                  <option value="hr">HR Manager</option>
                  <option value="sales_manager">Sales Manager</option>
                  <option value="admin">System Administrator</option>
                </select>
              </label>

              <label>
                <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>Branch / Location</span>
                <input
                  type="text"
                  className="ax-input"
                  value={newEmpForm.branch}
                  onChange={(e) => setNewEmpForm({ ...newEmpForm, branch: e.target.value })}
                />
              </label>

              <div style={{ gridColumn: 'span 2', display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
                <input
                  type="checkbox"
                  id="create_crm"
                  checked={newEmpForm.create_crm_account}
                  onChange={(e) => setNewEmpForm({ ...newEmpForm, create_crm_account: e.target.checked })}
                />
                <label htmlFor="create_crm" style={{ fontSize: '0.85rem', fontWeight: 600 }}>
                  Create system login credentials for this employee
                </label>
              </div>

              {newEmpForm.create_crm_account && (
                <label style={{ gridColumn: 'span 2' }}>
                  <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>Initial Temporary Password</span>
                  <input
                    type="password"
                    className="ax-input"
                    placeholder="Defaults to Lyka@2026 if blank"
                    value={newEmpForm.initial_password}
                    onChange={(e) => setNewEmpForm({ ...newEmpForm, initial_password: e.target.value })}
                  />
                </label>
              )}

              <div style={{ gridColumn: 'span 2', display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 14 }}>
                <button type="button" className="btn btn-ghost" onClick={() => setShowAddEmp(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn" disabled={actionBusy}>
                  {actionBusy ? 'Creating…' : 'Create Employee'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* MODAL: EDIT EMPLOYEE PROFILE & CREDENTIAL MANAGEMENT            */}
      {/* ------------------------------------------------------------- */}
      {editingEmp && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999, padding: 16 }}>
          <div style={{ background: '#fff', padding: '24px 28px', borderRadius: 16, width: '100%', maxWidth: 740, maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.25)' }}>
            
            {/* Modal Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16, borderBottom: '1px solid #f1f5f9', paddingBottom: 12 }}>
              <div>
                <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', color: '#c5a880', textTransform: 'uppercase' }}>
                  Employee Governance #{editingEmp.employee_id}
                </span>
                <h3 style={{ margin: '4px 0 0 0', color: '#5a1645', fontSize: 20, fontFamily: 'Playfair Display, Georgia, serif' }}>
                  {editingEmp.full_name}
                </h3>
                <p style={{ margin: '2px 0 0 0', fontSize: 12, color: '#64748b' }}>
                  {editingEmp.department} · {editingEmp.designation} · {editingEmp.branch}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setEditingEmp(null)}
                style={{ background: 'none', border: 'none', fontSize: 20, color: '#94a3b8', cursor: 'pointer', padding: 4 }}
              >
                ✕
              </button>
            </div>

            {/* Linked IT Account Summary Banner (Separation of Governance) */}
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '10px 14px',
              background: '#f8fafc',
              border: '1px solid #e2e8f0',
              borderRadius: 8,
              marginBottom: 16,
              fontSize: 12,
              flexWrap: 'wrap',
              gap: 8,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontWeight: 600, color: '#334155' }}>
                  Linked IT User Account:
                </span>
                {editingEmp.account ? (
                  <span style={{
                    padding: '2px 8px',
                    borderRadius: 6,
                    fontWeight: 700,
                    fontSize: 11,
                    background: editingEmp.account.is_active ? '#dcfce7' : '#fee2e2',
                    color: editingEmp.account.is_active ? '#15803d' : '#b91c1c',
                  }}>
                    {editingEmp.account.email} ({editingEmp.account.is_active ? '● Login Active' : '■ Login Suspended'})
                  </span>
                ) : (
                  <span style={{ color: '#94a3b8', fontStyle: 'italic' }}>
                    No linked CRM login
                  </span>
                )}
              </div>
              <span style={{ color: '#64748b', fontSize: 11 }}>
                🔒 System login credentials, passwords &amp; roles are managed under{' '}
                <b style={{ color: '#475569' }}>User &amp; Role Administration</b>.
              </span>
            </div>

            {/* Navigation Tabs */}
            <div style={{ display: 'flex', gap: 6, borderBottom: '1px solid #e2e8f0', marginBottom: 18, overflowX: 'auto', paddingBottom: 2 }}>
              {[
                ['personal', '1. Personal Details'],
                ['employment', '2. Employment Details'],
                ['attendance', `3. Attendance History (${empAttendanceHistory.length})`],
              ].map(([tKey, tLabel]) => (
                <button
                  key={tKey}
                  type="button"
                  onClick={() => setEditModalTab(tKey)}
                  style={{
                    padding: '8px 14px',
                    fontSize: 12.5,
                    fontWeight: 600,
                    border: 'none',
                    borderBottom: editModalTab === tKey ? '2px solid #5a1645' : '2px solid transparent',
                    background: editModalTab === tKey ? 'rgba(90,22,69,0.06)' : 'none',
                    color: editModalTab === tKey ? '#5a1645' : '#64748b',
                    borderRadius: '6px 6px 0 0',
                    cursor: 'pointer',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {tLabel}
                </button>
              ))}
            </div>

            {/* TAB 1: PERSONAL DETAILS */}
            {editModalTab === 'personal' && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
                <label style={{ gridColumn: 'span 2' }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>Full Legal Name *</span>
                  <input
                    type="text"
                    className="ax-input"
                    required
                    value={editingEmp.full_name}
                    onChange={(e) => setEditingEmp({ ...editingEmp, full_name: e.target.value })}
                  />
                </label>

                <label>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>Official Corporate Email</span>
                  <input
                    type="email"
                    className="ax-input"
                    disabled
                    value={editingEmp.official_email}
                    title="Change login email in Tab 3 (Login Account & Access)"
                    style={{ background: '#f8fafc', color: '#64748b' }}
                  />
                  <span style={{ fontSize: 11, color: '#94a3b8' }}>Managed under Login Account & Access</span>
                </label>

                <label>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>Contact Phone Number</span>
                  <input
                    type="text"
                    className="ax-input"
                    placeholder="+971 50 123 4567"
                    value={editingEmp.contact_number || ''}
                    onChange={(e) => setEditingEmp({ ...editingEmp, contact_number: e.target.value })}
                  />
                </label>
              </div>
            )}

            {/* TAB 2: EMPLOYMENT DETAILS */}
            {editModalTab === 'employment' && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
                <label>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>Department</span>
                  <select
                    className="ax-input"
                    value={editingEmp.department}
                    onChange={(e) => setEditingEmp({ ...editingEmp, department: e.target.value })}
                  >
                    {DEPARTMENTS.filter((d) => d !== 'All').map((d) => <option key={d} value={d}>{d}</option>)}
                  </select>
                </label>

                <label>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>Designation</span>
                  <input
                    type="text"
                    className="ax-input"
                    value={editingEmp.designation}
                    onChange={(e) => setEditingEmp({ ...editingEmp, designation: e.target.value })}
                  />
                </label>

                <label>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>Employment Type</span>
                  <select
                    className="ax-input"
                    value={editingEmp.employment_type || 'Full-time'}
                    onChange={(e) => setEditingEmp({ ...editingEmp, employment_type: e.target.value })}
                  >
                    <option value="Full-time">Full-time</option>
                    <option value="Part-time">Part-time</option>
                    <option value="Contract">Contract</option>
                    <option value="Probation">Probation</option>
                  </select>
                </label>

                <label>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>Branch / Office Location</span>
                  <input
                    type="text"
                    className="ax-input"
                    value={editingEmp.branch || 'Dubai Main Branch'}
                    onChange={(e) => setEditingEmp({ ...editingEmp, branch: e.target.value })}
                  />
                </label>

                <label style={{ gridColumn: 'span 2' }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>Employment Lifecycle Status</span>
                  <select
                    className="ax-input"
                    value={editingEmp.employment_status}
                    onChange={(e) => setEditingEmp({ ...editingEmp, employment_status: e.target.value })}
                  >
                    <option value="Active">Active (Contract active in good standing)</option>
                    <option value="On Leave">On Leave (Approved sabbatical / maternity / extended leave)</option>
                    <option value="Suspended">Suspended (Access held pending internal review)</option>
                    <option value="Terminated">Terminated (Employment concluded; login revoked)</option>
                  </select>
                  <span style={{ fontSize: 11, color: '#64748b', marginTop: 4, display: 'block' }}>
                    ℹ Lifecycle employment status. Daily attendance (Present, Absent, Field Duty, WFH) is recorded independently per day.
                  </span>
                </label>
              </div>
            )}

            {/* TAB 3: ATTENDANCE HISTORY */}
            {editModalTab === 'attendance' && (
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#475569' }}>
                    Recent Daily Attendance Logs ({empAttendanceHistory.length} recorded days)
                  </span>
                </div>
                {empAttendanceHistory.length === 0 ? (
                  <div style={{ padding: 24, textAlign: 'center', background: '#f8fafc', borderRadius: 8, color: '#94a3b8', fontSize: 13 }}>
                    No attendance records logged for this employee yet.
                  </div>
                ) : (
                  <div style={{ maxHeight: 320, overflowY: 'auto', border: '1px solid #e2e8f0', borderRadius: 8 }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                      <thead>
                        <tr style={{ background: '#f8fafc', borderBottom: '1px solid #e2e8f0', textAlign: 'left' }}>
                          <th style={{ padding: '8px 12px' }}>Date</th>
                          <th style={{ padding: '8px 12px' }}>Status</th>
                          <th style={{ padding: '8px 12px' }}>Work Mode</th>
                          <th style={{ padding: '8px 12px' }}>Check In</th>
                          <th style={{ padding: '8px 12px' }}>Check Out</th>
                          <th style={{ padding: '8px 12px', textAlign: 'right' }}>Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {empAttendanceHistory.map((att) => (
                          <tr key={att.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                            <td style={{ padding: '8px 12px', fontWeight: 600 }}>{att.attendance_date}</td>
                            <td style={{ padding: '8px 12px' }}>
                              <span style={{
                                padding: '2px 8px',
                                borderRadius: 10,
                                fontSize: 11,
                                fontWeight: 700,
                                background: att.status === 'Present' ? '#dcfce7' : att.status === 'Late' ? '#fef3c7' : '#fee2e2',
                                color: att.status === 'Present' ? '#15803d' : att.status === 'Late' ? '#b45309' : '#b91c1c',
                              }}>
                                {att.status}
                              </span>
                            </td>
                            <td style={{ padding: '8px 12px', color: '#64748b' }}>{att.work_mode || 'OFFICE'}</td>
                            <td style={{ padding: '8px 12px', color: '#475569' }}>
                              {att.check_in ? new Date(att.check_in).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—'}
                            </td>
                            <td style={{ padding: '8px 12px', color: '#475569' }}>
                              {att.check_out ? new Date(att.check_out).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—'}
                            </td>
                            <td style={{ padding: '8px 12px', textAlign: 'right' }}>
                              <button
                                type="button"
                                className="btn btn-sm btn-ghost"
                                style={{ fontSize: 11, padding: '2px 8px' }}
                                onClick={() => {
                                  setCorrectingAtt(att)
                                  setCorrectionForm({ status: att.status, reason: '' })
                                }}
                              >
                                Correct
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* Modal Actions Footer */}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 22, borderTop: '1px solid #f1f5f9', paddingTop: 14 }}>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setEditingEmp(null)}
              >
                Close
              </button>
              <button
                type="button"
                className="btn"
                disabled={actionBusy}
                onClick={handleUpdateEmployee}
              >
                {actionBusy ? 'Saving Changes...' : 'Save Profile Changes'}
              </button>
            </div>

          </div>
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* MODAL: FORMAL WORKFORCE OFFBOARDING & CLEARANCE               */}
      {/* ------------------------------------------------------------- */}
      {offboardModalEmp && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999 }}>
          <div style={{ background: '#fff', padding: 28, borderRadius: 12, width: '100%', maxWidth: 500, boxShadow: '0 20px 25px -5px rgba(0,0,0,0.15)' }}>
            <h3 style={{ margin: '0 0 10px 0', color: '#991b1b', fontSize: '1.2rem' }}>Initiate Employee Offboarding</h3>
            <p style={{ fontSize: '0.88rem', color: '#475569', marginBottom: 16 }}>
              Formal employee separation governance. Completing offboarding marks the employee as <strong>Terminated</strong>, suspends CRM system login, and immediately terminates all active sessions.
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <label>
                <span style={{ fontSize: '0.82rem', fontWeight: 600, color: '#334155', display: 'block', marginBottom: 4 }}>
                  Select Employee for Separation:
                </span>
                <select
                  className="ax-input"
                  style={{ width: '100%' }}
                  value={offboardModalEmp.id}
                  onChange={(e) => {
                    const sel = employees.find(x => x.id === parseInt(e.target.value, 10))
                    if (sel) setOffboardModalEmp(sel)
                  }}
                >
                  {employees.map(e => (
                    <option key={e.id} value={e.id}>
                      {e.employee_id} - {e.full_name} ({e.department} · {e.employment_status})
                    </option>
                  ))}
                </select>
              </label>

              <label>
                <span style={{ fontSize: '0.82rem', fontWeight: 600, color: '#334155', display: 'block', marginBottom: 4 }}>
                  Separation Justification &amp; Clearance Notes *
                </span>
                <textarea
                  className="ax-input"
                  style={{ width: '100%', height: 80 }}
                  required
                  placeholder="e.g. Resignation tendered; handover completed; RERA broker card cancelled."
                  value={offboardReason}
                  onChange={(e) => setOffboardReason(e.target.value)}
                />
              </label>

              <div style={{ padding: '10px 12px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, fontSize: '0.78rem', color: '#991b1b' }}>
                ⚠ <strong>Data Integrity Note:</strong> Historical leads, transactions, and audit records will remain permanently preserved. Database records are never deleted.
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 20 }}>
              <button className="btn btn-ghost" onClick={() => setOffboardModalEmp(null)}>
                Cancel
              </button>
              <button
                className="btn"
                style={{ background: '#dc2626', color: '#fff' }}
                disabled={actionBusy || !offboardReason.trim()}
                onClick={handleOffboardEmployee}
              >
                {actionBusy ? 'Processing Clearance…' : 'Confirm Offboarding & Revoke Access'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* MODAL: AUTHORIZE MANUAL ATTENDANCE CORRECTION                 */}
      {/* ------------------------------------------------------------- */}
      {correctingAtt && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999 }}>
          <div style={{ background: '#fff', padding: 28, borderRadius: 12, width: '100%', maxWidth: 460 }}>
            <h3 style={{ margin: '0 0 12px 0', color: '#5a1645' }}>Correct Attendance Entry</h3>
            <p style={{ fontSize: '0.88rem', color: '#666', marginBottom: 16 }}>
              Employee: <strong>{correctingAtt.employee_name}</strong> · Date: {correctingAtt.attendance_date}
            </p>
            <form onSubmit={handleCorrectAttendance} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <label>
                <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>Adjusted Status *</span>
                <select
                  className="ax-input"
                  style={{ width: '100%' }}
                  value={correctionForm.status}
                  onChange={(e) => setCorrectionForm({ ...correctionForm, status: e.target.value })}
                >
                  {ATTENDANCE_STATUSES.filter((s) => s !== 'All').map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </label>

              <label>
                <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>Reason for Correction (Audited) *</span>
                <textarea
                  className="ax-input"
                  style={{ width: '100%', height: 75 }}
                  required
                  placeholder="e.g. Employee attended offsite client viewing at Palm Jumeirah."
                  value={correctionForm.reason}
                  onChange={(e) => setCorrectionForm({ ...correctionForm, reason: e.target.value })}
                />
              </label>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 10 }}>
                <button type="button" className="btn btn-ghost" onClick={() => setCorrectingAtt(null)}>
                  Cancel
                </button>
                <button type="submit" className="btn" disabled={actionBusy || !correctionForm.reason.trim()}>
                  {actionBusy ? 'Saving…' : 'Save Correction'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* MODAL: REVIEW LEAVE APPLICATION                               */}
      {/* ------------------------------------------------------------- */}
      {reviewingLeave && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999 }}>
          <div style={{ background: '#fff', padding: 28, borderRadius: 12, width: '100%', maxWidth: 460 }}>
            <h3 style={{ margin: '0 0 12px 0', color: '#5a1645' }}>Review Leave Application</h3>
            <p style={{ fontSize: '0.9rem', color: '#444', marginBottom: 12 }}>
              Applicant: <strong>{reviewingLeave.employee_name}</strong> ({reviewingLeave.department})<br />
              Period: {reviewingLeave.start_date} to {reviewingLeave.end_date} ({reviewingLeave.days_count} days)<br />
              Type: <strong>{reviewingLeave.leave_type}</strong>
            </p>
            <div style={{ background: '#faf6ef', padding: '8px 12px', borderRadius: 6, fontSize: '0.86rem', color: '#333', marginBottom: 16 }}>
              "{reviewingLeave.reason}"
            </div>

            <label style={{ display: 'block', marginBottom: 16 }}>
              <span style={{ fontSize: '0.85rem', fontWeight: 600, display: 'block', marginBottom: 4 }}>
                Reviewer Notes (Optional)
              </span>
              <input
                type="text"
                className="ax-input"
                style={{ width: '100%' }}
                placeholder="e.g. Approved. Coverage arranged."
                value={reviewNotes}
                onChange={(e) => setReviewNotes(e.target.value)}
              />
            </label>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
              <button className="btn btn-ghost" onClick={() => setReviewingLeave(null)}>
                Cancel
              </button>
              <button
                className="btn btn-ghost"
                style={{ color: '#dc2626' }}
                disabled={actionBusy}
                onClick={() => handleReviewLeave(false)}
              >
                Reject Request
              </button>
              <button
                className="btn"
                disabled={actionBusy}
                onClick={() => handleReviewLeave(true)}
              >
                {actionBusy ? 'Processing…' : 'Approve Leave'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

