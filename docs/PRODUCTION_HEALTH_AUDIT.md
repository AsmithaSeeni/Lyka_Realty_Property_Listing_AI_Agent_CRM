# Production Reliability, Deployment & Performance Audit — Lyka Realty

Date: 2026-10-27 · Scope: make the deployed (Vercel) environment serve the SPA
on every route, serve `/api/*` reliably, ship the property dataset, keep the
AI/speech paths honest under failure, add health checks, measure performance,
and document deployment. All fixes are implemented and verified **locally**;
production verification requires the user to commit/push/deploy and configure
the environment (nothing was committed or deployed by this work).

---

## 1. Summary of findings

| # | Finding | Severity | Root cause (evidence) | Status |
|---|---|---|---|---|
| 1 | Deep links (`/properties`, `/chat`, `/login`, refresh) returned 404 on the live site | **Blocker** | Top-level `"/(.*)"` rewrite forwarded the original path into the static frontend service, which 404s non-file paths | **Fixed (this task)**: the earlier "fix" was inert — the root `vercel.json` was never read (project Root Directory = `frontend`), so deep links kept 404ing in production. Real fix = `frontend/vercel.json`: `"/api/:path*"` → Render proxy first, then `"/(.*)"` → `/index.html` |
| 2 | Every `/api/*` request returned 500 on the live site | **Blocker** | Import-time `init_db()` failing against production DB config (missing/wrong `DATABASE_URL` → SQLite fallback on read-only serverless FS, or Turso auth failure). Exact exception needs Vercel function logs | **Made diagnosable + fail-fast**: production guard names the missing config; `init_db()` wrapped with actionable logging; root fix = user sets env vars (§4) |
| 3 | Property dataset not bundled with the deployed function | **Blocker** | `UAErealestate.json` (8.2 MB, 25,082 rows) sat at repo root; the backend service root is `backend/`, so the file never shipped → chat search/detail/saved silently returned `[]` | **Fixed**: tracked `git mv` to `backend/UAErealestate.json`; `_find_dataset()` candidate #2 resolves it on Vercel (verified locally from the new location: "Loaded 25082 properties") |
| 4 | NVIDIA client read timeout (120 s) exceeded the serverless function cap (30 s) | High | Long Tamil/thinking replies were killed mid-invocation → opaque errors | **Fixed**: `httpx.Timeout(25.0, connect=8.0)` — worst case (one non-retried read timeout, or fast 5xx + one retry) fits the 30 s budget; honest fallback is returned instead |
| 5 | On provider failure, customers received greeting-style canned replies that looked like successful AI answers | High | `_fallback_response()` masked outages | **Fixed**: single honest outage message per reply language ("LykAI is having trouble reaching its service right now…"); all existing fallback-honesty tests pass unmodified |
| 6 | Speech provider HTTP calls used 60–90 s timeouts > 30 s function cap | High | TTS/STT provider hangs became killed invocations | **Fixed**: `_PROVIDER_TIMEOUT_SECONDS = 25.0` applied to all provider calls in `voice.py` |
| 7 | No client-side fetch timeouts | Medium | A hung backend left spinners running forever | **Fixed**: `AbortSignal.timeout` on every API call (reads 15 s, auth 20 s, AI turns 32 s, extraction 35 s, health 10 s, session 12 s) with a friendly "Request timed out" error (`code: 'timeout'`) |
| 8 | Saved-properties endpoints rebuilt/scanned the whole 25k-row dataset per request | Medium | `by_id` dict rebuild (GET) + linear `next()` scan (POST) | **Fixed**: both use the cached `get_property_by_id()` O(1) id index |
| 9 | In-memory, IP-keyed rate limiting behind Vercel's proxy | Medium | Per-instance counters (reset per cold start) keyed by the connecting address, which is the proxy for X-Forwarded-For traffic — effectiveness reduced and keying is ambiguous | **Not changed** (see §7): blind key changes risk weakening the control; smallest reliable fix proposed (Upstash Redis) |
| 10 | `properties` table likely unseeded in production | Medium | Seeding is a manual CLI step (`seed_demo_properties.py` / real-estate seeder); nothing seeds automatically | **Documented** (§6): user runs the seeder against Turso deliberately; no writes were made to any production database here |
| 11 | Unbounded in-process caches (`agents`, dataset) | Low | One instance = one 8.2 MB dataset + small dict caches — acceptable at this scale, but serverless instances multiply memory | Documented only |
| 12 | `/api/conversations` loads all messages per conversation row | Low | Message over-fetch on the history list | Documented only (measured local latency 28–30 ms warm; below action threshold) |

## 2. Deployment architecture findings (Vercel)

- Two services: `frontend` (static, root `frontend`, SPA fallback rewrite) and
  `backend` (Python, root `backend`, `app.main:app`), joined by a top-level
  `"/api/(.*)"` rewrite. `maxDuration: 30` (s) on the backend function is the
  hard time budget every client and provider timeout is sized under.
