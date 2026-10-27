import React from 'react'
import { Link } from 'react-router-dom'
import { useAuth, hasPerm } from '../auth/AuthContext.jsx'

/* ------------------------------------------------------------------ */
/* ModulePlaceholder (Phase 4) — HONEST "not yet built" dashboards.    */
/*                                                                     */
/* Roles such as HR, Payroll, Operations, Finance and Property Manager */
/* have a genuine permission foundation in the backend registry, but   */
/* the corresponding business modules DO NOT EXIST YET. This page      */
/* says so plainly instead of pretending to be functional HR/payroll   */
/* software. No employee, salary, payslip or attendance data is shown  */
/* or stored anywhere — because none exists.                          */
/*                                                                     */
/* When a real module is built it replaces this route; the role,       */
/* permission and access scaffolding around it stays exactly the same. */
/* ------------------------------------------------------------------ */

const MODULES = {
  '/hr/dashboard': {
    title: 'HR',
    heading: 'Human Resources',
    blurb:
      'Employee records, attendance and leave management will live here. This module is not yet implemented.',
    planned: ['Employee directory', 'Attendance tracking', 'Leave requests'],
  },
  '/payroll/dashboard': {
    title: 'Payroll',
    heading: 'Payroll',
    blurb:
      'Salary calculation, approval workflow and payslips will live here. This module is not yet implemented.',
    planned: ['Payroll runs', 'Approval workflow', 'Payslip delivery'],
  },
  '/operations/dashboard': {
    title: 'Operations',
    heading: 'Operations',
    blurb:
      'Operational workflows and reporting will live here. This module is not yet implemented.',
    planned: ['Operational dashboards', 'Process tracking'],
  },
  '/finance/dashboard': {
    title: 'Finance',
    heading: 'Finance & Accounts',
    blurb:
      'Financial reporting and accounts receivable/payable will live here. This module is not yet implemented.',
    planned: ['Financial reports', 'Transaction ledger'],
  },
  '/properties/manage': {
    title: 'Listings',
    heading: 'Property Management',
    blurb:
      'Listing creation, editing and approval will live here. This module is not yet implemented — public browsing of approved listings already works on the main site.',
    planned: ['Create listing', 'Edit / approve', 'Availability status'],
  },
}

export default function ModulePlaceholder({ path }) {
  const { session, roles, permissions } = useAuth()
  const mod = MODULES[path] || {
    title: 'Module',
    heading: 'Module',
    blurb: 'This module is not yet implemented.',
    planned: [],
  }

  const roleName =
    (roles && roles[0] && roles[0].display_name) || 'your role'

  // Only offer the CRM link to roles that actually hold CRM permissions —
  // placeholder-module users (HR, payroll, finance...) would only bounce
  // off the guard.
  const canUseCrm =
    hasPerm(session, 'leads.read_assigned') || hasPerm(session, 'leads.read_all')

  return (
    <div className="ph">
      <div className="ph__card">
        <span className="eyebrow">Lyka Realty · {mod.title}</span>
        <h1>{mod.heading}</h1>
        <div className="ph__badge" role="status">
          Not yet implemented
        </div>
        <p className="ph__blurb">{mod.blurb}</p>

        {mod.planned.length > 0 && (
          <>
            <h2 className="ph__sub">Planned capabilities</h2>
            <ul className="ph__list">
              {mod.planned.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </>
        )}

        <div className="ph__meta">
          <p>
            You are signed in as <b>{session?.identity?.full_name || session?.identity?.email}</b>{' '}
            with the role <b>{roleName}</b>. Your access to this area is already
            governed by role-based permissions on the server — the dashboard itself
            simply has not been built yet.
          </p>
          <p className="ph__note">
            We show this placeholder rather than a mock screen so nothing here is
            ever mistaken for live HR or payroll data.
          </p>
        </div>

        {canUseCrm && (
          <Link className="btn" to="/agent/dashboard">
            Go to your CRM dashboard
          </Link>
        )}
      </div>
    </div>
  )
}
