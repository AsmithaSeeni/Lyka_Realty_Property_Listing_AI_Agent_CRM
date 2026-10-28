# LykAI — AI Property Concierge by Lyka Realty (AI Agent + CRM)

A production-style, **two-tier** AI real-estate app for the UAE, powered by
**LykAI** (LYK = Lyka · AI = Artificial Intelligence) — Lyka Realty's AI
property concierge:

- **Customer side (public)** — LykAI chats like a human consultant
  (English · Tamil · Tanglish), searches a 25,000-property dataset
  deterministically, remembers each visitor's conversations, captures leads
  naturally, and supports voice. Customers only ever see **their own** chats.
- **Agent side (authenticated CRM)** — bcrypt + session-cookie login at
  `/agent/login`, then a role-scoped CRM: dashboard, searchable/filterable leads,
  full AI conversation transcripts, property recommendations, notes and
  pipeline status. Every `/api/agent/*` request is validated server-side.
  Customer and staff sessions are **fully separate** (different cookies,
  different tables, different endpoints) — a staff login never creates a
  customer identity and vice versa.

Backend: FastAPI + SQLAlchemy + SQLite. Frontend: React + Vite.

---

## Project structure

```
lyka_property_agent2/
├── .env                       # All API keys (never exposed to the frontend)
├── lyka_logo.png
├── start.bat                  # One-click startup (Windows)
│
├── backend/
│   ├── requirements.txt
│   ├── real_estate.db         # SQLite (auto-created + auto-migrated on start)
│   └── app/
│       ├── main.py            # FastAPI app: public API, auth, agent CRM API
│       ├── config.py          # .env settings loader
│       ├── database.py        # Models (Agent, Customer, Lead, Conversation,
│       │                      #   Message, PropertyRecommendation, AgentSession)
│       │                      #   + schema migration + seed CRM accounts
│       ├── ai/
│       │   ├── agent.py       # Conversation state, language detection, lead logic
│       │   └── nvidia_client.py  # NVIDIA LLM client + fallback replies
│       └── services/
│           ├── property_search.py  # Deterministic dataset search
│           ├── voice.py             # STT / TTS providers
│           ├── auth.py              # bcrypt, sessions, cookies, RBAC scope
│           └── leads.py             # AI lead upsert (dedupe) + serializers
│
└── frontend/
    ├── index.html
    ├── vite.config.ts         # Dev proxy: /api → localhost:8000
    └── src/
        ├── main.jsx / App.jsx # Router + layout (public vs agent chrome)
        ├── api.js             # API client (public + auth + agent)
        ├── index.css          # Premium UAE design + internal CRM design
        ├── pages/
        │   ├── LandingPage.jsx
        │   ├── ChatPage.jsx            # Chat + voice mode (own history only)
        │   ├── ConversationHistory.jsx # /history — the visitor's OWN past chats
        │   ├── SavedProperties.jsx     # /saved — saved listings (signed-in)
        │   ├── Profile.jsx             # /profile — customer profile
        │   ├── PropertiesPage.jsx      # /properties — optional manual browse
        │   ├── PropertyDetails.jsx
        │   ├── CustomerAuth.jsx        # /login + /register (optional, guests skip)
        │   └── LoginPage.jsx           # /agent/login — internal CRM sign-in
        ├── components/
        │   └── SavedGrid.jsx           # Shared saved-property cards
        └── agent/                      # Protected CRM (behind /agent/*)
            ├── AgentAuth.jsx          # Session guard + context
            ├── AgentShell.jsx         # Internal layout (rail + topbar)
            ├── AgentDashboard.jsx
            ├── AgentLeads.jsx         # Search / filter / sort list
            ├── AgentLeadDetail.jsx    # Profile + notes + full chat + recs
            └── AgentConversations.jsx # Business thread browser + drawer
```

---

## Prerequisites

- **Python 3.10+**
- **Node.js 18+** (npm included)
- Python packages in `backend/requirements.txt` (includes `bcrypt`)
- API keys in `.env` (already configured):
  - `NVIDIA_API_KEY` — the LLM brain
  - `STT_API_KEY` / `TTS_API_KEY` — optional, for server-side speech (see Voice)

---

## Quick start (Windows)

```bat
start.bat
```

This opens two windows:
1. **Lyka Backend** → FastAPI on `http://localhost:8000`
2. **Lyka Frontend** → Vite on `http://localhost:5173`

The browser then opens `http://localhost:5173`.

---

## Manual start

### 1. Backend

```bat
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

> ⚠️ Always run the backend from the `backend/` folder (module path `app.main:app`).

On startup the backend: creates missing tables, **migrates** old databases
(adds the new columns), and **seeds the CRM accounts** (once).

Verify: `http://localhost:8000/api/health` → `{"status":"healthy", ...}`

### 2. Frontend

