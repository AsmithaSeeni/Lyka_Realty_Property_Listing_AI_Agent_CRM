# Lyka Realty — AI Property Consultant + CRM

A production-style AI real-estate agent for the UAE with a built-in CRM.
The AI chats like a human consultant (English · Tamil · Tanglish), searches a
25,002-property dataset deterministically, remembers every conversation, captures
leads naturally, and supports voice — all over a FastAPI + React stack.

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
│   ├── real_estate.db         # SQLite (auto-created on first run)
│   └── app/
│       ├── main.py            # FastAPI app + all API routes
│       ├── config.py          # .env settings loader
│       ├── database.py        # SQLAlchemy models (Lead, Conversation, Message…)
│       ├── ai/
│       │   ├── agent.py       # Conversation state, language detection, lead logic
│       │   └── nvidia_client.py  # NVIDIA LLM client + fallback replies
│       ├── services/
│       │   ├── property_search.py  # Deterministic dataset search
│       │   └── voice.py             # STT / TTS providers
│       └── schemas/
│
└── frontend/
    ├── index.html
    ├── vite.config.ts         # Dev proxy: /api → localhost:8000
    └── src/
        ├── main.jsx / App.jsx # Router + layout
        ├── api.js             # API client
        ├── index.css          # Premium UAE design system
        └── pages/
            ├── LandingPage.jsx
            ├── ChatPage.jsx           # Chat + voice mode
            ├── CRMDashboard.jsx
            ├── ConversationHistory.jsx
            └── PropertyDetails.jsx
```

---

## Prerequisites

- **Python 3.10+**
- **Node.js 18+** (npm included)
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

Verify: `http://localhost:8000/api/health` → `{"status":"healthy", ...}`

### 2. Frontend

```bat
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

> The Vite dev server proxies `/api/*` to `http://localhost:8000`, so no CORS
> setup is needed in development.

---

## Pages

| Route | Page |
|---|---|
| `/` | Landing — hero, features, languages |
| `/chat` | AI Agent chat (new conversation) |
| `/chat/:id` | Reopen a stored conversation with full context |
| `/history` | Conversation history with previews |
| `/crm` | CRM dashboard — leads, pipeline, notes |
| `/property/:id` | Property details from the dataset |

---

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Health check |
| POST | `/api/chat` | Chat message → AI reply + recommended properties |
| GET | `/api/properties/search` | Filtered dataset search |
| GET | `/api/properties/{id}` | Single property |
| GET | `/api/conversations` | List conversations |
| GET | `/api/conversations/{id}` | Conversation + messages + recommendations |
| POST | `/api/conversations` | Create a conversation |
| GET | `/api/leads` | List leads (CRM) |
| POST | `/api/leads` | Create a lead |
| GET | `/api/leads/{id}` | Get a lead |
| PATCH | `/api/leads/{id}` | Update status / notes (JSON body) |
| POST | `/api/voice/transcribe` | Audio file → text (STT) |
| POST | `/api/voice/respond` | Text → AI reply (optionally with audio) |
| POST | `/api/voice/synthesize` | Text → WAV audio (TTS) |

Interactive docs: `http://localhost:8000/docs`

---

## How the AI works

1. **Language detection** — every message is classified as English, Tamil
   (script) or Tanglish (romanized Tamil) and the agent replies in kind.
2. **Requirement extraction** — budget, location, bedrooms, buy/rent, purpose,
   timeline, and contact details (name/phone/email) are extracted from natural
   messages as the chat progresses.
3. **Deterministic search** — the AI never invents properties. When enough
   requirements exist, the backend filters `UAErealestate.json` and attaches the
   real matches. Follow-ups like *"show me cheaper ones"* re-run the search with
   the remembered criteria.
4. **Memory** — every message, detected language and shared property is stored
   in SQLite. Reopening a conversation replays the history so the agent
   continues with the same context even after a server restart.
5. **Lead capture** — once requirements **and** contact details exist, a CRM
   lead is created/updated automatically (no duplicate leads per phone number).

### Dataset fields

`property_id, price, property_type, no__of__beds, no_of_baths, area, highlights, location`

Only these fields exist — the UI and search never show anything else.
Prices use Indian number formatting (e.g. `65,00,000`) and are parsed to numbers
for filtering.

---

## Voice

**In the browser (works out of the box):**
The chat page's 🎙 voice mode uses the Web Speech API —
speech recognition for input and speech synthesis for replies, with
listening → thinking → speaking states, mute, live transcript, and an
end button. Best in Chrome / Edge over `http://localhost` (mic requires a
secure context; localhost qualifies).

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
```

The backend loads `.env` from the repo root — the frontend never sees these values.

---

## Tests used during development

- `GET /api/health`, chat, search, leads, conversations — all verified via the
  FastAPI TestClient and live HTTP against the running server.
- End-to-end: start chat → continue → fetch conversation → clear server memory →
  reopen with context → give contact details → lead created → PATCH lead status.
- Frontend production build: `npm run build` (Vite) compiles clean.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'backend'` | Run uvicorn from inside `backend/` |
| Port 8000 already in use | `Get-NetTCPConnection -LocalPort 8000 -State Listen` → stop that PID |
| AI replies feel canned | NVIDIA call failed — check `.env` key / network; fallback replies are used |
| Mic not working | Use Chrome/Edge and `http://localhost:5173` (not a file:// URL) |
| Empty search results | Confirm `UAErealestate.json` sits next to `.env` at the repo root |
| Old DB schema warnings | Delete `backend/real_estate.db` — it is recreated on startup |
