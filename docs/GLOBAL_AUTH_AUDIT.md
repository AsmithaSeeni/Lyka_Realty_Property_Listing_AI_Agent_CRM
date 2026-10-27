# Global Auth & RBAC — Phase 0 Audit

Status: complete (read-only inspection; no destructive changes made).
Scope: existing authentication, sessions, roles, database, routing, tests and
deployment configuration at `D:\lyka_property_agent2`, prior to implementing the
single Global Login Portal and enterprise Role-Based Access Control (RBAC).

---

## 1. Existing authentication flow

The application runs **two deliberately separate identity worlds** today:

| Aspect | Staff (internal CRM) | Customer (public) |
|---|---|---|
| Table | `agents` | `customers` |
| Identifier | `email` (unique) **or** `username` (unique) | `email` (unique among accounts) |
| Password | `password_hash` (bcrypt, cost 12) — always set | `password_hash` (bcrypt) — `NULL` = guest |
| Session token | `agent_sessions` row; only the **SHA-256 hash** is stored | `customers.token_hash` (the token itself is the session handle) |
| Cookie | `lyka_agent_session` (HttpOnly, SameSite=Lax, Secure in prod) | `lyka_customer` (HttpOnly, SameSite=Lax, Secure in prod) |
| Login endpoint | `POST /api/auth/login` (email **or** username + password) | `POST /api/customer/login` (email + password) |
| Session check | `GET /api/auth/me` → 401 when unauthenticated | `GET /api/customer/me` → `{authenticated:false}` for guests |
| Logout | `POST /api/auth/logout` (revokes the session row) | `POST /api/customer/logout` (clears cookie) |
| Guard dependency | `get_current_agent` (`services/auth.py`) | `_require_account_customer` / `get_or_create_customer` |

**Strengths already present (keep and build on):**
- Server-managed opaque sessions; only token **hashes** are persisted for staff, so a DB dump cannot be replayed.
- Passwords are bcrypt hashes; plaintext is never stored or logged.
- Cookie flags are correct (HttpOnly + SameSite=Lax; Secure follows `APP_ENV`/`COOKIE_SECURE`).
- Login errors are generic ("Invalid username or password") — no account probing.
- Rate limiting on `auth` bucket (15 req/60 s per IP, in-memory).
- CSRF **origin guard** middleware on unsafe `/api/*` methods (defence-in-depth on top of SameSite=Lax).
- Sessions validated on **every** protected request; disabled agents lose access immediately.
- Customer registration reserves staff emails (staff identity can never be mirrored into the customer table).

## 2. Existing login pages & route structure (frontend)

React + Vite, plain CSS. Router in `src/App.jsx`.

- **Customer website** (public, guest-friendly): `/`, `/chat`, `/chat/:id`, `/history`, `/saved`, `/profile`, `/properties`, `/property/:id`, `/login`, `/register`, `/signin` (legacy alias). All render `CustomerAuth.jsx` for the auth pages.
- **Staff CRM** (separate chrome): `/agent/login` → `LoginPage.jsx`; `/crm` redirects to `/agent/login`; `/agent/*` wrapped in `RequireAgent` → `AgentShell` (sidebar) → `AgentDashboard`, `AgentLeads`, `AgentNewLead`, `AgentLeadDetail`, `AgentConversations`.
- **Route guard**: `RequireAgent` (`agent/AgentAuth.jsx`) calls `GET /api/auth/me`; on failure redirects to `/agent/login`. This is UX only — the backend re-checks authorisation on every request.
- **No central auth/session provider** for customers (the `Header` component fetches `/api/customer/me` per route change and listens to a `lyka:customer` window event).
- **Two disconnected login pages** with duplicated submit/error logic. No permission-aware navigation (the agent sidebar always shows Dashboard/Leads/Conversations for everyone).

## 3. Existing roles & permissions

- **Staff roles**: a single `agents.role` **string** column with exactly two values, `"admin"` and `"agent"`. Seeded by `_seed_agents()` (dev defaults `Admin@123`/`Agent@123`; production requires `SEED_*_PASSWORD`).
- **Customers**: implicitly one role, "customer". No role column.
- **Authorisation logic** is **hard-coded string comparison** `agent.role == "admin"` / `!= "admin"` in **8 places**:
  - `services/auth.py`: `lead_in_scope`, `scoped_lead_query` (admin → all leads; agent → assigned + unassigned pool).
  - `main.py`: `_scoped_conversations` (1417), `_conversation_linkable` (1434), `_resolve_agent` (1456, only admin assigns others), `agent_update_lead` assignment rule (1890), agent-conversations scope (2291).
