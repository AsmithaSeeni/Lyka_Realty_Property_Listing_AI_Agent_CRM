# Production Cleanup Audit — Lyka Realty (found state, pre-cleanup)

Scope: full repository audit preceding the content/dead-code cleanup. Every item
below was verified by reading source and grepping for references before any
removal. No secrets are reproduced anywhere in this document.

Method: file/route map of `frontend/src`, section-by-section read of every page,
backend route/service inventory, deployment config review, dependency and asset
reference checks, CSS selector usage checks (grep over JSX/JS before deleting any
block), and production probing of the live site.

---

## 1. Content removed (confirmed unnecessary before cleanup)

| Item | Where (pre-cleanup) | Why |
|---|---|---|
| AI feature-card grid ("The LykAI difference": *Multilingual by design, It remembers you, Never invents a thing, Natural follow-ups, Lead capture, naturally, Full conversation history*) | `LandingPage.jsx` + `AI_FEATURES` constant | Promotional repetition of AI capabilities on a public homepage; each card either restates the hero/services copy or exposes internal implementation details (deterministic search, CRM lead capture) |
| Hero "Live preview" card with fabricated conversation ("I found 20 matching villas", fake price) | `LandingPage.jsx` | Sample/placeholder content presented as a real product preview; also embedded an operational status chip ("LykAI is online/offline") that exposes backend state to every visitor and currently renders "offline" in production |
| Trust chip `★★★★★ Trusted by 300+ clients across Dubai` | `LandingPage.jsx` | Unverifiable rating + client count (no source of truth anywhere in the project) |
| Stats row `300+ clients · 25,082 UAE listings · 10 communities · 3 languages` | `LandingPage.jsx` + `STATS` | "300+ clients" and "10 communities" unverifiable; raw dataset counts are internal figures, not customer value |
| Footer claim "no pressure, no confusion. … 300+ clients served" | `App.jsx` footer | Slogan + unverifiable client count |
| CTA slogan "No pressure, no confusion." | `LandingPage.jsx` | Slogan |
| Meta-description count "25,000+ listings" | `frontend/index.html` | Marketing count in public metadata; not needed to describe the service |
| "AI desk that never sleeps" / "— instantly" hype | `LandingPage.jsx` services title | Slogan/availability claim |

## 2. Content retained (serves customers/business)

- Hero identity, headline, both CTAs (Talk to LykAI / Explore Properties).
- Services section (4 service cards — real service descriptions, lightly trimmed).
- Communities list, Languages section (factual, implemented features), closing
  CTA with the verified public WhatsApp contact.
- All property browsing/detail pages, filters, dataset notice and the
  "Demo/fictional listing" badge system (safeguard — kept).
- LyKAI chat UI, conversation history, saved properties, profile.
- Global Login Portal (`/login`, `/register`, `/signin`) incl. brand panel —
  its claims (role-based access, session-secured, audited) describe implemented,
  test-covered behaviour.
- Agent CRM: dashboard (real computed metrics), leads, lead detail, new-lead
  review flow, conversations, follow-ups.
- Honest "Not yet implemented" placeholder pages for HR/Payroll/Operations/
  Finance/Property Management — explicitly required to stay marked as such.
- Verified contact/address content in footer; brand colours/typography/logo.

## 3. Broken or incomplete functionality (documented, not silently fixed)

1. **Placeholder "Go to your CRM dashboard" button** showed for roles with no
   CRM access (HR/payroll…), which would only bounce off the guard →
   **fixed**: now permission-gated (`leads.read_assigned`/`leads.read_all`)
   and rendered as a client-side `Link`.
2. `services/property_crud.py` has service-level functions + tests but **no
   HTTP routes** (listing management module not built). Retained (tested
   building block); module intentionally absent.
3. No CRM modules for Deals/Pipeline, Contacts, Calendar, Reports, Admin
   Settings; admin UI for the tested admin/audit API not built yet.
4. Known pre-existing bugs (out of cleanup scope, listed for the roadmap):
   `AgentConversations.jsx` cleanup race, backend `new_conversation` always
   `False`, `chat()` TypeError retry path.
