# Global Login & Enterprise RBAC — Implementation

Status: implemented and tested. Companion to `GLOBAL_AUTH_AUDIT.md` (Phase 0).

This document describes what was BUILT for the single Global Login Portal and
the permission-based access-control system, and states honestly what is real
versus what is only a foundation.

---

## What exists now

### 1. One global login entry point

- **`/login`** (also `/register` and legacy `/signin`) all render a single
  portal: `frontend/src/pages/GlobalLogin.jsx`.
- One form authenticates **either** a staff account (email **or** username)
  **or** a customer account (email). The backend resolves which world the
  credential belongs to — the user never picks a "role".
- **Customer registration** is a separate, clearly-labelled mode in the same
  portal. It only ever creates a *customer* account; a public request can never
  create an admin/HR/payroll/staff account (the route lives behind
  `users.create` and writes only to the `agents` table).
- Features: show/hide password, loading state, generic auth error, accessible
  labels (`aria-live` on errors), keyboard navigation, responsive two-column →
  single-column layout, sanitized `?next=` redirect (no open redirects).
- Old entry points (`/agent/login`, `/crm`) **redirect** to `/login`, so there
  is exactly one sign-in surface.

### 2. Unified session model

- **`GET /api/auth/session`** is the single "who am I?" endpoint. It returns
  whichever identity the browser holds — a **staff** session
  (`lyka_agent_session`) or a **customer** session (`lyka_customer`) — plus that
  identity's **roles**, **permissions** and **landing route**. It returns
  `{authenticated:false}` for anonymous visitors (never an error).
- **`POST /api/auth/portal-login`** is the one submit endpoint behind the form.
  Wrong password and unknown identifier return the **identical** generic 401.
- The existing endpoints (`/api/auth/login`, `/api/customer/login`,
  `/api/auth/me`) are preserved **byte-compatible**; the 592-test baseline
  stayed green throughout.

### 3. Central role & permission registry

`backend/app/services/rbac.py` is the single source of truth. Roles group
permissions; permissions gate actions. Adding a role/permission never requires
editing an authorisation call site again.

**Roles implemented** (registry keys): `admin` (System Administrator),
`sales_manager`, `agent` (Real Estate Agent), `support` (Customer Support),
`property_manager`, `operations_manager`, `finance`, `hr_manager`, `hr_staff`,
`payroll_officer`, and the implicit `customer`.

**Multi-role**: a staff identity's primary role stays in `agents.role`
(authoritative on its own). Extra roles live in the new `agent_roles` table.
`effective_roles()` merges, de-duplicates and normalises them. The documented
**default-landing policy**: the role with the lowest `priority` number wins
(admin → sales_manager → agent → …).

**Server-side enforcement**: the eight hard-coded `agent.role == "admin"`
comparisons were replaced by permission checks (`leads.read_all`,
`conversations.read_all`, `leads.assign`) with **identical 404/403 behaviour**.
Reusable dependencies were added:
`require_authenticated_user`, `require_roles(...)`,
`require_permissions(..., mode="all"|"any")`, and imperative `ensure_permission`.

### 4. Dashboards & routing

- **Real** dashboards: System Administrator, Sales Manager, Real Estate Agent
  and Support land on the existing `/agent/*` CRM (permission-filtered nav).
- **Not-yet-implemented** dashboards: HR, Payroll, Operations, Finance and
  Property Manager land on `ModulePlaceholder`, which plainly says the module
  is not built. **No employee, salary, payslip or attendance data is fabricated
  or stored anywhere** — those tables and routes do not exist.
- `ProtectedRoute` (UX wrapper) redirects anonymous users to the portal with
  `?next=`, blocks cross-kind access (a customer session cannot open staff
  areas), and renders an `AccessDenied` view for insufficient permission.
  The **backend re-checks every request**, so reaching a component never grants
  data access.

### 5. Account status, lockout & session lifecycle

- Additive `agents` columns: `last_login_at`, `failed_login_count`,
  `locked_until`, `updated_at` (idempotent migration; no row rewritten).
- **Lockout**: after `LOGIN_LOCKOUT_THRESHOLD` (default 8) consecutive failures
  on one existing account, it locks for `LOGIN_LOCKOUT_MINUTES` (default 15).
  A locked account returns the same generic 401 (no lock oracle). Counters
  reset on success. Unknown identifiers are never tracked (no row to write).
- **Session revocation**: `revoke_all_sessions()` is called on suspend, role
  change and administrative password reset, so an open browser loses access
  immediately instead of waiting for the 12 h TTL.