- The dataset MUST live under `backend/` to be bundled — this was finding #3
  and is now the case (single tracked copy, README documents the path).
- The backend's working directory at runtime is the service root; the SQLite
  default is unusable there (read-only, ephemeral), so production requires an
  external database (Turso/libSQL).

## 3. Health check design

`GET /api/health` (main.py) — cheap, no AI provider calls, always HTTP 200
(liveness), with dependency diagnostics:

```json
{
  "status": "healthy",
  "message": "LykAI — AI Property Concierge by Lyka Realty is running",
  "checks": {
    "application": "ok",
    "database": "ok",
    "property_data": {"dataset_rows": 25082, "db_listings": 23},
    "ai_config": {"nvidia_configured": true, "stt_provider": "groq", "tts_provider": "edge-tts"}
  }
}
```

- `database` is a `COUNT` on `properties` (error caught → `"degraded"`, never raises).
- `ai_config` reports configuration **presence only** — never secret values
  (a dedicated test asserts no secret-shaped strings appear in the payload).
- Note: the health URL is **`/api/health`**. A bare `/health` returns 404 by
  design (no such route); probes must use the `/api` prefix.
- New tests: `backend/tests/test_health_checks.py` (contract + secret-leak).

## 4. Environment variables (authoritative mapping)

Frontend: **no `VITE_*` secrets exist**; all API calls use relative `/api/...`
paths through the rewrite. Nothing to configure on the frontend service beyond
what Vercel sets up automatically.

Backend (Vercel → Project Settings → Environment Variables):

| Variable | Service | Required? | Purpose / failure mode when missing |
|---|---|---|---|
| `DATABASE_URL` | backend | **Required in production** | Turso/libSQL DSN (`libsql://<db>.turso.io`). Missing + `APP_ENV=production` → **fail-fast RuntimeError naming the variable** (no opaque 500s) |
| `TURSO_AUTH_TOKEN` | backend | **Required with libsql://** | Turso auth. Wrong/missing → `init_db()` fails at import with the new actionable log line |
| `APP_ENV` | backend | **Set to `production`** | Enables the production DB guard; also pins cookie security behaviour |
| `NVIDIA_API_KEY` | backend | Required for chat | Chat/voice replies fall back to the honest outage message; health reports `nvidia_configured: false` |
| `NVIDIA_MODEL`, `NVIDIA_MODEL_TAMIL` | backend | Optional | Defaults exist in code |
| `CORS_ORIGINS` | backend | Optional (same-origin deploy) | Only needed if the API is called cross-origin |
| `SEED_ADMIN_PASSWORD`, `SEED_AGENT_PASSWORD` | backend | First-run only | Seed accounts created by `init_db` on an empty DB; change after first login |
| `LOGIN_LOCKOUT_THRESHOLD/WINDOW_SECONDS/MINUTE_WINDOW` | backend | Optional | Lockout tuning (threshold clamped ≥ 1 — cannot be disabled) |
| `STT_PROVIDER`, `STT_API_KEY` (+ provider-specific) | backend | Optional | Server-side STT endpoint; the chat UI uses browser speech STT, so chat works without it |
| `TTS_PROVIDER`, `TTS_VOICE`, `TTS_VOICES`, `EDGE_TTS_*` | backend | Optional | TTS; default `edge-tts` (free, no key) |
| `SARVAM_API_KEY`, `SARVAM_*` | backend | Optional | Sarvam STT/TTS provider |
| `OPENAI_API_KEY`, `OPENAI_*` | backend | Optional | Staff lead-extraction endpoint |
| `COOKIE_SECURE`, `COOKIE_SAMESITE`, `COOKIE_DOMAIN` | backend | Optional | Cookie hardening (auto-secure in production) |
| `RATE_LIMIT_*`, `CHAT_RATE_LIMIT_*` | backend | Optional | Rate-limit tuning (see §7 caveats) |

`.env.example` now documents `TURSO_AUTH_TOKEN` and corrects the lockout
wording (threshold is clamped ≥ 1; it cannot be disabled). **No secret values
appear in any file or document.**

## 5. AI & speech reliability (per-request traces)

- **Chat**: browser → `POST /api/chat` (client timeout 32 s) → NVIDIA
  `POST https://integrate.api.nvidia.com/v1/chat/completions` (httpx timeout
  25 s read / 8 s connect; one retry on 5xx/connect errors only) → reply or
  **honest fallback** ("LykAI is having trouble reaching its service right
  now… try again in a little while"), in the reply language (Tamil variant for
  ta/mixed). No fabricated listings, no greeting-style masking.
- **Voice**: `POST /api/voice/respond` (32 s) → STT (Groq/Sarvam) and/or TTS
  (edge-tts default) with 25 s provider ceilings → clean 502 instead of a
  killed invocation.