```bat
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

> The Vite dev server proxies `/api/*` to `http://localhost:8000`, so no CORS
> setup is needed in development. Cookies (`lyka_customer`, `lyka_agent_session`)
> flow through the proxy exactly as in production (same-origin).

---

## Pages & routes

### Public (customer flow — conversation-first)

| Route | Page |
|---|---|
| `/` | Landing — one clear idea: *tell LykAI what you're looking for* (primary CTA **Talk to LykAI**, secondary **Explore Properties**) |
| `/chat` | LykAI chat (new conversation — resumes the active thread from sessionStorage) |
| `/chat/:id` | Reopen **your own** conversation with full context |
| `/properties` | Public browse of DB-backed listings — server-side filters (purpose, location, type, beds, price range), URL-persisted state, result counts, reset (Phase 6) |
| `/properties/:id` | DB-backed listing details (approved + available only; **Fictional Demo Listing** badges/disclaimers; **Ask LykAI** carries the listing as chat context via `/chat?ref=<id>&src=record`) |
| `/property/:id` | Legacy UAE-dataset listing details (unchanged behavior; `/chat?ref=<id>`) |
| `/login` | Optional customer sign-in (guests chat immediately — never required) |
| `/register` | Customer account creation (confirm-password field; links this guest's chats + saves) |
| `/history` | Signed-in customers: their conversations + saved properties. Guests first see a non-blocking *"Want to keep your LykAI conversations and saved properties?"* prompt (Sign In / Create Account / Continue as Guest) |
| `/saved` | Signed-in customer's saved properties (same friendly prompt for guests) |
| `/profile` | Lightweight customer profile (identity, counts, sign out) |

Nav: **Properties · LykAI · My Chats** plus **Sign In** (guests) or
**Profile** (signed-in). LykAI is the primary entry point; on phones the
fourth item collapses (My Chats carries the same sign-in prompt).

Customers are identified by an anonymous httpOnly cookie. The backend only
ever returns conversations owned by that cookie — one customer can never list
or open another customer's chat (foreign IDs return `404`, not `403`, so they
can't be probed either). Pre-migration conversations with no owner are
agents-only. Signing in **claims** the guest cookie's conversations (and saved
properties) onto the account, so nothing is lost when a guest registers.

### Staff CRM (separate portal, separate session)

| Route | Page |
|---|---|
| `/agent/login` | **Internal Lyka Realty CRM** staff sign-in (email **or** username + password; never shows credentials) |
| `/agent/dashboard` | Status counts, recent leads, recent conversations |
| `/agent/leads` | Lead list — search, status/location filters, sort, inline status |
| `/agent/leads/:id` | Customer profile, editable status & notes, complete AI conversation, all recommended properties |
| `/agent/conversations` | Business view of every thread in scope — search by customer/phone/email/lead#/conv#, date range, thread drawer |

`/crm` redirects to `/agent/login`. Unauthenticated visits to `/agent/*`
redirect to `/agent/login` (frontend convenience — the **backend**
independently rejects every request without a valid staff session, so the UI
guard is defence in depth, not the security boundary). The staff entry link
in the customer footer is deliberately subtle ("Staff login").

### CRM accounts (seeded on first run)

| Role | Login | Password (development default) | Scope |
|---|---|---|---|
| admin | `admin@lykarealty.ae` (or `admin`) | `Admin@123` | All leads & conversations |
| agent | `agent@lykarealty.ae` (or `agent`) | `Agent@123` | Leads assigned to them + the shared unassigned pool |

Override via `.env`: `SEED_ADMIN_EMAIL`, `SEED_ADMIN_USERNAME`,
`SEED_ADMIN_PASSWORD`, `SEED_ADMIN_NAME` (and the `SEED_AGENT_*` equivalents).
Passwords are stored as **bcrypt** hashes (cost 12); plaintext is never stored
or logged. **Production safety:** with `APP_ENV=production` the demo
passwords above are *never* used — a staff account is only seeded when its
`SEED_*_PASSWORD` is set explicitly, otherwise seeding is skipped with a
warning, so development credentials cannot silently become production
credentials. These accounts are **staff-only**: they live in the `agents`
table, are rejected by customer registration (`422` — staff emails are
reserved), and never appear as customer identities.

---

## API endpoints

### Public

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Health check (confirms LykAI is running) |
| POST | `/api/chat` | Chat message → AI reply + recommended properties (visitor-scoped; optional `property_id` + `property_source=dataset\|record` = listing the customer is viewing; no language parameter — the agent classifies each message itself and replies in that language) |
| GET | `/api/properties` | **Phase 6** public browse of DB-backed listings (approved + available only): `purpose`, `location`, `property_type`, `min_price`, `max_price`, `min_bedrooms`, `max_bedrooms`, `limit` (≤48), `offset` — all validated (422), deterministic price/id ordering, customer-safe fields only |
| GET | `/api/properties/record/{id}` | **Phase 6** one DB-backed listing, only while publicly eligible (identical `404` for unknown/unapproved/unavailable) |
| GET | `/api/properties/search` | Dataset search (`location`, `property_type`, price/bed/bath/area ranges, `limit`, `offset`) — legacy UAE JSON dataset |
| GET | `/api/properties/{id}` | Single dataset property (legacy UAE JSON dataset) |
| GET | `/api/conversations` | **Your** conversations (cookie-scoped; `[]` without one) |
| GET | `/api/conversations/{id}` | **Your** conversation + messages + recs (`404` if not yours) |
| POST | `/api/conversations` | Create a conversation (owned by the caller) |
| POST | `/api/voice/transcribe` | Audio file → text (STT) |
| POST | `/api/voice/respond` | Text → AI reply, voice channel (same pipeline) |
| POST | `/api/voice/synthesize` | Text → WAV audio (TTS) |

### Customer accounts (optional — guests never need to sign in)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/customer/me` | `{authenticated, email, name}` — never creates a cookie |
| POST | `/api/customer/register` | `{email, password, name?, confirm_password?}` → account + links this guest's conversations/saves (`409` if the email exists; `422` if it is reserved for staff or the confirmation doesn't match the password) |
| POST | `/api/customer/login` | `{email, password}` → session cookie, claims guest conversations (`401` generic on bad credentials) |
| POST | `/api/customer/logout` | Clear cookie — next chat is a fresh guest |
| GET | `/api/customer/saved` | Saved listings, each tagged `source: "dataset" \| "record"` (accounts only, `401` otherwise; rows that no longer resolve to a public listing are skipped) |
| POST | `/api/customer/saved` | `{property_id, source?}` → bookmark (idempotent; `source="record"` bookmarks a DB-backed listing and requires it to be publicly eligible, else `404`) |
| DELETE | `/api/customer/saved/{id}?source=dataset\|record` | Remove a bookmark (the id space is explicit, so equal numbers in different spaces never delete each other) |

### Auth & agent CRM (401 without a valid session — checked on **every** request)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/login` | `{username, password}` → session cookie + one-time bearer token |
| POST | `/api/auth/logout` | Revoke session, clear cookie |
| GET | `/api/auth/me` | Current agent (used for route guarding) |
| GET | `/api/agent/dashboard` | Real DB counts by status + priority + follow-up buckets, recent leads/conversations |
| GET | `/api/agent/leads` | `q`, `status`, `priority`, `intent`, `follow_up`, `location`, `property_type`, `assigned_agent_id`, `sort=newest\|interaction`, `limit`, `offset` (validated) |
| GET | `/api/agent/leads/{id}` | Profile + score/breakdown + follow-ups + linked account + conversations + recommendations |
| PATCH | `/api/agent/leads/{id}` | Status / notes / structured requirements / assignment — requirement changes re-score server-side |
| POST | `/api/agent/leads` | Phase 5: create from **reviewed, explicitly confirmed** details (409 on possible duplicates) |
| POST | `/api/agent/leads/{id}/follow-ups` | Phase 5: schedule a follow-up (label only — nothing is sent) |
| GET | `/api/agent/leads/{id}/follow-ups` | Phase 5: a lead's follow-ups (oldest due first) |
| GET | `/api/agent/follow-ups` | Phase 5: across scoped leads, `filter=all\|pending\|overdue\|due_today\|upcoming\|completed`, `lead_id` |
| PATCH | `/api/agent/follow-ups/{id}` | Phase 5: type/due/notes/completion/assignment |
| POST | `/api/agent/leads/{id}/recommendations` | Phase 5: re-score + match approved listings + deduplicated history save (`limit`, `save`) |
| GET | `/api/agent/conversations` | `q` (name/phone/email/lead#/conv#), `date_from`, `date_to` |
| GET | `/api/agent/conversations/{id}` | Full thread + recommendations + lead reference |
| POST | `/api/agent/leads/extract` | Phase 3: structured extraction of an enquiry (review-only, saves nothing) |
| POST | `/api/agent/leads/score` | Phase 4: deterministic scoring of a reviewed extraction (pure, no DB writes) |
| POST | `/api/agent/properties/match` | Phase 4: DB-backed matching/ranking of approved listings, ≤3 results (read-only) |

There is intentionally **no public lead endpoint** — the old `/api/leads*`
routes were removed. The AI creates/updates leads through a server-side
authenticated code path (`app/services/leads.py`). The Phase 3 extraction
endpoint is staff-only and **never writes to the database** — the agent
reviews/edits the extracted fields and explicitly confirms before the
Phase 5 create endpoint saves anything.

Interactive docs: `http://localhost:8000/docs`

---

## How LykAI works

1. **Language detection** — every message is classified as English, Tamil
   (script), Tanglish (romanized Tamil) or mixed, and the agent replies in
   kind. There is **no language selector**: the agent decides the reply
   language itself from each message (`ChatRequest` carries no language field;
   `reply_language` in the conversation state comes straight from detection),
   so Tamil/English/mixed input always gets the same language back.
   Deterministic strings (follow-up questions, fallback replies) are
   localized in all three variants, voice output follows the agent's own
   verdict (Tamil/mixed script → `ta-IN`, Tanglish → `en-IN`, English →
   `en-US`) and voice input listens in the conversation's language (browser
   locale before any reply). A deterministic **language-integrity net** sits
   behind this: if a Tamil/mixed turn ever comes back in English or with the
   model's reasoning leaked into the body, the reply is swapped for a Tamil
   announcement built from the real cards (count + min/max price + one
   question) — plain English or model self-talk never reaches the customer.
2. **Requirement extraction** — budget, location, bedrooms (incl. the common
   hyphenated *2-bedroom* spelling), buy/rent, purpose,
   timeline, and contact details (name/phone/email) are extracted from natural
   messages as the chat progresses.
3. **Deterministic search, announced naturally** — the AI never invents
   properties. The search runs **before** the reply, so LykAI knows its cards
   are attached and says things like *"I found a few properties that match
   what you're looking for"* (one question at a time, budget asked first) —
   the announcement directive is repeated on the reply's final prompt turn so
   the model's own pending clarifying question can never silence it.
   Cards attach only when the result differs from what is already visible, so
   the thread never floods with duplicates. Follow-ups like *"show me cheaper
   ones"* or *"what about 3 bedrooms"* re-run the search with the remembered
   criteria, and *"the second property"* is pinned **deterministically** to
   the exact numbered card the customer can see (English + Tamil ordinals,
   `#2` / `property 2` forms, out-of-range references refused) — the model
   can never answer about a listing from another thread. The opening reply
   always ends with a question, and when requirements are already known it
   asks for the single missing detail (usually budget) instead of the
   generic opener.
4. **Ask LykAI about a listing** — opening a property and tapping
   *Ask LykAI about this property* returns to the conversation with
   `/chat?ref=<id>`; the backend resolves that listing server-side and injects
   its real dataset row, so follow-ups like *"tell me more about this
   property"* are answered from actual data — the customer never types an id.
   The focus turn carries an authoritative disambiguation line, so *this
   property* is answered from that listing only, never from an earlier
   numbered card.
5. **Memory** — every message (with timestamp, detected language, text/voice
   channel) and every shared property is stored in SQLite. Reopening a
   conversation replays the history — property cards re-attach to the exact
   reply that introduced them — so the agent continues with the same context
   even after a server restart.
6. **Lead capture** — once requirements **and** contact details exist, a CRM
   lead is created or **updated** automatically. Matching is by phone (digits
   normalised, so `+971 52 123 4567` == `971521234567`) **or** email
   (case-insensitive), so the same customer never creates duplicates; the
   conversation is linked to the reused lead and `last_interaction_at` is
   refreshed. The ask itself stays conversational — no registration forms.
7. **Never invent data** — unknown lead fields are stored as `NULL` and
   surfaced to the CRM as **"Not provided"**. Only dataset fields ever appear
   in property cards.

### Dataset fields

`property_id, price, property_type, no__of__beds, no_of_baths, area, highlights, location`

Only these fields exist — the UI and search never show anything else.
Prices use Indian number formatting (e.g. `65,00,000`) and are parsed to numbers
for filtering.

---

## Performance (measured, not guessed)

LykAI's reply latency was benchmarked end-to-end (`POST /api/chat`) against
the live NVIDIA endpoint before and after the fixes:

| Scenario (e2e `/api/chat`) | Before | After |
|---|---|---|
| English enquiry | 52.0 s | **1.5–13.7 s** (typically 2–7 s) |
| Tanglish enquiry | 33.9 s | **1.7–12.9 s** (typically 2–5 s) |
| Tamil-script enquiry | 41.4 s | 18.7–73.6 s when the model responds; hard 120 s cap → localized fallback* |
| Dataset search (warm, per query) | 5.7–15.9 ms | **0.0–7 ms** |

\* Tamil keeps the reasoning pass on purpose — see below.

Root causes and fixes:

- **99.9% of the latency was hidden model "thinking".** The reasoner emitted
  600–5,000 invisible reasoning tokens before every answer. Fix:
  `chat_template_kwargs: {"enable_thinking": false}` is sent for
  **English/Tanglish** replies (measured 10–20× faster: 18–74 s → 1.4–7.4 s),
  while **Tamil/mixed keep thinking ON** — with thinking disabled the model
  measurably degrades on Tamil (instruction echo, switching to English
  mid-reply, stray scripts), which would violate the quality requirement.
  `auto`/unknown languages default to thinking ON (safe). The model itself is
  unchanged (`nvidia/nemotron-3.5-lightning-30b-a3b`).
- **Shared keep-alive HTTP client** (one `httpx.Client`, connect 10 s /
  read 120 s — same effective ceiling as before the changes) instead of a new
  connection per request, plus **one safe retry** on connect errors/5xx (never
  on read timeout — a slow model falls back to a canned reply instead of
  doubling the wait). If the LLM still fails, the fallback reply is localized
  (English or correct Tamil) and property cards still attach.
- **Precomputed search index** — property rows are parsed once at startup
  (`_search_index`), so filter/parse is sub-millisecond and property-id lookup
  is O(1). The dataset is never sent to the LLM: only the top matches (≤ 10)
  enter the prompt.
- **Streaming was evaluated and rejected on measurement**: the reasoner
  produces content in a burst at the end, so time-to-first-content ≈ total
  time — streaming would not improve perceived latency here.
- Timing is logged per request: `respond(): search X ms, llm Y ms` and
  `NVIDIA chat done in Zs (attempt, thinking, lang)`.

---

## Security model (two-tier separation)

- **Customer ↔ customer isolation** — anonymous visitor token in an httpOnly
  cookie (`lyka_customer`); every conversation query filters on its owner.
  A customer cookie never unlocks any `/api/agent/*` route.
- **Optional customer accounts** — bcrypt password hash on the `customers`
  row (guests have none). Signing in **claims** the guest cookie's
  conversations and saved properties onto the account (they're moved, not
  copied). Login failures return one generic `401`; registration returns
  `409` for an existing email. Logout clears the cookie and the next chat
  starts a fresh guest.
- **Agent auth** — bcrypt passwords + opaque session tokens (SHA-256 hashed at
  rest, 12-hour expiry, revocable server-side). Sent as an httpOnly cookie;
  `Authorization: Bearer` also accepted for API clients.
- **RBAC scope** — `admin` sees everything; `agent` sees leads assigned to
  them or in the shared unassigned pool, plus those leads' conversations.
  Out-of-scope IDs return `404`. Agents can self-claim; only admins can assign
  to someone else. Invalid statuses are rejected with `422`.
- **No secrets in the frontend** — all API keys live in `.env` on the server.

### Global login & enterprise RBAC (added)

One portal signs in every role (System Administrator, HR, Payroll, Real Estate
Agent, Sales Manager, Operations, Finance, Property Manager, Support, Customer).

- **Single entry point** — `/login` (also `/register`, legacy `/signin`) renders
  one portal. One form authenticates a **staff** account (email *or* username)
  or a **customer** account (email); the backend resolves which world the
  credential belongs to. `/agent/login` and `/crm` redirect here. There is **no
  role selector** — identity, roles and permissions come from the database,
  never from the client.
- **Unified session** — `GET /api/auth/session` returns the current identity
  (staff *or* customer) plus its roles, permissions and landing route;
  `{authenticated:false}` when anonymous. `POST /api/auth/portal-login` is the
  single submit endpoint (identical generic `401` for wrong password vs unknown
  account).
- **Central permission registry** — `backend/app/services/rbac.py`. Roles group
  permissions; permissions gate actions. The eight hard-coded
  `agent.role == "admin"` checks were replaced by permission checks with
  identical `404`/`403` behaviour. Reusable dependencies:
  `require_roles(...)`, `require_permissions(...)`, `ensure_permission(...)`.
  Multi-role is supported (`agent_roles` table; primary role stays in
  `agents.role`). Default landing: lowest-priority-number role wins.
- **Account lockout** — after `LOGIN_LOCKOUT_THRESHOLD` (default 8) consecutive
  failures on one existing account, locked for `LOGIN_LOCKOUT_MINUTES` (default
  15). Generic error either way (no lock oracle); counters reset on success.
- **Session revocation** — suspend, role change and admin password reset call
  `revoke_all_sessions()` so an open browser loses access immediately.
- **Provisioning & role management** — permission-gated `/api/admin/*` routes
  (`users.read/create/update/suspend`, `roles.read/manage`) with step-up
  password confirmation for high-impact changes, last-admin protection, and
  self-suspend prevention. Public registration can only ever create a *customer*
  account.
- **Audit log** — append-only `audit_log` table (login success/failure, logout,
  role change, suspension, staff creation, password reset). No route can modify
  or delete rows; reading needs `audit.read`. Passwords/tokens/bodies are never
  stored.
- **Honest scope** — HR, Payroll, Operations, Finance and Property-Manager
  *modules are not built*; those roles land on a clearly-labelled "not yet
  implemented" dashboard. **No employee, salary, payslip or attendance data is
  fabricated or stored.** Self-service password reset and MFA are **not**
  implemented (no mail transport / no TOTP); the supported recovery path is an
  audited administrator reset.

See `docs/GLOBAL_AUTH_AUDIT.md` (Phase 0 findings) and
`docs/GLOBAL_AUTH_IMPLEMENTATION.md` (what was built + limitations).

### Phase 1 hardening (added)

- **Rate limiting** — in-memory sliding-window limiter on the expensive
  endpoints: `POST /api/chat` (`CHAT_RATE_LIMIT`, default 60/min per IP),
  `POST /api/auth/login` + `/api/customer/login` + `/api/customer/register`
  (`AUTH_RATE_LIMIT`, default 15/min), all `/api/voice/*`
  (`VOICE_RATE_LIMIT`, default 30/min). Over-limit requests get `429` with
  `Retry-After` in the normal `{"detail": ...}` shape.
  > ⚠️ **Per process only**: counters live in this application process, reset
  > on restart, and are not shared between workers. This is basic
  > abuse-damping — **not a distributed production rate limiter**. For
  > multi-worker/production deployments put a real limiter in front (API
  > gateway / reverse proxy / Redis-backed limiter).
- **Request-size & input-length limits** — body > `REQUEST_MAX_BYTES`
  (default 5 MB) → `413`; chat `message` capped at `CHAT_MESSAGE_MAX_CHARS`
  (default 4000) and TTS `text` at `SYNTHESIZE_TEXT_MAX_CHARS` (default 5000)
  → `422`; audio uploads capped at `VOICE_UPLOAD_MAX_BYTES` (default 5 MB)
  → `413`. All rejected **before** any business logic/LLM call.
- **Global error handler** — unexpected exceptions return
  `{"detail": "Internal server error"}` (`500`, JSON): no stack traces, no
  exception text, no file paths in responses. Tracebacks are logged
  server-side only (code lines — never headers, cookies, keys or bodies).
- **CORS from configuration** — `CORS_ORIGINS` (comma-separated) with safe
  localhost defaults; `*` is rejected when `APP_ENV=production`.
- **Cookie flags** — `HttpOnly` + `SameSite=Lax` always; `Secure` follows
  `COOKIE_SECURE` (auto-`true` when `APP_ENV=production`).
- **`DEBUG`** — read from env, defaults to **off** (was hard-coded `True`).
- **Explicit database URL** — `DATABASE_URL` defaults to the *absolute*
  active path (`backend/real_estate.db`); the server can no longer open the
  stale repo-root `real_estate.db` by starting from a different working
  directory. Using any other database requires an explicit `DATABASE_URL`.
- **Voice endpoints stay customer-facing** — deliberately *not* staff-gated
  (any visitor may speak to the concierge); protected by rate + size limits.

### Phase 2 database & property data (added)

- **Additive schema migration** (existing mechanism in
  `backend/app/database.py`, idempotent & repeatable — no DB recreation):
  - `leads` +12 nullable columns for structured qualification
    (`original_enquiry`, `budget_min`, `budget_max`, `budget_currency`,
    `amenities`, `lead_score`, `priority`, `score_breakdown`,
    `missing_fields`, `clarification_questions`, `timeline_days`,
    `extraction_source`). Old rows keep `NULL` — scores are never fabricated.
  - `property_recommendations` +4 nullable columns (`match_score`,
    `match_reasons`, `match_mismatches`, `property_record_id` — a logical
    reference to `properties.id`; SQLite cannot add FKs via `ALTER`, so
    integrity is enforced in the service layer).
  - New tables: **`properties`** (verified purpose/availability/approval
    fields with CHECK constraints + filter indexes) and **`follow_ups`**
    (lead FK, optional agent FK, type CHECK, due-date index, ORM cascade).
  - Migrations run automatically at app startup (`init_db`), or manually via
    `python -c "from app.database import init_db; init_db()"` from `backend/`.
- **Dataset boundary (important)** — the 25,082-row `UAErealestate.json`
  dataset (kept in `backend/` so the deployed Vercel function ships with it)
  is **unchanged** and is **never** imported into `properties`, never
  assumed sale/rent/approved/available, and never sent whole to an LLM. The
  existing chat search (`search_properties`) is untouched; the new
  `search_property_records()` queries only the `properties` table with hard
  eligibility defaults (approved + available only, verified purpose only,
  empty result = empty — nothing is invented).
- **Fictional demo properties** — `backend/app/seed_demo_properties.py`
  seeds **23 clearly fictional** listings (Dubai Marina 5, Business Bay 4,
  Downtown Dubai 4, JVC 6, Dubai Hills Estate 4; sale 9 / rent 11 / lease 3;
  22 available + 1 reserved). Every row: `is_demo=True`, `source=demo_seed`,
  "Fictional Demo" in the title, "FICTIONAL DEMO LISTING" notice in the
  description, stable unique `external_ref` (idempotent — re-running creates
  nothing). Safe default target = the active local DB; any other target
  requires explicit `--database-url`. **Never runs at app startup.**

  ```bash
  cd backend
  python -m app.seed_demo_properties            # seed local dev DB
  python -m app.seed_demo_properties --dry-run  # preview only
  ```

- **Property CRUD service** — `backend/app/services/property_crud.py`
  (create/get/update/delete/list with validation & pagination). Approval
  changes require an explicit `allow_approval_change=True` gate that only
  staff routes (Phase 5/6) will pass; customer-facing paths cannot modify
  approval. Full authenticated CRUD API belongs to a later phase.

### Phase 3 structured lead extraction (added)

- **Isolated OpenAI client** — `backend/app/ai/openai_client.py` reads only
  the `OPENAI_*` settings (`OPENAI_API_KEY`, `OPENAI_MODEL` default
  `gpt-4o-mini`, `OPENAI_BASE_URL`, `OPENAI_TIMEOUT_SECONDS`,
  `OPENAI_MAX_RETRIES` clamped to 0–1). It uses the existing `httpx`
  dependency, retries transient failures (timeout/429/5xx) at most ONCE,
  never retries auth failures, never logs keys/headers/enquiries/response
  bodies, and raises structured safe errors (`missing_config`, `auth_error`,
  `rate_limited`, `timeout`, `provider_error`, `malformed_response`) instead
  of ever fabricating a result. The NVIDIA chat path is completely untouched.
- **Extraction service** — `backend/app/ai/lead_extraction.py` (Pydantic
  contracts). The model only proposes; deterministic code validates:
  enums (`buy|rent|lease|unknown`; known property types), numeric ranges,
  3-letter currency codes (never silently converted; no assumed AED),
  budget period only when stated (`monthly|yearly|one_time`, else a
  clarification question), timeline_days only when clearly implied, exact
  `original_enquiry` preservation (the model's echo is ignored), the enquiry
  fenced in `<enquiry>` tags as untrusted data, junk field types degraded to
  unknown, deterministic `missing_fields` + clarification questions, and
  per-field `provenance` (`explicit|inferred|unknown`). No scores, priorities
  or property records are ever produced here (Phase 4/5 own those).
- **Staff endpoint** — `POST /api/agent/leads/extract` (staff session
  required via the existing `get_current_agent` dependency; customers and
  anonymous visitors get `401`; rate-limited with the chat bucket).
  **Review-only: it creates/updates nothing.** Unconfigured key → safe `503`;
  provider failures → safe `502/503/504` with `{"message", "code"}` detail,
  never provider internals. Enquiry limited to 4000 chars (`422` beyond).
- **Tests** — `tests/test_phase3_extraction.py` (all provider calls mocked,
  no key needed) + `tests/test_phase3_live_openai.py` (optional, skipped
  unless `OPENAI_API_KEY` is configured; marked `live_openai`).

### Phase 4 deterministic scoring & matching (added)

- **Lead scoring** — `backend/app/services/lead_scoring.py` is pure Python
  (no DB, no network, no LLM): the model never assigns a score or priority.
  Fixed rubric → budget 20 · location 20 · type OR bedrooms 15 (one
  criterion, never both) · confirmed intent 15 · timeline 20/15/5/0 for
  ≤30 / 31–90 / >90 / unknown days (mutually exclusive bands, taken only
  from the validated `timeline_days` integer — free text is never parsed
  here) · essential preferences 10. **Essential-preferences rule (documented,
  no new category):** at least one amenity OR one non-amenity preference in
  the validated extraction. Maximum 100; priority High 70–100 · Medium 40–69
  · Low 0–39. Every criterion line explains awarded AND unawarded points,
  and a final invariant check rejects out-of-range totals, over-awarded
  criteria, breakdown/total mismatches, and inconsistent priorities.
- **Property matching** — `backend/app/services/property_matching.py` ranks
  ONLY Phase 2 database `properties` rows — never `UAErealestate.json`.
  **Hard eligibility before scoring:** approved + available + verified
  sale/rent/lease purpose + no conflict with a clearly stated buy/rent/lease
  intent + stated hard requirements the schema can validate (bedrooms and
  bathrooms must be ≥, property type exact after case/hyphen normalisation).
  Missing lead data never counts as a match. **Weights:** location 30 ·
  budget 25 · type/bedrooms 20 (12 type + 8 bedrooms) · amenities 15
  (matched-requested ratio) · preferences 10 (lead preference tokens vs
  property highlights) = 100, every component auditable in `breakdown`.
  Location scores exact 30 / containment 20 / else 0. Stable ordering
  (score DESC → price ASC → id ASC); top 3 by default, `limit` clamped 1–10.
- **Budget semantics (never assumed):** currencies are never converted — a
  mismatch or a missing lead currency scores 0 with an explicit note; rent
  and lease property prices are the YEARLY amount (the schema has no
  price-period column — documented limitation), so a rent/lease budget is
  compared only when the lead states `budget_period=yearly` (monthly or
  unspecified → 0 with a note, periods are never converted); unknown intent
  → 0; out-of-bounds prices score 0 with a mismatch. Missing **property**
  data (unreadable amenities, absent highlights) is reported in `data_gaps`
  — never counted as a match.
- **Staff endpoints** — `POST /api/agent/leads/score` (pure CPU, zero
  writes; client-supplied `lead_score`/`priority` fields are ignored) and
  `POST /api/agent/properties/match` (read-only; `limit` 1–10, default 3;
  empty results carry a clear “No eligible properties” explanation). Both
  reuse the existing `get_current_agent` staff dependency (anonymous and
  customer sessions → `401`), are Pydantic-validated (`422`), never call
  the provider, and never write to the database. Persistence stays a
  separate, explicit service function — `save_recommendations()` uses only
  existing Phase 2 columns (`property_record_id` = real `properties.id`,
  `match_score`, `match_reasons`, `match_mismatches`), never creates leads,
  and never touches customer/conversation records. No migration needed.
- **Tests** — `tests/test_phase4_scoring.py` (every rubric criterion, exact
  70/40 boundary classification, 100-point cap, invalid-timeline handling,
  spoofed score rejection, provider-isolation) and
  `tests/test_phase4_matching.py` (hard eligibility exclusions, intent/purpose
  conflicts, currency & price-period semantics, partial-weight arithmetic,
  stable tie-breaking, default/configurable limits, empty-result explanation,
  isolated temp-DB persistence with unrelated-table counts asserted unchanged,
  endpoint RBAC + no-secret-in-logs checks).

### Phase 5 lead CRM workflow (added)

The human-in-the-loop pipeline: chat → reviewed extraction → confirmed save →
server-side score → DB-backed matching → saved recommendations → scheduled
follow-ups → tracked in the CRM.

- **Lead creation (explicit, reviewed)** — `POST /api/agent/leads` is
  staff-only and accepts the **reviewed** Phase 3 extraction payload plus
  CRM fields. `confirm: true` is mandatory (422 otherwise) — there is no
  automatic lead creation from chat messages, and no LLM call happens in
  the save path. The payload deliberately has **no score/priority field**
  (extras ignored): score and priority are always recomputed by the Phase 4
  rubric. Validation and duplicate checks run before any write; the lead,
  its score, its conversation link and any adopted conversation
  recommendations commit in **one transaction** — any failure rolls the
  whole thing back (no partial leads), logging only the exception class
  (no PII).
- **Conservative duplicate policy** — `find_duplicate()` matches **phone
  first (normalised digits), then email (case-insensitive)**; name-only
  similarity never merges. A possible match returns `409` with a safe
  payload (`code=duplicate_lead`, `matched_by`, and the existing `lead_id`
  only when the caller may actually open it). Existing leads are never
  silently overwritten; `duplicate_override: true` explicitly creates a
  separate lead alongside the original.
- **Server-side score recalculation** — create always scores; `PATCH`
  re-scores whenever requirement fields change (intent, location, type,
  bedrooms/bathrooms, budget parts/period, amenities, preferences,
  timeline/days, original enquiry, requirements). The Phase 3
  `missing_fields`/`clarification_questions` are recomputed with the same
  deterministic logic. Client-supplied scores remain impossible to inject.
- **Structured PATCH** — the existing endpoint now validates budget
  min/max consistency, currency shape (3 letters, normalised upper-case),
  and conversation linking (a new link must be visible to the caller and
  unlinked — or already this lead's; explicit `null` unlinks). Assignment
  keeps its RBAC rules (agents → self, admins → anyone active).
- **List & dashboard from real queries** — `GET /api/agent/leads` gained
  validated filters (`priority` incl. `unscored`, `intent`, `follow_up`
  bucket via `EXISTS`, `property_type`, `assigned_agent_id`) with `422` on
  invalid params, stable ordering (id tiebreak) and honest pagination
  (`limit` 1–500, `offset` ≥ 0). The dashboard uses grouped SQL counts
  (`app/services/crm_stats.py`): status, priority (NULL → *unscored*), and
  pending follow-up buckets — **no hardcoded numbers**; agents only ever
  see their own + unassigned leads.
- **Follow-ups** — CRUD on the existing Phase 2 `follow_ups` table (no new
  table, nothing is ever *sent* — `type` is a label; no schedulers).
  **Timezone policy:** the DB stores naive UTC (project convention); the
  API accepts ISO-8601 (aware → converted, naive → read as UTC, never
  shifted) and serialises with an explicit `Z`. Buckets are UTC
  calendar-day partitions of pending rows: overdue (< today) · due today ·
  upcoming (≥ tomorrow); completed rows only under `completed`.
  Completing stamps `completed_at`; restoring clears it.
- **Recommendation persistence** — `POST /api/agent/leads/{id}/recommendations`
  re-scores the lead, matches approved+available listings, and saves **only
  history rows that don't exist yet for that lead** (repeat requests never
  duplicate; already-saved results come back flagged `previously_saved`).
  One transaction: score refresh + new rows commit together; a matching
  failure rolls everything back and leaves the (already valid) lead
  untouched. `save: false` is a dry run that only refreshes the score.
  Saving reuses the Phase 4 `save_recommendations()` service — existing
  columns only, no migration.
- **Storage mapping (no migration)** — budget period is round-tripped as a
  canonical token inside the existing `budget` display text ("per
  month"/"per year"/"one-time"; legacy text → parsed back or left as
  safe ambiguity); preferences are stored as a JSON array string inside
  `requirements` (legacy free text → empty list, never reinterpreted). The
  customer link is validated at create time and persisted through
  `conversations.customer_id` because `leads` has no customer FK
  (documented limitation, no invented columns).
- **Frontend** — `AgentLeads` gained priority/intent/follow-up filters, a
  score column and "Load more" pagination; new `/agent/leads/new` page
  implements paste → optional AI extract (review-only prefill with
  missing-field/question chips) → edit → **explicit confirm checkbox** →
  save, with a 409 duplicate panel (open existing vs. keep both);
  `AgentLeadDetail` gained the score panel with per-criterion breakdown,
  structured requirement editing (diff-only PATCH, re-scores on save),
  follow-up scheduling/completion, and a "Run matching" panel showing
  score/reasons/mismatches; the dashboard shows priority and follow-up
  cards. All reuses the existing `ax-*` design system.
- **Tests** — `tests/test_phase5_leads.py` (create/confirm/duplicates/
  override/name-only no-merge/transaction rollback/conversation linking/
  PATCH recalculation/filters/pagination/RBAC),
  `tests/test_phase5_followups.py` (CRUD, timezone conversion & bucket
  semantics, filters, assignment RBAC, unrelated-records-untouched),
  `tests/test_phase5_recommendations.py` (persistence, dedupe on repeat,
  approved+available hard rules, dry run, failure rollback without score
  leaks), `tests/test_phase5_dashboard.py` (exact counts on isolated
  per-test engines, agent scoping, endpoint consistency).

### Phase 6 public property browsing (added)

Two listing id spaces genuinely coexist in this project and were connected
without a migration or any change to legacy behavior:

- **UAE dataset ids (1–25,082)** — the original JSON dataset. All legacy
  flows (chat recommendation cards, conversation history, existing saved
  bookmarks, `/property/:id`, `GET /api/properties/{id}`,
  `GET /api/properties/search`) keep serving exactly the same rows.
- **DB-backed record ids (`properties.id`)** — the approved+available
  listings. The existing `/properties/:id` route alias (already used by the
  CRM's "Open listing" links) now resolves these via
  `GET /api/properties/record/{id}`, and the browse page
  (`/properties`) queries `GET /api/properties` — both backed by the Phase 2
  `search_property_records`/eligibility rules.

Because dataset ids and record ids numerically overlap, the URL alias
(`/properties/:id` vs `/property/:id`) and an explicit `source` /
`property_source` parameter select the space everywhere it matters (saved
bookmarks, chat focus); nothing is ever guessed from the number alone.

- **Browse page** — server-side filters (purpose sale/rent/lease, location
  containment, property type, min/max price, min bedrooms) with validated
  parameters (422 on junk), deterministic ordering (price asc, id asc),
  `total` result counts, offset "Load more" pagination, reset-filters, and
  filters persisted in the URL so returning from a detail page restores the
  result set. Cards show only real fields: title, location, purpose badge,
  honest price + period (`/ year` for rent/lease per the established
  convention, plain amount for sale, "Price period not specified" when a
  period is unknown — never converted, never assumed), beds/baths/area,
  and a **Fictional Demo Listing** badge on every `is_demo` row. The
  database has no photos, so cards keep the branded placeholder — no
  images are invented.
- **Detail page** — loads by the actual property id; unknown, unapproved
  or unavailable records all get a friendly not-found state (the API
  returns an identical 404 for each, so private inventory cannot be
  probed). Shows title, listing id, location, purpose, price + period,
  type, beds/baths/area, description, amenities, highlights, availability,
  demo disclaimer, and the enquiry action. Internal governance fields
  (`is_approved`, `source`, `external_ref`, timestamps) are never exposed.
  The legacy dataset detail rendering is preserved unchanged.
- **Enquiry integration** — "Ask LykAI about this property" navigates to
  `/chat?ref=<id>&src=record`; the chat endpoint resolves the focus
  listing server-side with the same public eligibility rule and maps it
  into the dataset-shaped focus payload the NVIDIA agent already
  understands (`record_focus_dict`) — **no agent, prompt, or provider
  changes**. An ineligible record resolves to *no* focus, so the assistant
  can never claim an unverified listing is available. No lead is created
  by viewing or enquiring (asserted by test and live check). English/
  Tamil/Tanglish/mixed behavior is untouched.
- **Saved properties** — the single `saved_properties.property_id` column
  now serves both spaces through a documented reserved-range encoding
  (record bookmarks are stored as `1,000,000 + id`; the dataset's maximum
  id is 25,082, so collision is impossible and every legacy row keeps its
  stored value). Saves of `source="record"` require public eligibility;
  the saved list decodes both spaces and tags each row with `source`, and
  unsaving targets one space explicitly. No schema migration was added.
- **Tests** — `tests/test_phase6_public_properties.py` (46 tests): public
  listing eligibility/filters/pagination/validation/demo-disclaimer/no-
  internal-fields, detail not-found semantics + honest price periods,
  legacy dataset endpoint regression, both-space saved-property behavior
  (round-trip, reserved-range storage, idempotency, per-space unsaving,
  cross-customer isolation, ineligible-skip), and chat focus wiring with a
  faked agent (record/dataset focus, invalid source rejection, no lead
  created, voice forwarding).

### Phase 7 CRM integration & end-to-end validation (added)

End-to-end validation of the customer and agent journeys, plus fixes for
the two confirmed integration defects:

- **Defect 1 — record-space chat focus leaking into dataset card lists.**
  A DB-record listing opened via "Ask LykAI" was prepended into the agent's
  shared recommendation list, where its id lives in a different id space.
  Refinement replies ("cheaper ones", "marina options") could then return
  it as a *dataset* card, persisting a record id into the dataset-keyed
  `property_recommendations` table (wrong listing links) and colliding
  with same-numbered dataset ids in the card dedupe/numbering. Fixed by
  keeping record-space focus strictly per-turn (it keeps its authoritative
  focus context); dataset-focus behavior is unchanged, and the chat
  persistence layer now also skips any record-marked card as defense in
  depth.
- **Defect 2 — fictional demo listings presented without honesty.** The
  focus payload carried no demo marker, so the assistant could describe a
  fictional demo listing as real Lyka Realty inventory. `record_focus_dict`
  now carries `is_demo`/`source`, and the agent's deterministic context
  block adds an explicit honesty instruction for demo focus listings — no
  prompt rewrite, no provider change. Verified live: the assistant now
  answers "this is a fictional demo listing … not a real, verified, or
  currently available Lyka Realty property".
- **CRM link fix** — the lead-detail "Open listing" link resolved every
  recommendation through the record URL, including chat-era dataset rows
  (`property_record_id` NULL), which opened a same-numbered listing from
  the wrong id space. Links now resolve per space (`/properties/:id` for
  saved matches, `/property/:id` for dataset rows).
- **Journeys verified** (automated on the throwaway DB): customer browse →
  detail → chat focus → register → save → return → unsave with zero CRM
  writes; cross-customer isolation of saves/conversations; guest chat
  claimed on registration; full agent workflow (create with explicit
  confirmation → dashboard → status → follow-up → recommendations run
  twice without duplicating history → reopen/persist) with RBAC (agent
  sees the unassigned pool + own leads, loses access once assigned away,
  `404` without detail leaks, `401` anonymous, `422` invalid status,
  `409` phone duplicates never merging by name) and dashboard-vs-database
  count agreement.
- **Live smoke** (16/16): browse/detail/demo regressions, two real NVIDIA
  turns (demo-honesty answer; "cheaper" refinement returning dataset-only
  cards), read-only staff CRM checks (dashboard total == DB leads, status
  buckets sum to total), no lead/follow-up writes, stale root DB hash
  unchanged, server log free of secrets.

---

## Voice

**In the browser (works out of the box):**
The chat page's 🎙 voice mode uses the Web Speech API —
speech recognition for input and speech synthesis for replies, with
listening → thinking → speaking states, mute, live transcript, and an
end button. Voice turns are stored with `message_type: "voice"` and share the
exact same conversation state as text. Best in Chrome / Edge over
`http://localhost` (mic requires a secure context; localhost qualifies).

**On the server (optional):**
`/api/voice/transcribe` and `/api/voice/synthesize` call the providers set in `.env`:

```env
STT_PROVIDER=groq          # or openai / nvidia
STT_MODEL=whisper-large-v3-turbo
STT_API_KEY=...            # must match the provider (gsk_... for Groq)

TTS_PROVIDER=sarvam        # or edge-tts / nvidia / openai
TTS_MODEL=bulbul:v4-flash
TTS_VOICE=neha_mr_narration
SARVAM_API_KEY=...
```

> Note: For high-quality Indian English speech synthesis, Sarvam AI's `bulbul:v4-flash`
> model with `neha_mr_narration` voice is the primary TTS provider (24000 Hz sample rate, pace 1.0).
> Free Edge-TTS (`ta-IN-PallaviNeural` / `en-IN-NeerjaExpressiveNeural`) is available as a zero-key alternative.

---

## Configuration (`.env`)

```env
NVIDIA_API_KEY=nvapi-...
NVIDIA_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b
STT_PROVIDER=...
STT_MODEL=...
STT_API_KEY=...
TTS_PROVIDER=sarvam
TTS_MODEL=bulbul:v4-flash
TTS_VOICE=neha_mr_narration
SARVAM_API_KEY=your_actual_key_here
# Optional CRM seed overrides (defaults shown — development only; see below)
SEED_ADMIN_EMAIL=admin@lykarealty.ae
SEED_ADMIN_USERNAME=admin
SEED_ADMIN_PASSWORD=Admin@123
SEED_ADMIN_NAME=Lyka Admin
SEED_AGENT_EMAIL=agent@lykarealty.ae
SEED_AGENT_USERNAME=agent
SEED_AGENT_PASSWORD=Agent@123
SEED_AGENT_NAME=Sales Agent
# Production: set APP_ENV=production and supply SEED_*_PASSWORD explicitly;
# without them no staff accounts are seeded (demo passwords never apply).
APP_ENV=development

# --- Phase 1 security settings (safe defaults; see “Security model”) ---
DEBUG=false
CORS_ORIGINS=                  # empty = localhost:5173/8000 defaults; no "*" in production
DATABASE_URL=                  # empty = active backend/real_estate.db (absolute path)
RATE_LIMIT_ENABLED=true
RATE_LIMIT_WINDOW_SECONDS=60
CHAT_RATE_LIMIT=60
AUTH_RATE_LIMIT=15
VOICE_RATE_LIMIT=30
REQUEST_MAX_BYTES=5242880
VOICE_UPLOAD_MAX_BYTES=5242880
CHAT_MESSAGE_MAX_CHARS=4000
SYNTHESIZE_TEXT_MAX_CHARS=5000
COOKIE_SECURE=                 # empty = automatic (true when APP_ENV=production)

# --- Serverless deployment (Turso / libSQL — see “Deploying to Vercel”) ---
# Only used when DATABASE_URL is a libSQL URL. Never commit the real value.
DATABASE_URL=libsql://<db-name>-<org>.turso.io
TURSO_AUTH_TOKEN=

# Reserved for the future OpenAI lead-extraction phase (not read yet):
OPENAI_API_KEY=
OPENAI_MODEL=
```

The backend loads `.env` from the repo root — the frontend never sees these
values. `.env` is gitignored; keep real credentials only there (copy
`.env.example` and fill in placeholders).

---

## Deploying to Vercel

The deployed architecture is **two platforms behind one domain**:

| Piece | Platform | Configuration |
|---|---|---|
| Frontend (Vite static SPA) | Vercel — project **Root Directory: `frontend`** | `frontend/vercel.json` |
| Backend (FastAPI) | Render (`https://lyka-realty-property-listing-ai-agent-crm.onrender.com`) | Render dashboard (env vars, logs) |

`frontend/vercel.json` is the only Vercel config in the repo, with two
ordered rewrites:

1. `"/api/:path*"` → the Render backend (same-origin in the browser, so no
   CORS setup is needed);
2. `"/(.*)"` → `"/index.html"` — the SPA fallback, so deep links and
   refreshes (`/properties`, `/chat`, `/login`, …) serve the app instead of
   Vercel's edge 404. Vercel checks the filesystem first and matches
   rewrites in order, so `/assets/*` files and `/api/*` are never
   intercepted by it.

The frontend calls relative `/api/*` paths only, so no frontend code changes
were needed for either platform. The former root `vercel.json` (a Vercel
Services topology that would have hosted FastAPI **on Vercel**) was removed:
it contradicted the FastAPI-on-Render architecture and was never active —
the project's Root Directory is `frontend`, so only `frontend/vercel.json`
is read.

### Database: local SQLite won't work on Render

Render's free-tier disk is **ephemeral** — the default SQLite file
(`backend/real_estate.db`) is wiped on every redeploy or restart, so
accounts, sessions, leads and conversations would be lost. Point
`DATABASE_URL` at a hosted Turso database instead; the SQLAlchemy models,
queries and migrations are unchanged.

```bash
turso db create lyka-realty
turso db show lyka-realty --url        # -> DATABASE_URL=libsql://...
turso db tokens create lyka-realty     # -> TURSO_AUTH_TOKEN
```

`init_db()` still runs at startup, so tables and indexes are created on the
hosted database automatically. For production also set `APP_ENV=production`
(cookies become `Secure`; API docs are disabled) and `CORS_ORIGINS` to your
real domain.

> **Driver platform note:** `sqlalchemy-libsql` ships wheels for Linux and
> macOS only — Render's runtime is Linux, so it installs there. Local
> Windows development keeps using SQLite (the default when `DATABASE_URL` is
> unset) and does not need the package.

### Environment variables (set in the Render dashboard)

`.env` is gitignored and never deployed, so set these on the Render service:
`NVIDIA_API_KEY`, `STT_PROVIDER`, `STT_API_KEY`, `TTS_PROVIDER`, `TTS_VOICE`,
`DATABASE_URL`, `TURSO_AUTH_TOKEN`, `APP_ENV=production`, `CORS_ORIGINS`, and
`SEED_ADMIN_PASSWORD` / `SEED_AGENT_PASSWORD` — production seeding **refuses**
to use the demo passwords, so no staff account is created without them.

The Python runtime must be **3.10** to match `requirements.txt`.

---

## Tests (backend)

Pytest suite with a **throwaway SQLite database** (the live
`backend/real_estate.db` is never touched — `tests/conftest.py` points
`DATABASE_URL` at a temp file before the app is imported):

```powershell
cd D:\lyka_property_agent2\backend
python -m pytest tests -q
```

Covers: configuration with missing optional env vars · `DATABASE_URL`
defaulting to the active DB from any CWD · NVIDIA config/payload/thinking
regression · rate-limit units + wiring + live `429` · request-size and
input-length rejections (`413`/`422`) · CORS origin behaviour · safe global
error responses (no tracebacks/secrets) · staff/customer auth, RBAC scoping
and session separation · voice endpoints (customer-usable, rate-limited,
error mapping) · `.env.example` placeholders-only + gitignore hygiene.

Phase 2 adds: migration on a **disposable copy** of the live DB (row counts
and old rows preserved, repeat-safe, live file hash never changes during the
test) · fresh-DB init · `properties`/`follow_ups` schema, CHECK constraints
and indexes · sale/rent/lease separation · unapproved/unavailable exclusion ·
unknown-purpose rejection · Indian-style price normalisation (`65,00,000`,
`AED 750,000`) · JSON-dataset search regression · demo seed (≥20 fictional
rows across the 5 communities, idempotent re-run, demo/fictional labelling,
reserved row excluded from eligible matches, no customer data) · lead /
recommendation / follow-up model behaviour (old rows readable, NULL scores)
· property CRUD validation and the approval-change gate.

Phase 3 adds: extraction contracts and normalisation (enums, currency and
period rules, provenance, junk-input degradation) · deterministic
missing-fields/clarification logic · mocked provider success/retry/error
paths · staff-only `401/422/503` handling · log/caplog assertions that keys
and enquiries never appear · the optional live OpenAI test (skipped without
a key).

Phase 4 adds: the full scoring rubric with exact High/Medium/Low boundary
and 100-point-cap assertions · spoofed client scores being ignored ·
provider-isolation proof for scoring/matching · hard eligibility (unapproved,
unavailable, unknown purpose, intent/purpose conflict, bedrooms/bathrooms/
type) · currency mismatch, monthly-vs-yearly, unspecified-period and
out-of-bounds budget cases · exact partial-weight arithmetic (amenities 15,
preferences 10) · stable equal-score ordering · default 3 / clamped 1–10
limits · empty-result explanations · isolated temp-DB recommendation
persistence (accurate `property_record_id`/scores, invalid references
rejected, unrelated table counts unchanged) · endpoint RBAC (`401`
anonymous + customer, `422` junk/limit) and no-secrets-in-logs checks.
Service tests use their own per-test SQLite file, so they can never observe
rows created by other tests — and never the live database.

Phase 5 adds: lead creation only through explicit confirmation (`422`
without it, spoofed score fields ignored) · phone-first/email-second
duplicate conflicts with safe payloads · override creating a *separate*
lead without touching the original · name-only never merging · customer/
conversation reference validation · full-transaction rollback on failure
(no partial rows, links undone) · deterministic re-score after requirement
PATCHes with currency/period/preferences round-trips · list filters,
validated pagination and stable ordering · agent scoping on every route
(list/detail/PATCH/follow-ups/matching) · follow-up CRUD with timezone
conversion (aware → UTC, naive read as UTC) and UTC day-bucket semantics ·
recommendation runs saving once and never duplicating history (repeat +
dry-run cases), matching failures rolling back the score refresh ·
dashboard exact-count assertions on isolated per-test engines (empty DB,
status/priority partitions, follow-up buckets, admin-vs-agent scoping).
All endpoint tests use unique synthetic contacts per test, so they stay
correct as the shared throwaway database grows.

Phase 6 adds: public listing eligibility (approved + available only;
unapproved/sold/reserved/off-market excluded) · purpose, location, price
and bedroom filters · deterministic pagination with id tiebreak · 422 on
invalid parameters · demo rows keeping their fictional disclaimers ·
detail pages returning an identical 404 for unknown/unapproved/unavailable
records and never exposing internal governance fields · honest per-purpose
price periods · legacy dataset endpoint regression (shape + ids
unchanged) · saved properties across both id spaces (reserved-range
storage, idempotent saves, per-space unsaving, cross-customer isolation,
guest 401, ineligible rows skipped) · chat focus wiring with a faked
agent (record focus from an eligible listing, no focus for an ineligible
one, invalid source 422, dataset focus preserved, voice forwarding) and
proof that browsing/enquiring creates no CRM lead. All 46 tests run on the
throwaway test database; the live NVIDIA path was verified separately with
a single manual chat turn.

Phase 7 adds: full customer journey (browse → detail → chat focus →
register → save → return → unsave) with conversation survival and zero
lead creation · cross-customer isolation of saves and conversations ·
guest-chat claiming on registration · full agent CRM workflow (explicit-
confirmation create, dashboard, status PATCH, follow-up create/list,
recommendation runs twice with identical saved-row counts, reopen
persistence) · RBAC boundaries (pickup pool, assignment revocation with
`404` and no detail leak, anonymous `401`, invalid-status `422`,
duplicate-phone `409` without name merging, single-lead invariant) ·
dashboard counts compared against direct database counts · and regression
tests for the two Phase 7 fixes: record focus never entering the shared
recommendation list or the persisted cards (agent-level and API-level),
and the demo honesty marker present for demo focus but absent for real
and dataset focus. All provider calls are faked or bypassed.

### Phase 9 SQLite connection safety & integrity hardening (added)

Phase 8's audit (see `docs/PHASE8_PRODUCTION_READINESS_AUDIT.md`) found that
SQLite foreign-key enforcement was off and write contention was unmanaged.
Phase 9 adds a **per-connection safety contract** (`apply_sqlite_pragmas` in
`app/database.py`, registered as a SQLAlchemy `connect` hook for SQLite
engines only — other dialects are untouched):

- **`PRAGMA foreign_keys=ON` on every new connection** (app, tests,
  migrations). Pre-change read-only audits of the working database found
  **0 `foreign_key_check` violations and 0 orphans** across all ten FK
  relationships, and the full suite passes unchanged under enforcement.
  Nullable relationships (legacy NULL-customer conversations, unassigned
  leads) remain legal.
- **Explicit busy timeout** (`SQLITE_BUSY_TIMEOUT_SECONDS`, default 5 s) set
  both as the sqlite3 connect `timeout` and as a PRAGMA — no blind retries
  were added anywhere.
- **WAL journal mode by default** (`SQLITE_JOURNAL_MODE=wal`; allowlisted
  values only, unknown values ignored) so readers never block the single
  writer. `synchronous` stays **FULL** — durability is not weakened. The
  mode persists per database file and takes effect on the working database
  the next time the app opens it (no data is rewritten; automated tests only
  ever set it on temporary databases).
- No schema changes, no data rewrites, no unique constraints added
  (saved-property uniqueness stays service-enforced pending an approved
  migration; `leads.phone` stays intentionally non-unique for the explicit
  duplicate-override workflow).

Tests (`tests/test_phase9_sqlite_safety.py`, 13): FK enforcement verified on
freshly opened connections and the session factory · invalid conversation/
follow-up/saved/recommendation references rejected by the database ·
nullable legacy shapes still accepted · busy timeout applied and configurable
· WAL verified on temp databases with configurability and invalid-value
fallback · migrations + init idempotent under enforcement (twice) ·
durable `synchronous` untouched · dual-space save/unsave, eligibility 404s,
demo-honesty context guard, and lead/dashboard workflows all pass under
enforcement.

### Phase 10 test & CI hardening (added)

**Running the normal suite (fully offline, no keys required):**

```
cd backend && python -m pytest tests -q      # backend
cd frontend && npm run build                 # production build check
```

**Live provider tests are opt-in only.** Tests marked `live` or
`live_openai` are skipped by a `tests/conftest.py` collection hook unless
`RUN_LIVE_TESTS=1` is deliberately set — this holds even when an API key
happens to exist in the environment or `.env`. A second, independent guard
inside `tests/test_phase3_live_openai.py` skips when `OPENAI_API_KEY` is
missing, so opting in without credentials is still a clear skip, never a
network attempt. Skip reason: *"live provider test — set RUN_LIVE_TESTS=1
(and provide the API key) to run it; default runs are fully offline."*

**Provider tests are mocked** in `tests/test_phase10_nvidia_failures.py`:
a guard fixture replaces the shared httpx client with one that raises on any
unscripted call, so the real NVIDIA endpoint cannot be reached; scripted
fakes cover success (preamble scrubbing, token-cap tail trim), HTTP 429 (no
retry), 5xx (exactly one retry), connect errors/timeouts (retry then canned
fallback), read timeout (no retry), invalid JSON / empty or missing
`choices` (fallback), empty or whitespace-only replies (Phase 10 fix:
fallback, never a blank bubble), missing key (fallback with zero calls),
secret-leak checks against customer text and logs, and the honesty promise
that fallbacks quote no prices, numbers, or availability claims.

**New Phase 10 tests (4 files, 60 tests):** NVIDIA failure paths (21) ·
language-detection matrix for English / Tamil script / Tanglish / mixed,
short, empty, and ambiguous inputs with documented limitations (23) ·
guardrail regressions — anti-hallucination prompt strings, zero-match search
yields no cards, demo honesty context, customer↔agent and agent↔agent CRM
isolation (leads *and* follow-ups), auth-before-provider ordering (401
anonymous / structured 503 staff), dataset↔record id-space separation for the
same numeric id, unapproved-record save eligibility (9) · live-opt-in
mechanism contract (7). Two minimal production fixes: blank provider replies
now fall back instead of surfacing empty, and the Tanglish (`ta-Latn`)
canned fallback uses the Tamil reply (English behavior unchanged).

**CI** (`.github/workflows/ci.yml`) runs on pushes to `main` and on pull
requests: a backend job (Python 3.10, `pip install -r backend/requirements.txt`,
`python -m pytest tests -q` with no secrets and `RUN_LIVE_TESTS` forced off)
and a frontend job (Node 20, `npm ci` from the committed lockfile,
`npm run build`). No deployments, no database uploads, no secret printing,
no real provider calls; the workflow fails if tests or the build fail.

**Remaining gaps:** the live OpenAI extraction smoke test still needs a real
`OPENAI_API_KEY` plus `RUN_LIVE_TESTS=1` (never in CI); server-side STT/TTS
voice remains unverifiable with current keys; the NVIDIA tests assert the
client's documented behavior against scripted fakes, not against the live
endpoint (a live NVIDIA smoke test does not exist yet).

---

## Verification performed

- **Two-portal architecture & identity separation (85 live checks):** guest
  chat with no account · dataset search returns real rows · **staff login
  page exposes no credentials** (no dev hint, no staff-email placeholder,
  labelled *Internal Lyka Realty CRM*) and `/agent/login` · `/login` +
  `/register` + `/saved` + `/profile` serve customers · **root-cause
  regression**: no staff/customer email overlap in the DB (the leaked
  `admin@lykarealty.ae` customer row is an anonymous guest again), staff-email
  registration → `422`, staff credentials → customer login `401` · customer
  A/B isolation for conversations *and* saved properties · staff session sees
  zero customer data (`me` guest, `[]`, `401`, foreign conversation `404`) ·
  customer session → `401` on every CRM endpoint · cookie separation
  (`lyka_agent_session` vs `lyka_customer` — each logout leaves the other
  portal's session intact, and revokes its own) · logout closes protected
  customer endpoints · guest→account claiming only from the caller's own
  guest cookie (a fresh sign-in rotates the session token) · admin/scoped
  agent login + RBAC scope · DB counts intact · mobile nav media queries.
- **Conversation-first journey (78 live HTTP + UI checks, all passing):**
  browse search pagination (`limit`/`offset`) · guest chat → follow-up →
  property cards with dataset fields only · ordinal reference (*"the second
  property"*) grounded in the real listing · focus-property chat
  (`property_id` from the details page) grounded in that listing · messages +
  per-message recommendation ids persisted · customer register (guest chats
  claimed) · signup confirm-password mismatch → `422` with **no** account
  created, matching confirmation accepted · duplicate register → 409 · bad
  login → 401 · saved properties
  (idempotent save/list/delete, guest → 401) · login from another browser
  claims its guest chats · logout → empty scope · all routes in OpenAPI ·
  voice pipeline reuse · landing/browse/sign-in/details/chat/history UI copy.
- **Announcement behaviour (15 checks):** no cards before the budget question
  · fresh search → cards **and** a reply that announces the matches ·
  later turns attach no duplicate cards · exactly one reply carries cards ·
  ordinal + focus answers grounded.
- **Agent CRM regression (56 live HTTP checks):** wrong/unknown credentials →
  401 · login by email and username · cookie and bearer auth ·
  `/api/auth/me` · customer A/B isolation (own list only, foreign conversation
  → 404, orphan threads hidden) · dashboard counts · lead
  list/search/filters/sort · lead detail with conversations + recommendations ·
  PATCH status (valid, invalid → 422) · agent conversation search, date range,
  thread view · RBAC scoping (agent cannot see/patch an admin-assigned lead →
  404, cannot assign to others → 403) · same-phone chat reuses the existing
  lead (no duplicate) · logout revokes the session (subsequent calls → 401).
- **Branding (43 checks):** health/OpenAPI/HTML/README/modules say **LykAI**
  (never the old names, never all-caps `LYKAI`).
- **Through the Vite dev proxy (14 checks):** identical behaviour with real
  cookie flow — customer cookie never opens agent endpoints.
- **Frontend:** `npm run build` compiles clean; every route serves; all agent
  modules transform without errors.
- **Speed + language fixes — new permanent suite `test_speed_lang.py`
  (114 live/unit checks, all passing):** payload thinking flags per reply
  language (en/ta-Latn → off, ta/auto → on), system-role history entries
  dropped from the payload (no prompt injection), meta/echo stripping in
  `_clean_response` (incl. unbracketed echoes of the final-turn directives,
  trailing self-notes like *But we need to ensure it's natural Tamil.*, and
  marker-quoted answers sliced with a fresh offset after preamble stripping),
  English/Tanglish/Tamil detection and extraction (Tamil
  budget units மில்லியன்/லட்சம்/கோடி/ஆயிரம் incl. casual no-virama spellings,
  Tamil numerals ௦–௯, Tamil price keywords/location names, beds/type patterns,
  hyphenated *2-bedroom*/*2-bath* → exact bed/bath search criteria,
  colloquial/phonetic Tanglish detection — *"inniku yenakku set aagumaa? …
  irukkaa?"* → ta-Latn, not English),
  the spec sentence *"துபாயில் 2 பெட்ரூம் அபார்ட்மென்ட் வேணும், பட்ஜெட் 3
  மில்லியன்"* → location/type/beds/budget → real Dubai dataset rows (all
  within budget), reply-language context directives (the reply language
  comes only from detection — no selector preference parameter exists
  anywhere), localized deterministic strings, the deterministic ordinal
  reference hint (English/Tamil ordinals, `#2`/`property 2`, out-of-range →
  *do not invent*, no ordinal → context untouched), the focus-turn
  disambiguation line **plus** the focus referent repeated as the first
  final-turn internal note (so *this property* can never be answered from the
  listing discussed previously), dataset prices normalized for the model
  context (Indian-grouped *13,80,000* → *1,380,000* — no lakh/BHK drift, no
  miscounted budget claims), the final-turn internal-note ordering (focus →
  reply language → announcement) and its deterministic safety nets (one
  localized question when an opener has no `?`, one Tanglish sign-off when a
  ta-Latn reply comes back plain English, and the Tamil/mixed
  **language-integrity net** — a reply whose body leaks the model's
  deliberation or comes back without Tamil script is replaced by the
  deterministic Tamil announcement built from the real cards: count + min/max
  price + one question, never plain English or model self-talk — with a
  focused `test_integrity_net.py` covering all of it), `main.py` persisting all 10
  visible cards (numbering
  survives a restart), search-index correctness against
  all 25,082 rows, **live** `/api/chat` Tamil enquiry with **no language
  field** (Tamil reply + Dubai cards ≤ budget) vs plain English (English
  reply + cards) vs Tanglish (ta-Latn detected, Tanglish signal in the
  reply, no scaffolding leak), and served-module assertions for the
  conversations error/retry/empty states, the selector's removal (no
  `lang-select`, no language argument — voice output follows the agent's
  reply-language verdict `ta-IN`/`en-IN`/`en-US`) and the signup
  confirm-password field + mismatch validation.
- **`/agent/conversations` UI states:** served-module assertions for the
  prominent error panel + Retry button, distinct *no conversations yet* vs
  *no match for these filters* empty states, `Clear filters`, and the
  `limit: 200` fetch — an API failure can never render as a silent empty list.
- Old databases migrate in place (new tables + new columns added on startup).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'backend'` | Run uvicorn from inside `backend/` |
| Port 8000 already in use | `Get-NetTCPConnection -LocalPort 8000 -State Listen` → stop that PID |
| Redirected to `/agent/login` from `/agent/*` | Expected — sign in with a staff CRM account |
| AI replies feel canned | NVIDIA call failed — check `.env` key / network; fallback replies are used |
| Mic not working | Use Chrome/Edge and `http://localhost:5173` (not a file:// URL) |
| Empty search results | Confirm `UAErealestate.json` sits next to `.env` at the repo root |
| Old DB schema | No action needed — the backend migrates old databases automatically at startup |
