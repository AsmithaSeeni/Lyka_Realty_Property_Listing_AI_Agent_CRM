# Production Cleanup & Reliability — Implementation Report

Date: 2026-10-27 · Repo: `D:\lyka_property_agent2` · Branch: `main`
**State: all changes local and uncommitted (per the no-commit rule). The
production site is unchanged until the operator deploys.**

Companion documents: `PRODUCTION_CLEANUP_AUDIT.md` (found state),
`PRODUCTION_HEALTH_AUDIT.md` (findings/fixes/measurement),
`PRODUCTION_DEPLOYMENT_GUIDE.md` (env vars + steps),
`PRODUCTION_SMOKE_TESTS.md` (post-deploy checklist).

---

## 1. What changed (by area)

**Homepage content cleanup (real JSX removal)**
- `frontend/src/pages/LandingPage.jsx` — full rewrite: removed the AI
  feature-card grid ("Multilingual by design"…), the fabricated "Live
  preview" hero chat card + online/offline chip, the `★★★★★ Trusted by 300+
  clients` chip, the `300+/25,082/10/3` stats row, the "AI desk that never
  sleeps"/"No pressure, no confusion" slogans, and the health-state fetch.
  Kept: identity, headline, both CTAs, services (trim), communities,
  languages, WhatsApp CTA, verified contact info.
- `frontend/src/App.jsx` — footer: dropped "300+ clients served"; kept
  "Founded 2024".
- `frontend/index.html` — meta description: dropped the "25,000+ listings"
  count.
- `frontend/src/index.css` — hero becomes single-column (child measure
  capped at 820px); removed all CSS for the deleted sections plus dead
  blocks (`.lg*`, `.ca-*`, `.metrics/.metric*`, `.lead-row/.lead-cell*`,
  `.search-input`, `.chip-row`, `.status-row`, `.ax-sec`, `.section.tight`,
  `.section.white`, `.on-dark .eyebrow`, `.prop-rail*`, `.prop-grid`) after
  grep-verifying zero JSX usage. Brand palette/typography/logo untouched.

**Dead files/imports removed (after reference checks)**
- Deleted `frontend/src/pages/CustomerAuth.jsx`, `LoginPage.jsx` (orphaned
  predecessors of `GlobalLogin.jsx`), `backend/app/server_entry.py` (stale v1
  artifact, previously flagged P3 in the Phase-8 audit).
- Removed dead client methods `createConversation`, `searchProperties`,
  `transcribe`; removed unused imports `BackgroundTasks` (main.py),
  `tempfile` (voice.py).
- Retained (documented, not dead): `admin*`, `auditLog`, follow-up listers
  (client contract of live tested endpoints), `api.health` (chat banner).

**Fixed misleading behaviour**
- `ModulePlaceholder.jsx` — "Go to your CRM dashboard" is now permission-gated
  (`leads.read_assigned`/`leads.read_all`) and rendered as a client-side
  `Link`; HR/payroll/finance placeholder users no longer see a button that
  would bounce them off the CRM guard. Placeholder modules remain clearly
  marked "Not yet implemented".

**Production reliability (backend)**
- Dataset moved `UAErealestate.json` → `backend/UAErealestate.json` (tracked
  `git mv`, single 8.2 MB copy, 25,082 rows) so the Vercel backend function
  bundles it; `test_phase2_property_model.py` + README updated.
- `database.py` — production guard: `APP_ENV=production` with empty
  `DATABASE_URL` now raises a `RuntimeError` naming the variable and fix.
- `main.py` — `init_db()` wrapped with actionable logging + re-raise; health
  endpoint enriched (database count, dataset rows vs DB listings, provider
  config presence — no secrets); saved-properties GET/POST switched to O(1)
  cached id lookups.
- `nvidia_client.py` — httpx timeout 120 s → 25 s read / 8 s connect (fits the
  30 s serverless cap); `_fallback_response()` replaced with an honest
  outage message per reply language (existing honesty tests pass unmodified).
- `voice.py` — all provider HTTP calls capped at 25 s.
- `.env.example` + `docs/GLOBAL_AUTH_IMPLEMENTATION.md` — corrected lockout
  wording (threshold clamped ≥ 1, cannot be disabled); added
  `TURSO_AUTH_TOKEN` documentation.

**API client (frontend)**
- `api.js` — every call carries an `AbortSignal` timeout (reads 15 s, auth
  20 s, AI turns 32 s, extraction 35 s, health 10 s, session 12 s) with a
  friendly "Request timed out" error (`code: 'timeout'`).

**New tests**
- `backend/tests/test_health_checks.py` — health contract + secret-leak check.

## 2. Verification (local, this machine)

| Check | Result |
|---|---|
| Backend suite | **629 passed, 2 skipped** (was 627+2), 124 s |
| Targeted subset (health, fallbacks, dataset move, env example, voice) | **70 passed**, 2.6 s |
| Frontend production build | Clean, 56 modules — `index-Ce3xmRR2.js` 291.66 kB (gzip 85.15; was 295.68 kB), CSS 65.90 kB |
| Fresh uvicorn start with new code | Health returns the new `checks` shape; log shows "Loaded 25082 properties" from the new location |
| API latency (warm, 3 runs each) | health 35–47 ms · properties?limit=24 64–112 ms · dataset search 43–84 ms · session 29–40 ms · conversations 28–30 ms |
| Browser scenario (Edge headless, `vite preview`) — 9 pages | **0 page errors, 0 console errors** (evidence `ev_9684ee9e…`, `ev_0a6ea1af…`, detail/CRM scenario) |
| Homepage content assertions | All 12 kept items present; all 15 removed items (cards, stats, trust chip, live-preview card, slogans, "300+", "25,082") absent from the rendered DOM |
| `/properties` + `/property/1` | Render records/detail (fictional-demo badges + prices intact) |
| `/login`, `/register` | Global Portal renders in both modes |
| `/agent/dashboard`, `/hr/dashboard` (logged out) | Redirect to `/login` (latter preserves `?next=`) |
| Unknown route `/route-that-does-not-exist-xyz` | SPA renders (no platform 404) |
| Chat page | Loads, honest status via `api.health` ("Online" when healthy) |

## 3. Production status — read carefully

- **Not deployed.** The live site still runs the stale build: its `/api/*`
  500s and deep-link 404s remain until the operator commits, pushes and sets
  the environment variables (deployment guide §3).
- The production `/api/*` 500 root cause was narrowed to import-time database
  configuration; the exact exception needs Vercel function logs, which this
  work could not access. The new logging turns that unknown into one explicit
  line on the next deploy.
- Live Turso could not be exercised from this Windows machine (no
  `sqlalchemy-libsql` wheel); libsql behaviour must be confirmed with the
  smoke tests after deploy.
- The production `properties` table is expected to be empty until the operator
  runs the seeder deliberately (documented; never run against production from
  here). Chat search serves the bundled dataset regardless.

## 4. Risks & deliberate non-changes

- Rate limiting remains in-memory/IP-keyed behind the proxy (analysis +
  proposed Upstash fix in health audit §7 — needs approval/account).
- Streaming chat, conversations-list over-fetch, unbounded in-process caches:
  documented only.
- Firebase evaluation: not needed (health audit §9).
- Everything auth/RBAC/CSRF/lockout/audit was preserved; HR/payroll
  placeholders stay marked not-implemented; the fictional-demo safeguard
  badges are untouched; no credentials appear in code, docs, or storage.