5. Production `/api/*` returned 500 and `/properties` returned 404 on the live
   site at audit time — root causes and fixes in `PRODUCTION_HEALTH_AUDIT.md`.

## 4. Unverified marketing claims removed

- "Trusted by 300+ clients" (star rating), "300+ clients served", "10
  communities covered" — no data source in the project.
- "AI desk that never sleeps" (availability claim), "— instantly".
- The fabricated "Live preview" conversation (sample prices/results).
- Note: "25,000+ listings" was *consistent with the dataset* (25,082 rows) but
  is an internal figure with no customer value in hero/meta copy → removed from
  UI; the factual count remains in README/docs where it describes the dataset.

## 5. Dead code and unused assets removed (after reference checks)

| Removed | Evidence it was dead |
|---|---|
| `frontend/src/pages/CustomerAuth.jsx` | Zero importers; superseded by `GlobalLogin.jsx` |
| `frontend/src/pages/LoginPage.jsx` | Zero importers; superseded by `GlobalLogin.jsx` |
| `backend/app/server_entry.py` | Zero references; stale v1 static-frontend entry (flagged P3 in `docs/PHASE8_PRODUCTION_READINESS_AUDIT.md`) |
| CSS `.lg*` (login page), `.ca-*` (customer auth) | Used only by the two deleted pages |
| CSS `.metrics/.metric*`, `.lead-row/.lead-cell*`, `.search-input`, `.chip-row`, `.status-row`, `.ax-sec`, `.section.tight`, `.section.white`, `.on-dark .eyebrow`, `.prop-rail*`, `.prop-grid*` | Zero matches in any JSX/JS after the CRM redesign cascade took over (verified by grep before deletion) |
| CSS `.trustchip`, `.hero-stats`, `.stat`, `.hero-card`, `.hero-mini-msg` + media-query references | Used only by the removed homepage sections |
| `api.createConversation`, `api.searchProperties`, `api.transcribe` | Zero callers; superseded (`/api/chat` auto-creates conversations, `listRecords` serves browse, browser SpeechRecognition is the wired STT path). Backend endpoints/tests kept intact |
| Unused imports: `BackgroundTasks` (main.py), `tempfile` (voice.py) | Zero references |

**Deliberately retained** (unwired but not dead): the `admin*`, `auditLog`,
`agentLeadFollowUps`, `listAgentFollowUps` client methods — they are the client
contract of live, tested admin/audit/follow-up endpoints that the planned admin
UI will consume. `api.health()` — actively used by the chat page's truthful
backend-status banner.

## 6. Production risks NOT silently changed

- **In-memory, IP-keyed rate limiting** behind Vercel's proxy: per-instance
  counters, key = connecting address (proxy). See health audit §7 for analysis
  and the smallest proposed fix — not implemented (blind key changes could
  weaken the control).
- **`properties` table seeding** is a manual CLI step; production listings
  depend on the operator seeding the production database. No writes were made
  to any production database from this work.
- **Session/auth security controls** (RBAC, CSRF, lockout, audit logging,
  hashed tokens, HttpOnly cookies) — untouched except doc-accuracy fixes.
- **Dataset duplication risk**: the dataset now lives at
  `backend/UAErealestate.json` (single copy, tracked rename) so the deployed
  function ships with it; replacing the dataset in the future must update that
  path (README documents this).

## 7. Files expected to change

`frontend/src/pages/LandingPage.jsx` (rewrite), `frontend/src/api.js`
(timeouts + dead methods), `frontend/src/App.jsx` (footer), `frontend/index.html`
(meta), `frontend/src/pages/ModulePlaceholder.jsx` (CRM button),
`frontend/src/index.css` (hero single-column + dead blocks), deletions above,
`backend/app/main.py`, `backend/app/database.py`, `backend/app/ai/nvidia_client.py`,
`backend/app/services/voice.py`, `backend/tests/test_phase2_property_model.py`,
new `backend/tests/test_health_checks.py`, `.env.example`,
`docs/GLOBAL_AUTH_IMPLEMENTATION.md` (doc-accuracy), `README.md`,
`vercel.json` (routing fix, earlier task), plus the five
`docs/PRODUCTION_*` documents.