- **No** permission model, **no** role→permission registry, **no** multi-role support, **no** user/role management API.

## 4. Security issues & gaps

| # | Gap | Severity | Notes |
|---|---|---|---|
| G1 | No central permission model — authorisation is scattered string checks | High | Adding any role means editing 8+ call sites; easy to miss one. |
| G2 | No account lockout / failed-login tracking / `last_login` | Medium | Only IP rate-limiting; a targeted password spray at one account is damped but not blocked. |
| G3 | No audit logging of security events | Medium | Login/logout/role-change/suspend are invisible after the fact. |
| G4 | No user provisioning / role-management API | Medium | Staff accounts only created by seeding; no safe admin-driven creation or role change. |
| G5 | No last-admin protection | Medium | Nothing prevents removing/demoting the only admin (once such an API exists). |
| G6 | Two login pages, duplicated logic, no unified entry point | Medium | Confusing UX; no single place to apply future MFA/reset. |
| G7 | No password-reset / recovery flow | Low | Must NOT be faked; needs email delivery which is not configured. |
| G8 | Agent sidebar shows every nav item regardless of role | Low | UX only; backend enforces correctly. |
| G9 | No `X-Frame-Options`/`Permissions-Policy` hardening headers | Low | Outside strict auth scope. |

**Not issues (verified secure):** cookie flags, hash-at-rest sessions, generic
errors, CSRF origin guard, per-request session validation, staff-email
reservation, request-size guard, in-memory rate limiting (honest limitation is
that it is per-process — documented in README).

## 5. Existing tables & relationships (live DB inspection)

Tables present: `agents`, `agent_sessions`, `customers`, `conversations`,
`leads`, `messages`, `properties`, `property_recommendations`,
`saved_properties`, `follow_ups`. **No** `roles`, `permissions`, `users`,
`audit_*`, `hr_*`, `payroll_*` tables exist.

- `agents`: id, email (UQ), username (UQ), full_name, password_hash, role, is_active, created_at. **2 rows** (1 admin, 1 agent).
- `agent_sessions`: id, agent_id (FK, idx), token_hash (UQ, idx), created_at, expires_at, revoked_at. **118 rows**.
- `customers`: id, token_hash (UQ, idx), name, phone, email, password_hash, created_at, updated_at. **321 rows** (64 registered accounts, the rest guests).
- `leads.assigned_agent_id` → `agents.id`; `follow_ups.assigned_agent_id` → `agents.id`; `conversations.customer_id` → `customers.id`.
- Relationships/foreign keys enforced per-connection (`PRAGMA foreign_keys=ON`, Phase 9 contract).

## 6. Files to modify (implementation plan)

**Backend (additive only; no destructive migration):**
- `app/services/auth.py` — add unified session resolver, permission helpers, lockout/`last_login`, keep existing signatures intact.
- **New** `app/services/rbac.py` — central role→permission registry + permission catalogue (single source of truth).
- **New** `app/services/audit.py` — `write_audit()` helper + event names.
- `app/database.py` — additive columns on `agents` (`last_login_at`, `failed_login_count`, `locked_until`) + **new** tables `agent_roles` (multi-role), `audit_log`; idempotent migrations in `_MIGRATIONS`.
- `app/main.py` — unified `/api/auth/session`; convert the 8 hard-coded role checks to permission checks; add admin user-management + audit-read endpoints; wire audit writes into login/logout/role-change/suspend.
- `app/config.py` — new knobs (lockout threshold/window, default landing policy).
- `backend/tests/` — new RBAC / portal / admin / audit test modules; existing suites must stay green.

**Frontend:**
- **New** `src/auth/AuthContext.jsx` — central session provider (identity, roles, permissions, landing resolver).
- **New** `src/pages/GlobalLogin.jsx` — one responsive portal (staff + customer modes, show/hide password, generic errors).
- `src/App.jsx` — mount provider; route all staff+customer sign-in through the portal; add protected-route wrapper; add clearly-marked "not yet implemented" dashboards for HR/Payroll/etc.
- `src/agent/AgentShell.jsx` — permission-aware navigation.
- `src/api.js` — add session/admin/audit calls; keep every existing call.
- `src/index.css` — scoped portal styles (existing pages untouched).

