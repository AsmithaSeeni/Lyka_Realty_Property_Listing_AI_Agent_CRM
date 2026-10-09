# LykAI — AI Property Concierge by Lyka Realty (AI Agent + CRM)

A production-style, **two-tier** AI real-estate app for the UAE, powered by
**LykAI** (LYK = Lyka · AI = Artificial Intelligence) — Lyka Realty's AI
property concierge:

- **Customer side (public)** — LykAI chats like a human consultant
  (English · Tamil · Tanglish), searches a 25,000-property dataset
  deterministically, remembers each visitor's conversations, captures leads
  naturally, and supports voice. Customers only ever see **their own** chats.
- **Agent side (authenticated CRM)** — bcrypt + session-cookie login at
  `/login`, then a role-scoped CRM: dashboard, searchable/filterable leads,
  full AI conversation transcripts, property recommendations, notes and
  pipeline status. Every `/api/agent/*` request is validated server-side.

Backend: FastAPI + SQLAlchemy + SQLite. Frontend: React + Vite.

---

## Project structure

```
lyka_property_agent2/
├── .env                       # All API keys (never exposed to the frontend)
├── UAErealestate.json         # Property dataset (25,082 listings)
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
        │   ├── ConversationHistory.jsx # The visitor's OWN past chats
        │   ├── PropertyDetails.jsx
        │   └── LoginPage.jsx           # /login — agent sign-in
        └── agent/                     # Protected CRM (behind /agent/*)
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
| `/properties` | Optional manual browse (secondary; every card also offers **Ask LykAI**) |
| `/property/:id`, `/properties/:id` | Property details — **Ask LykAI about this property** returns to the conversation with the listing in focus (`/chat?ref=<id>`) |
| `/signin` | Optional customer sign-in / create account (guests chat immediately) |
| `/history` | Signed-in customers: their conversations + saved properties. Guests first see a non-blocking *"Want to keep your LykAI conversations and saved properties?"* prompt (Sign In / Create Account / Continue as Guest) |

Nav: **Home (logo) · Properties · LykAI · Sign In** (signed-in customers see
**My Chats** instead of Sign In). LykAI is the primary entry point; history is
never prominent for guests.

Customers are identified by an anonymous httpOnly cookie. The backend only
ever returns conversations owned by that cookie — one customer can never list
or open another customer's chat (foreign IDs return `404`, not `403`, so they
can't be probed either). Pre-migration conversations with no owner are
agents-only. Signing in **claims** the guest cookie's conversations (and saved
properties) onto the account, so nothing is lost when a guest registers.

### Agent (login + protected CRM)

| Route | Page |
|---|---|
| `/login` | Agent sign-in (email **or** username + password) |
| `/agent/dashboard` | Status counts, recent leads, recent conversations |
| `/agent/leads` | Lead list — search, status/location filters, sort, inline status |
| `/agent/leads/:id` | Customer profile, editable status & notes, complete AI conversation, all recommended properties |
| `/agent/conversations` | Business view of every thread in scope — search by customer/phone/email/lead#/conv#, date range, thread drawer |

`/crm` now redirects to `/login`. Unauthenticated visits to `/agent/*`
redirect to `/login` (frontend convenience — the **backend** independently
rejects every request without a valid session, so the UI guard is defence in
depth, not the security boundary).

### CRM accounts (seeded on first run)

| Role | Login | Password | Scope |
|---|---|---|---|
| admin | `admin@lykarealty.ae` (or `admin`) | `Admin@123` | All leads & conversations |
| agent | `agent@lykarealty.ae` (or `agent`) | `Agent@123` | Leads assigned to them + the shared unassigned pool |

Override via `.env`: `SEED_ADMIN_EMAIL`, `SEED_ADMIN_USERNAME`,
`SEED_ADMIN_PASSWORD`, `SEED_ADMIN_NAME` (and the `SEED_AGENT_*` equivalents).
Passwords are stored as **bcrypt** hashes (cost 12); plaintext is never stored
or logged.

---

## API endpoints

### Public

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Health check (confirms LykAI is running) |
| POST | `/api/chat` | Chat message → AI reply + recommended properties (visitor-scoped; optional `property_id` = listing the customer is viewing) |
| GET | `/api/properties/search` | Filtered dataset search (`location`, `property_type`, price/bed/bath/area ranges, `limit`, `offset`) |
| GET | `/api/properties/{id}` | Single property |
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
| POST | `/api/customer/register` | `{email, password, name?}` → account + links this guest's conversations/saves (`409` if the email exists) |
| POST | `/api/customer/login` | `{email, password}` → session cookie, claims guest conversations (`401` generic on bad credentials) |
| POST | `/api/customer/logout` | Clear cookie — next chat is a fresh guest |
| GET | `/api/customer/saved` | Saved listings as full dataset rows (accounts only, `401` otherwise) |
| POST | `/api/customer/saved` | `{property_id}` → bookmark (idempotent, never duplicates) |
| DELETE | `/api/customer/saved/{id}` | Remove a bookmark |

### Auth & agent CRM (401 without a valid session — checked on **every** request)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/login` | `{username, password}` → session cookie + one-time bearer token |
| POST | `/api/auth/logout` | Revoke session, clear cookie |
| GET | `/api/auth/me` | Current agent (used for route guarding) |
| GET | `/api/agent/dashboard` | Counts by status + recent leads + recent conversations |
| GET | `/api/agent/leads` | `q`, `status`, `location`, `sort=newest\|interaction`, `limit`, `offset` |
| GET | `/api/agent/leads/{id}` | Profile + every conversation + all recommendations |
| PATCH | `/api/agent/leads/{id}` | Status / notes / fields / assignment (validated) |
| GET | `/api/agent/conversations` | `q` (name/phone/email/lead#/conv#), `date_from`, `date_to` |
| GET | `/api/agent/conversations/{id}` | Full thread + recommendations + lead reference |

There is intentionally **no public lead endpoint** — the old `/api/leads*`
routes were removed. The AI creates/updates leads through a server-side
authenticated code path (`app/services/leads.py`).

Interactive docs: `http://localhost:8000/docs`

---

## How LykAI works

1. **Language detection** — every message is classified as English, Tamil
   (script) or Tanglish (romanized Tamil) and the agent replies in kind.
2. **Requirement extraction** — budget, location, bedrooms, buy/rent, purpose,
   timeline, and contact details (name/phone/email) are extracted from natural
   messages as the chat progresses.
3. **Deterministic search, announced naturally** — the AI never invents
   properties. The search runs **before** the reply, so LykAI knows its cards
   are attached and says things like *"I found a few properties that match
   what you're looking for"* (one question at a time, budget asked first).
   Cards attach only when the result differs from what is already visible, so
   the thread never floods with duplicates. Follow-ups like *"show me cheaper
   ones"* or *"what about 3 bedrooms"* re-run the search with the remembered
   criteria, and *"the second property"* is resolved against the numbered
   cards the customer can actually see.
4. **Ask LykAI about a listing** — opening a property and tapping
   *Ask LykAI about this property* returns to the conversation with
   `/chat?ref=<id>`; the backend resolves that listing server-side and injects
   its real dataset row, so follow-ups like *"tell me more about this
   property"* are answered from actual data — the customer never types an id.
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

TTS_PROVIDER=nvidia        # or openai
TTS_MODEL=magpie-tts-multilingual
TTS_VOICE=mia
TTS_API_KEY=...
```

> Note: keys must match their provider format. NVIDIA-hosted *chat* models are
> available at `integrate.api.nvidia.com`; hosted TTS/STT endpoints require the
> provider above to expose them (or a self-hosted NIM). The browser voice mode
> is the recommended default and needs no keys.

---

## Configuration (`.env`)

```env
NVIDIA_API_KEY=nvapi-...
NVIDIA_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b
STT_PROVIDER=...
STT_MODEL=...
STT_API_KEY=...
TTS_PROVIDER=...
TTS_MODEL=...
TTS_VOICE=...
TTS_API_KEY=...
# Optional CRM seed overrides (defaults shown)
SEED_ADMIN_EMAIL=admin@lykarealty.ae
SEED_ADMIN_USERNAME=admin
SEED_ADMIN_PASSWORD=Admin@123
SEED_ADMIN_NAME=Lyka Admin
SEED_AGENT_EMAIL=agent@lykarealty.ae
SEED_AGENT_USERNAME=agent
SEED_AGENT_PASSWORD=Agent@123
SEED_AGENT_NAME=Sales Agent
```

The backend loads `.env` from the repo root — the frontend never sees these values.

---

## Verification performed

- **Conversation-first journey (76 live HTTP + UI checks, all passing):**
  browse search pagination (`limit`/`offset`) · guest chat → follow-up →
  property cards with dataset fields only · ordinal reference (*"the second
  property"*) grounded in the real listing · focus-property chat
  (`property_id` from the details page) grounded in that listing · messages +
  per-message recommendation ids persisted · customer register (guest chats
  claimed) · duplicate register → 409 · bad login → 401 · saved properties
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
- Old databases migrate in place (new tables + new columns added on startup).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'backend'` | Run uvicorn from inside `backend/` |
| Port 8000 already in use | `Get-NetTCPConnection -LocalPort 8000 -State Listen` → stop that PID |
| Redirected to `/login` from `/agent/*` | Expected — sign in with a seeded CRM account |
| AI replies feel canned | NVIDIA call failed — check `.env` key / network; fallback replies are used |
| Mic not working | Use Chrome/Edge and `http://localhost:5173` (not a file:// URL) |
| Empty search results | Confirm `UAErealestate.json` sits next to `.env` at the repo root |
| Old DB schema | No action needed — the backend migrates old databases automatically at startup |