- Cookies stay HttpOnly + SameSite=Lax (+ Secure in production); CSRF origin
  guard and per-IP auth rate limiting are unchanged and covered by tests.

### 6. Safe provisioning & administrative role management

Permission-gated, server-side API (all require step-up re-authentication where
noted):

| Route | Permission | Step-up? |
|---|---|---|
| `GET /api/admin/users` | `users.read` | no |
| `GET /api/admin/roles` | `roles.read` or `users.read` | no |
| `POST /api/admin/users` | `users.create` | no |
| `PATCH /api/admin/users/{id}/role` | `roles.manage` | **yes** |
| `POST /api/admin/users/{id}/roles/{key}` | `roles.manage` | no |
| `DELETE /api/admin/users/{id}/roles/{key}` | `roles.manage` | no |
| `POST /api/admin/users/{id}/suspend` | `users.suspend` | **yes** |
| `POST /api/admin/users/{id}/reset-password` | `users.update` | **yes** |
| `GET /api/audit/log` | `audit.read` | no |

Safeguards: role values validated against the registry; the **last active
administrator cannot be demoted or suspended**; an admin cannot suspend their
own account; the primary role is changed via the role endpoint (extra-role
revocation cannot touch it); duplicates return 409; every password is bcrypt.

### 7. Audit logging

New append-only `audit_log` table, written only through
`services/audit.py::write_audit()`. There is **no application route to update or
delete rows**. Recorded events: login success/failure, logout, session
revocation, suspension/reactivation, role granted/revoked, staff creation,
password reset, audit read. Data-minimisation is enforced in the helper (short
`detail` clamp; passwords, tokens, cookies and message bodies are never stored).
Reading requires `audit.read`.

---

## Verified by automated tests

`backend/tests/test_global_auth_rbac.py` — **35 tests**, grouped by the master
prompt's §12 matrix:

- **Authentication**: staff & customer portal login, identical generic errors,
  suspended account cannot log in, logout invalidates the session, expired
  session rejected, lockout after N failures (correct password refused while
  locked), password hashes never returned by any auth API, rate limit and CSRF
  guard still enforced.
- **Authorization**: anonymous → 401 everywhere; customer cookie cannot reach
  staff APIs; agent cannot read another agent's restricted lead (404, no
  existence leak); role comes from the DB not the request; direct URL access
  does not bypass authorisation; multi-role union works; customer isolation.
- **Provisioning/admin**: public registration never creates staff; create +
  role validation + duplicates → 409; last-admin protection; step-up required;
  suspend revokes sessions and blocks re-login; cannot suspend self.
- **Audit**: success/failure recorded, no secrets in rows, permission-gated,
  role grant recorded.
- **Regression**: admin-sees-all, agent-scoped leads + self-assign, chat and
  properties endpoints all unchanged.

Full backend suite after implementation: **627 passed, 2 skipped** (592 baseline
+ 35 new). Frontend `npm run build`: clean, no warnings.

---

## Honest limitations

1. **HR, Payroll, Operations, Finance and Property-Manager modules do not
   exist.** Their roles and permissions are real and enforced, but the
   dashboards are explicit placeholders. No fake data is shown or stored.
2. **No self-service password reset.** No mail/SMS transport is configured, so
   a reset link cannot actually be delivered. The supported recovery path is an
   administrator reset (`POST /api/admin/users/{id}/reset-password`), which is
   audited and revokes sessions. A self-service flow is documented in the audit
   but deliberately not faked.
3. **No MFA.** Not implemented and not configured; the login form does not
   pretend to offer it.
4. **Rate limiting and lockout are per-process (in-memory).** On Vercel's
   multi-instance serverless runtime these are best-effort damping, not a
   distributed defence — put a real gateway/Redis limiter in front for
   production-grade abuse protection.
5. **Turso/libSQL live path unverified from this Windows machine**
   (`sqlalchemy-libsql` has no Windows wheel). The additive migrations run
   through the same `init_db()` and the SQLite path is fully tested; the first
   Vercel deploy should be watched in the logs.
6. **Existing `real_estate.db` staff roles were not backfilled into
   `agent_roles`** because `agents.role` remains the authoritative primary role
   and extra roles are optional. No data migration is required; nothing was
   deleted or rewritten.

---

## Configuration (new env vars, see `.env.example`)

- `LOGIN_LOCKOUT_THRESHOLD` — consecutive failures before lock (default 8; clamped to a minimum of 1 — lockout cannot be disabled)
- `LOGIN_LOCKOUT_MINUTES` — lock duration (default 15)

No other new variables are required; the portal reuses the existing session,
cookie and rate-limit configuration.