**Docs:** this file, `docs/GLOBAL_AUTH_IMPLEMENTATION.md`, README, `.env.example`.

## 7. Migration risks

| Risk | Mitigation |
|---|---|
| SQLite cannot `ALTER TABLE … ADD CONSTRAINT`; no `drop_all` allowed | All new columns nullable with defaults; all new tables created by `create_all`; migrations are idempotent (column-exists check), matching the existing `_MIGRATIONS` pattern. |
| Existing 2 staff + 321 customers must survive | Nothing deletes or rewrites rows. Final design (refined in `GLOBAL_AUTH_IMPLEMENTATION.md`): `agent_roles` holds **extra roles only** — the primary role stays in `agents.role`, which remains authoritative on its own, so **no backfill is needed at all** and the 8 legacy checks plus all tests keep working until they are converted. |
| Turso/libSQL path | Same SQLAlchemy models; additive DDL runs through the same `init_db()`. Live Turso cannot be verified from this Windows machine (`sqlalchemy-libsql` has no Windows wheel) — documented honestly; SQLite path fully tested. |
| 592 existing tests must not regress | Permission checks map `admin → leads.read_all`, `agent → leads.read_assigned`, preserving exact 404/403 behaviours the tests assert. |
| Customers are not staff | Customer identity stays in `customers`; the portal authenticates whichever world the credential belongs to. Customers receive the single implicit role `customer`. No cross-world token reuse (a customer cookie never opens `/api/agent/*`). |

## 8. Step-by-step implementation plan

1. **Phase 1 — Backend identity/sessions consolidation**
   Add `last_login_at`, `failed_login_count`, `locked_until` to `agents` (additive). Add a unified session resolver and `GET /api/auth/session` returning the current identity (staff **or** customer) + roles + permissions + landing route. Keep `/api/auth/login`, `/api/customer/login`, `/api/auth/me` contracts byte-compatible.

2. **Phase 2 — Central roles, permissions, server-side authorisation**
   Create `services/rbac.py` (role catalogue + permission registry + `require_permission`). Add `agent_roles` (multi-role) backfilled from `agents.role`. Convert all 8 hard-coded `agent.role == "admin"` checks to permission checks with identical 404/403 behaviour.

3. **Phase 3 — Global login UI + central auth state**
   `AuthContext` provider + `GlobalLogin` portal (staff & customer modes). Single entry point; registration remains customer-only. Backend ignores any client-supplied role for authorisation.

4. **Phase 4 — Dashboard integration & route guards**
   Protected-route wrapper; central post-login landing resolver; permission-aware agent sidebar; clearly-labelled "not yet implemented" dashboards for roles whose modules do not exist (HR/Payroll/Operations/Finance/Support/Property Manager). Access-denied page for direct URL attempts.

5. **Phase 5 — Safe provisioning & administrative role management**
   Admin user-management API (`users.read/create/update/suspend`, `roles.manage`), staff-only creation, last-admin protection, session revocation on suspend/role change, reauthentication for high-impact changes.

6. **Phase 6 — Audit logging & security hardening**
   `audit_log` table + `write_audit()`; record login success/failure, logout, role change, suspension, staff creation, sensitive reads. Permission-controlled read endpoint. Lockout wiring.

7. **Phase 7 — Tests, regression, build, deployment assumptions**
   New test modules (auth, authorization, regression) + full existing suite + `npm run build`. Update README, `.env.example`, deployment notes.

**Roles implemented vs. not:** the registry defines all requested business roles
(System Administrator, HR Manager/Staff, Payroll Officer, Real Estate Agent,
Sales Manager, Operations Manager, Finance, Property Manager, Customer Support,
Customer) so authorisation is real and extensible. Only Real Estate Agent,
System Administrator and Customer map to **existing** modules. HR and Payroll
receive a genuine permission foundation and a dashboard that is **explicitly
marked "module not yet implemented"** — no fabricated employee, salary, payslip
or attendance data is ever shown or stored.
