# Production Smoke Tests — Lyka Realty

Run this checklist after every production deploy. Each step lists the URL and
the expected result. Steps marked **[prod]** only make sense against the
deployed site; **[local]** steps reproduce them locally (`start.bat`, or
uvicorn :8000 + `npm run preview` :4173). Local runs were executed and passed
on 2026-10-27 (see `PRODUCTION_CLEANUP_REPORT.md`); the same matrix must be
re-run **[prod]** after the user deploys.

Base: replace `https://<domain>` with your Vercel domain.

---

## A. Static hosting / SPA routing

| # | Check | How | Expected |
|---|---|---|---|
| A1 | Homepage loads | `https://<domain>/` | 200, hero headline "…just tell LykAI what you need", buttons *Talk to LykAI* / *Explore Properties*; **no** "Multilingual by design" cards, **no** star ratings/"300+", **no** "Live preview" card |
| A2 | Deep link | `https://<domain>/properties` | 200 (app renders, property records or an honest empty state) — NOT a platform 404 |
| A3 | Hard refresh on deep link | press F5 on `/properties` | Same as A2 |
| A4 | Property detail | open any listing → `/property/<id>` | 200, listing title/price/attributes, "Ask LykAI about this property" button |
| A5 | Chat page | `https://<domain>/chat` | 200, LykAI composer + conversations sidebar; status shows *Online* only if `/api/health` succeeds |
| A6 | Login/register | `https://<domain>/login`, `/register` | 200, Global Portal brand panel + form |
| A7 | Unknown route | `https://<domain>/this-route-does-not-exist` | 200 with the app shell (SPA fallback) — NOT a platform 404 page |
| A8 | Assets | homepage → DevTools Network | JS/CSS served with cache headers, no 404 assets, bundle name `index-*.js` |

## B. API (backend service)

Run from any browser/PowerShell. `[prod]` URL = `https://<domain>/api/...`,
`[local]` = `http://localhost:8000/api/...`.

| # | Check | Expected |
|---|---|---|
| B1 | `GET /api/health` | **200** · `status: "healthy"` · `checks.database: "ok"` · `checks.property_data.dataset_rows: 25082` (proves the dataset shipped) · `ai_config.nvidia_configured: true` · **no secret values anywhere in the body** |
| B2 | `GET /api/properties?limit=24` | 200 with a `results` array (empty until §6 seeding — that is an honest empty state, not an error) |
| B3 | `GET /api/properties/search?limit=20` | 200 with non-empty `results` (dataset search; independent of DB seeding) |
| B4 | `GET /api/auth/session` | 200 `{"authenticated":false,...}` when logged out |
| B5 | `GET /api/conversations` | 200 (empty list for guests) |
| B6 | `GET /api/auth/me` | **401** when logged out (expected, not a failure) |

## C. Auth flows (real logins)

| # | Check | Expected |
|---|---|---|
| C1 | Register a customer at `/register` | Account created, lands authenticated (HttpOnly cookie; **no token in localStorage**) |
| C2 | Customer login/logout via portal | Succeeds; logout clears session |
| C3 | Staff login (`admin@…` / seeded password) | Lands on the role landing page |
| C4 | Staff RBAC | Admin-only routes (e.g. `/admin/users` API) return **403** for non-admins |
| C5 | `/agent/dashboard` while logged out | Redirects to `/login` |

## D. Chat / AI (needs `NVIDIA_API_KEY`)

| # | Check | Expected |
|---|---|---|
| D1 | Send one chat message in English | Reply from LykAI with property cards when relevant |
| D2 | Send one message in Tamil | Reply in Tamil (model routing) |
| D3 | Provider failure (temporarily remove/rename the NVIDIA key, redeploy preview, or test locally with an invalid key) | **Honest outage message** ("LykAI is having trouble reaching its service right now…") — never a greeting-style canned reply, never invented listings; UI offers retry |
| D4 | Voice (optional) | Mic flow records, TTS speaks back; provider failure surfaces a clean error state, not a hung spinner |

## E. Performance spot-check

Compare `[prod]` timings against the local warm baselines
(`PRODUCTION_HEALTH_AUDIT.md` §8): `/api/health` 35–47 ms local,
`/api/properties?limit=24` 64–112 ms local, dataset search 43–84 ms local.
Production adds Vercel + Turso latency; investigate anything > ~2 s warm or
any cold-start failure (function logs).

## F. Failure-mode quick check

Stop the backend (locally) or block the API (prod DevTools → Network →
block `/api/*`, reload `/chat`): the chat status banner must show the offline
state and sends must fail with the timeout/error message — the page must not
spin forever and must not fabricate replies.

---

Notes
- The health endpoint is **`/api/health`** — a bare `/health` is a 404 by design.
- Any `dataset_rows: 0` in B1 means the dataset file did not ship with the
  backend bundle — check that `backend/UAErealestate.json` is committed.
- Console noise check: DevTools console must show no red page errors on
  `/`, `/properties`, `/property/<id>`, `/login`, `/register`, `/chat`.
  (An anonymous `GET /api/auth/me` → 401 in the Network tab is expected.)
