# Production Deployment Guide — Lyka Realty

This guide reflects the state after the routing, reliability and cleanup work
(see `PRODUCTION_HEALTH_AUDIT.md`). **No commit, push or deploy has been
performed by the audit work** — the steps below are for the operator.

---

## 1. Before deploying

1. Review the pending diff (all changes are uncommitted by design):
   `git status` / `git diff` in the repo root. Expected: modified backend +
   frontend files, new `docs/PRODUCTION_*.md`, `backend/UAErealestate.json`
   (tracked rename from repo root), deleted orphan files
   (`CustomerAuth.jsx`, `LoginPage.jsx`, `server_entry.py`).
2. Run the verification suite locally:
   - Backend: `C:\Python310\python.exe -m pytest backend/tests/ -q`
     (expected: 629 passed, 2 skipped)
   - Frontend: `cd frontend && npm run build` (expected: clean build)
3. Commit and push the branch you want deployed (operator action).

## 2. Vercel project configuration

The project uses two services (`vercel.json`):

- `frontend` — static build of `frontend/` (SPA fallback rewrite → `index.html`)
- `backend` — Python, service root `backend/`, entry `app.main:app`, `maxDuration: 30`
- Top-level rewrite `"/api/(.*)"` sends API traffic to the backend service.

No changes are required to `vercel.json` for this release (the SPA-routing fix
is already in it and simply needs a deploy to take effect).

## 3. Environment variables (backend service)

Set these in Vercel → Project → Settings → Environment Variables. Values are
never committed to the repo; `.env.example` documents the names only.

| Variable | Required | Notes |
|---|---|---|
| `APP_ENV` | **Yes** | `production` — enables the fail-fast DB guard |
| `DATABASE_URL` | **Yes** | `libsql://<db-name>.turso.io` (your Turso DB) |
| `TURSO_AUTH_TOKEN` | **Yes** | Turso auth token for the database above |
| `NVIDIA_API_KEY` | Yes (chat) | Without it, chat returns the honest outage fallback and health reports `nvidia_configured: false` |
| `NVIDIA_MODEL` | No | Code default exists |
| `NVIDIA_MODEL_TAMIL` | No | Code default exists |
| `CORS_ORIGINS` | No | Only if the API is consumed cross-origin (same-origin deploy doesn't need it) |
| `SEED_ADMIN_PASSWORD` | First run | Seeds the admin account on an empty DB — change it after first login |
| `SEED_AGENT_PASSWORD` | First run | Seeds the agent account on an empty DB |
| `LOGIN_LOCKOUT_THRESHOLD` | No | Default 8; clamped ≥ 1 (lockout cannot be disabled) |
| `LOGIN_LOCKOUT_WINDOW_SECONDS` / `LOGIN_LOCKOUT_MINUTE_WINDOW` | No | Lockout tuning |
| `STT_PROVIDER` / `STT_API_KEY` | No | Server STT endpoint (chat UI uses browser speech STT and works without these) |
| `TTS_PROVIDER` / `TTS_VOICE` / `TTS_VOICES` / `EDGE_TTS_*` | No | Default `edge-tts` needs no key |
| `SARVAM_API_KEY` + provider keys | No | Alternate STT/TTS |
| `OPENAI_API_KEY` | No | Staff lead-extraction endpoint |
| `RATE_LIMIT_*` / `CHAT_RATE_LIMIT_*` | No | Tuning only (see health audit §7 for known limitations) |

Frontend service: no secrets, no `VITE_*` keys — the app calls relative
`/api/...` paths only.

## 4. Deploy

1. Push to the branch connected to Vercel (or press *Redeploy* on the latest
   deployment after the push).
2. Watch the backend function build: it must bundle `backend/UAErealestate.json`
   (~8 MB). If the file is missing from the commit, the dataset checks in the
   smoke tests will fail with `dataset_rows: 0`.

## 5. Post-deploy verification (first 5 minutes)

1. `GET https://<your-domain>/api/health` — expect HTTP 200 and:
   - `status: "healthy"`, `checks.database: "ok"`
   - `checks.property_data.dataset_rows: 25082` (confirms the dataset shipped)
   - `checks.property_data.db_listings: <n>` (0 until seeded — see §6)
2. If `/api/*` still 500s: open **Vercel → backend service → Logs**. The new
   startup logging prints one explicit line naming the missing/broken config
   (e.g., `DATABASE initialisation failed … Verify DATABASE_URL … and
   TURSO_AUTH_TOKEN`) instead of per-request 500s.
3. Run the browser checks in `PRODUCTION_SMOKE_TESTS.md`.

## 6. Database seeding (production, deliberate operator action)

The `properties` table drives `/api/properties` (browse). It is seeded by an
explicit CLI step — **never run data writes you haven't reviewed**:

```bash
# from backend/, with production DATABASE_URL/TURSO_AUTH_TOKEN exported
python -m app.seed_demo_properties     # 23 clearly-fictional demo listings
# or your real-estate import/seeder of record
```

- Until seeded, `/api/properties` returns an empty list; **chat property
  search still works** — it serves the bundled dataset, not this table.
- Demo listings are permanently badged "FICTIONAL DEMO" and are never mixed
  with real inventory.

## 7. Rollback

- Vercel: *Deployments* → promote the previous deployment (instant rollback).
- Env vars: keep the previous values documented in your secret store; the
  rollback needs no env changes (schema migrations are additive-only).

## 8. Local development (unchanged)

```bash
# backend
cd backend && C:\Python310\python.exe -m uvicorn app.main:app --port 8000
# frontend dev
cd frontend && npm run dev          # http://localhost:5173, /api proxied to :8000
# frontend production preview
cd frontend && npm run build && npm run preview   # http://localhost:4173
# one-click (Windows)
start.bat
```

Dev logins (development database only): `admin@lykarealty.ae` / `Admin@123`,
`agent@lykarealty.ae` / `Agent@123`. Production accounts are created from the
seed passwords above and must be rotated.