- **Client**: every fetch carries an `AbortSignal` timeout; timeouts surface
  as a normal error the UI already renders ("Request timed out. Please try
  again.").
- All bounds fit the 30 s function cap: client 32 s > server budget 30 s >
  provider 25 s, so the server always decides the outcome before the client
  gives up, and the client gives up before a spinner looks hung.

## 6. Database reliability

- **Fail-fast guard** (`database.py`): `APP_ENV=production` + empty
  `DATABASE_URL` → `RuntimeError` naming the variable and the fix, instead of
  an opaque "attempt to write a readonly database" at first query.
- **`init_db()` wrapped** (`main.py`): failure logs an actionable hint
  (check `DATABASE_URL` + `TURSO_AUTH_TOKEN`) to Vercel function logs, then
  re-raises — import fails loudly, per-request 500 storms are replaced by one
  clear log line.
- Additive migrations only; no destructive DDL. **No writes were made to any
  production database by this work.**
- Seeding: production listings come from the `properties` table, which is
  seeded by an explicit manual CLI step (see deployment guide §6). Until run,
  `/api/properties` returns an empty list (chat search still serves the
  bundled dataset).

## 7. Rate limiting (analysis; smallest fix proposed, not implemented)

Current: in-memory token buckets keyed by client IP, with chat-specific
limits. Behind Vercel's proxy the connecting address is the proxy and each
function instance has its own counters (reset on cold start). Effective limits
are therefore per-instance and the key is ambiguous; blind re-keying (e.g.,
trusting `X-Forwarded-For`) risks letting clients spoof identities and defeat
the control entirely. Smallest reliable fix: move the limiter to a shared
store — e.g. **Upstash Redis** (`@upstash/ratelimit`-style sliding window,
keyed by XFF client IP parsed once, server-side) — a config-driven addition
that requires an account/secret, hence listed for approval rather than
silently implemented.

## 8. Performance (measured locally, 2026-10-27)

Local stack: uvicorn (fresh process, new code) + `vite preview` + Edge
headless. Warm = 2nd/3rd request on an established connection.

| Endpoint | Warm latency (3 runs) | Payload |
|---|---|---|
| `GET /api/health` (new) | 35–47 ms | 279 B |
| `GET /api/properties?limit=24` | 64–112 ms | 13.2 kB |
| `GET /api/properties/search?limit=20` (dataset) | 43–84 ms | 5.3 kB |
| `GET /api/auth/session` | 29–40 ms | 49 B |
| `GET /api/conversations` | 28–30 ms | 2 B (guest) |
| First call in a fresh process (dataset lazy-load + conn setup) | ~2.1–2.6 s one-time | — |

Frontend bundle (production build): `index-Ce3xmRR2.js` **291.66 kB**
(gzip 85.15 kB; previously 295.68 kB — dead client methods and homepage copy
removed), CSS **65.90 kB** (gzip 13.59 kB), build clean in ~19 s.

Saved-properties improvement (code-level): GET no longer rebuilds a 25k-entry
dict per request and POST no longer linearly scans the dataset — both are now
O(1) lookups on the cached id index (covered by existing integration tests).

Caveat: these are localhost numbers; production adds Vercel routing + Turso
network latency. Post-deploy, re-measure with the smoke-test guide and compare
against these baselines.

## 9. Firebase evaluation (objective, no migration recommended)

Question: would Firebase (Firestore + Auth) improve reliability over the
current FastAPI + Turso architecture?

- **What the app actually needs**: relational data (leads ↔ conversations ↔
  messages ↔ follow-ups ↔ recommendations with FKs, cascades, filtered
  indexes), RBAC with permission sets and step-up re-authentication, audit
  logging, and cookie sessions. All exist today, are test-covered (629 tests),
  and work.
- **What Firebase would add**: a second auth system (every existing account —
  agents, customers, seeded staff — would need migration or dual-login), a
  different data model (no relational joins/cascades; fan-out rewrites), a new
  vendor SDK in the request path, and new failure modes — while solving no
  measured problem: the production outages traced to routing and environment
  configuration (findings #1–#3), which Firebase would not have prevented on
  its own.
- **Conclusion**: not needed. Revisit only if a measured, recurring problem
  with the current DB (e.g., Turso availability) appears, with the migration
  cost weighed explicitly.

## 10. Remaining risks / user actions

1. **Nothing is deployed yet** — all changes are local and uncommitted. The
   production site keeps its stale behaviour until the user commits, pushes,
   and sets the env vars in §4.
2. **Verify Vercel function logs after deploy** — the new `init_db` logging
   turns the previously opaque `/api/*` 500s into one explicit line (e.g.,
   missing `DATABASE_URL`/`TURSO_AUTH_TOKEN`).
3. **Seed the production `properties` table** deliberately (guide §6) if the
   browse page should show DB-backed listings; until then it is empty by
   design (chat search still works via the bundled dataset).
4. **Live Turso could not be exercised from this Windows machine**
   (`sqlalchemy-libsql` has no wheel here) — the libsql path is covered by
   tests via the SQLite engine; production DB behaviour must be confirmed with
   the smoke tests after deploy.
5. Known low-severity items (conversations over-fetch, unbounded caches,
   rate-limiter store) are documented in §1/§7 for a later pass.
