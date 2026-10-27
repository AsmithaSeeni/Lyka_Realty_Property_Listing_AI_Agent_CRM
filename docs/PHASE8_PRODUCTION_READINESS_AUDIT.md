# Phase 8 — Production Readiness Audit

**Project:** LYKAI / Lyka Realty AI (`D:\lyka_property_agent2`)
**Date:** 2026-10-12 · **Scope:** audit and planning only — no schema changes, no
migrations, no deployments, no commits were made in this phase.
**Basis:** direct inspection of the repository as it exists now (models, routes,
services, tests, live SQLite schema read-only), not prior completion reports.

## 0. Repository state at audit time

- Branch `main`, 3 commits (`99a823a initial enhancement` latest), **no stashes**.
- Working tree: **27 modified + 15 untracked = 42 entries** — identical to the
  Phase 7 end-state. All pre-existing work preserved; nothing reset/discarded.
- `docs/` did not exist; both Phase 8 documents are new files.
- Validation executed in this phase: `python -m pytest tests -q` →
  **396 passed, 1 skipped** (skip = live OpenAI, no key) and `npm run build` →
  ✅ 54 modules. Live SQLite inspected read-only (`mode=ro` URIs, PRAGMA queries
  only). Working DB `backend\real_estate.db`: `PRAGMA integrity_check` = **ok**,
  `PRAGMA foreign_key_check` = **0 violations**.
- Row counts (read-only): 23 properties, 2 leads, 0 follow_ups, 1,165
  recommendations (all dataset-space), 10 saved rows (all dataset-space),
  2 agents. *(Correction noted in Phase 9: this line originally listed
  "325 conversations, 327 customers", which were reconstructed rather than
  measured; the verified post-Phase-7 values measured read-only in Phase 9
  are 328 conversations and 301 customers. No writes occurred in between —
  nothing in Phases 8–9 modifies the working database.)*
- `lykarealty.ae` appears **only** as seeded staff email domains — there is no
  production URL anywhere in backend code or tests (verified by grep); nothing in
  this project can reach the production site.

---

## 1. Database & data-model audit

### 1.1 Sale vs rental price periods — **P2**
- **Evidence:** `properties.price` is a bare `Float` (`database.py:292`); no
  period column exists. The yearly-amount convention for rent/lease rows is a
  documented service-level convention, and display derives the period from
  `purpose` (`PRICE_PERIOD_BY_PURPOSE` in `services/property_search.py`).
- **Impact:** a raw `price` read without `purpose` is ambiguous; matching is safe
  today only because rent rows are compared rent-to-rent with yearly amounts.
- **Remedy:** when approved, add a nullable `price_period` column (additive
  migration) and backfill `rent/lease → 'per_year'`, `sale → 'one_time'`;
  keep purpose-derived display until then.

### 1.2 Property area and unit — **P3**
- **Evidence:** `area` `Float NULL` + `area_unit` default `"sqft"`
  (`database.py:298-299`). All seeded demo rows are sqft; area is not part of the
  Phase 4 match weights.
- **Impact:** mixed-unit imports would silently misrepresent size; currently
  contained because all sources are controlled.
- **Remedy:** keep per-row unit; if sqm sources ever arrive, add conversion at
  the service boundary (no schema change needed).

### 1.3 Verified listings vs fictional demo inventory — **P3 (by design, mitigated)**
- **Evidence:** `is_approved` (default FALSE), `is_demo`, `source` columns
  (`database.py:302-306`); CHECK constraints on `purpose` and `availability`;
  eligibility engine requires approved+available for browse, detail, saved
  bookmarks and chat focus (`services/property_search.py`); the dataset
  (25,082 rows) is never imported into `properties`.
- **Demo honesty:** demo rows are intentionally eligible (they demonstrate the
  product) but are labelled on the listing/detail pages, and the assistant is
  deterministically instructed that a demo focus listing is fictional
  (`agent.py` context-block guard, added Phase 7, live-verified).
- **Residual risk:** recommendation cards surfaced by chat are dataset rows, not
  DB records, so no demo record can silently appear as a card.
- **Remedy:** none required; optional production flag to exclude `is_demo` rows
  from public listing (product decision).

### 1.4 Saved-property ID-space encoding — **P2**
- **Evidence:** `saved_properties.property_id` is a bare `Integer`
  (`database.py:131`); record-space bookmarks are stored as
  `1,000,000 + record_id` (service constant `_SAVED_RECORD_ID_BASE`,
  `main.py`). Live DB currently holds 10 saved rows, **all dataset-space**
  (min 1059, max 67,48× range, 0 rows ≥ 1,000,000) — verified read-only.
- **Impact:** the encoding is a service-layer convention with no DB
  representation; a dataset id ≥ 1,000,000 would collide (dataset max 25,082 —
  ~39× safety margin today); manual DB edits could corrupt bookmarks; the
  customer never sees the synthetic id, but support/debugging must know the rule.
- **Remedy:** approved migration adding `saved_properties.source`
  (`dataset|record`) + backfill from the reserved range; keep the range encoding
  until then (it is fully covered by Phase 6/7 tests).

### 1.5 Customer / conversation / lead / recommendation / follow-up relationships — **P2**
- **Evidence (schema, read-only dump):**
  - `conversations.customer_id → customers.id` (nullable). **16 orphan rows**
    (NULL customer) exist — pre-migration legacy, visible to agents only.
  - `conversations.lead_id → leads.id` (nullable).
  - **`leads` has no customer FK** — the customer link exists only through
    `conversations.customer_id` (documented Phase 5 decision; `leads` also has no
    `customer_id` column).
  - `property_recommendations.conversation_id` and `.lead_id` are FKs;
    `property_id` (dataset space) and `property_record_id` (DB record space) are
    **plain integers, no FK** — `property_record_id` integrity is service-layer
    only (SQLite cannot add a FK via ALTER; noted in `database.py:264-268`).
  - `follow_ups.lead_id` FK (NOT NULL) + `assigned_agent_id` FK (nullable).
  - `messages.conversation_id` FK.
- **Impact:** account-side "my leads" views must join through conversations;
  recommendation↔property integrity depends on service code (Phase 7 added a
  defense-in-depth guard preventing record ids entering this table).
- **Remedy:** optional `leads.customer_id` FK column and a FK/backfill for
  `property_record_id` during the PostgreSQL move (both need approval).

### 1.6 Lead ownership, unassigned leads, administrator access — **P3**
- **Evidence:** `leads.assigned_agent_id` nullable FK; scope rule
  `admin → all`, `agent → own + unassigned pool` (`services/auth.py:233-243`);
  unauthorized access returns 404 **without lead details** (Phase 5 + Phase 7
  tests assert the response body is leak-free).
- **Impact:** no audit trail of who claimed/edited a lead (no activity log).
- **Remedy:** optional activity/audit table (pending Phase 5 decision).

### 1.7 Missing constraints, indexes, uniqueness, FK protection — **P1/P2/P3**
Verified with read-only PRAGMA queries against the live DB:

| Finding | Evidence | Severity |
|---|---|---|
| **SQLite FK enforcement is OFF** (`PRAGMA foreign_keys = 0`; SQLAlchemy never enables it). All FKs are declared but **not enforced**; today `foreign_key_check` = 0 violations, so nothing is currently orphaned (beyond the 16 legacy NULLs, which are legal). | live PRAGMA; `database.py:23-30` (no PRAGMA wiring) | **P1** |
| No `UNIQUE (customer_id, property_id)` on `saved_properties` — idempotency is service-layer only (concurrent double-save could insert twice; UI tolerates). | `PRAGMA index_list('saved_properties')` → only plain indexes | **P2** |
| No unique index on `customers.email` — registration uniqueness is check-then-insert (409) with a race window. | `customers` unique list = `[token_hash]` only; `main.py:1023-1039` | **P3** |
| `leads.phone` deliberately NOT unique — duplicate policy is "warn + explicit override" (409/`duplicate_override`); two concurrent creates could still double-insert. This is by design (a hard unique constraint would break the override flow). | `leads.py` find_duplicate; `main.py` create-lead 409 path; live: 0 duplicate phones | **P3** (accepted design) |
| **Duplicate indexes on `follow_ups`** — model indexes `ix_follow_ups_*` and post-migration list `ix_followups_*` both exist on fresh DBs (harmless bloat, proven by the index dump). | live index dump shows both families | **P3** |
| No CHECK constraints on `leads.status` / `conversations.status` / `messages.role` (follow-ups and properties do have CHECKs); status literals are enforced by Pydantic models. | `database.py` table args | **P3** |
| No schema-version ledger table; migrations are idempotent column-existence ALTERs instead (`_MIGRATIONS`, `_POST_MIGRATION_INDEXES`). Safe and repeatable for SQLite; insufficient discipline for PostgreSQL. | `database.py:367-451`; Phase 2 migration tests run them twice on a copy | **P2** (for the PG move) |

### 1.8 Data-integrity & migration risks for PostgreSQL — **P1 planning item**
- **Naive-UTC datetimes everywhere** (`datetime.utcnow`, no timezone) — PG
  `timestamptz` requires a conversion pass or a fixed server TZ.
- **Money as `Float`** (`properties.price`, `leads.budget_min/max`,
  `relevance_score`) — PG should use `NUMERIC`; float rounding must be
  reconciled.
- **JSON-in-Text columns** (`amenities`, `score_breakdown`, `missing_fields`,
  `clarification_questions`, `match_reasons`) — PG `jsonb` + GIN would be the
  target; content is already valid JSON (service-produced).
- **ID-space encoding must be resolved before migration** (§1.4) or the unique
  index and backfill become part of the cutover.
- **Orphan/NULL data**: 16 NULL-customer conversations must be preserved
  (agents-visible legacy), not "cleaned".
- **`_MIGRATIONS` ALTER-with-REFERENCES lists do not translate to PG** — they
  must be replaced by Alembic revisions; a fresh-schema parity test would be
  required.

---

## 2. API & security audit

### 2.1 Confirmed security properties (verified by code + automated tests)
- **Staff auth:** server-side sessions with SHA-256-hashed tokens
  (`agent_sessions.token_hash` unique — live-verified), 12 h TTL + revocation,
  httpOnly + SameSite=Lax cookies, `Secure` auto-on in production
  (`auth.py:26-125`), Bearer header also supported. Demo passwords are only
  seeded outside production; `APP_ENV=production` requires explicit
  `SEED_*_PASSWORD` (`database.py:454-522`).
- **RBAC:** admin-all vs agent-scope enforced server-side; unauthorized access →
  404 with no detail leakage (Phase 5 + Phase 7 tests).
- **Customer isolation:** cookie-token identity (hashed at rest); conversations
  and saved properties always filtered by `customer_id`; cross-customer access →
  404/empty (Phase 6 + Phase 7 tests); guest data claimed only on that browser's
  registration/login.
- **Identity separation:** staff emails reserved — customer registration with a
  staff email → 422 (`main.py:1017-1022`).
- **Input validation:** Pydantic `max_length`/patterns on all mutating payloads;
  chat message capped at 4,000 chars; request-size guard → 413 (5 MB default);
  voice upload capped; `LeadUpdate` uses `extra="forbid"`, `LeadCreate`
  `extra="ignore"` (spoofed `lead_score` is ignored, scores are server-computed).
- **CORS:** explicit origin list; `*` is rejected when `APP_ENV=production`
  and falls back to an empty (deny-all) list (`config.py:54-76`).
- **Rate limits:** sliding-window, per-IP — chat 60/min, auth 15/min, voice
  30/min, with `Retry-After` (`services/ratelimit.py`; wired in tests).
- **Error handling:** global handler returns `{"detail": "Internal server
  error"}` with server-side-only tracebacks; no stack traces, keys, cookies or
  bodies in responses; live log scans (Phases 6–7) found no secrets.
- **Secrets hygiene:** `.env` gitignored and covered by `test_env_example.py`;
  NVIDIA/OpenAI/voice logs emit status/duration/length only; OpenAI client
  contractually never logs key, headers, enquiry, or raw provider bodies
  (asserted by test).
- **Safe AI boundaries:** staff-only OpenAI extraction (503 without key —
  never fabricates), NVIDIA customer chat unchanged, chat never calls OpenAI
  (grep-verified single call site in the staff extraction route).

### 2.2 Theoretical risks (no current exploit; harden before real traffic)
| Risk | Evidence | Severity |
|---|---|---|
| **Chunked uploads bypass the 413 guard** — the size middleware only checks `Content-Length`; hostile non-browser clients can stream large bodies (browsers/Vite proxy always send the header). | `main.py:97-111` (documented in the comment) | **P2** |
| **In-memory rate limiter is per-process** — multi-worker deployments multiply the effective limit; restarts reset counters. | `services/ratelimit.py:3-8` | **P1** for production |
| **Global `agents: Dict[int, AIRealEstateAgent]`** — conversation AI state is in-process, never evicted (unbounded memory) and would be **inconsistent across workers**; the code itself notes "in production, use proper session management". | `main.py:125-126, 485-522, 812` | **P1** for production |
| **SQLite single-writer** (`journal_mode = delete`, `synchronous = FULL`) — parallel writes serialize and can raise "database is locked"; no explicit busy timeout configured (sqlite3 default 5 s). WAL would remove reader/writer blocking. | live PRAGMA; `database.py:23-30` | **P2** for production |
| **Customer register/login uniqueness is check-then-insert** (no DB unique index on `customers.email`). | `main.py:1023-1039`; PRAGMA | **P3** |
| **API docs public** (`/docs`, `/openapi.json` unauthenticated). | FastAPI defaults | **P3** |
| **No rate limit on public reads** (`/api/properties*`, `/api/properties/search`) — cheap local reads, damping only. | route definitions | **P3** |
| **`voice.py` reads keys via `os.getenv` directly** instead of `settings` — env-var precedence differs from the rest of the config (config-divergence). | `voice.py:16,28,37` vs `config.py:105,110` | **P3** |
| **Stale `server_entry.py`** (v1.0.0, CWD-relative `frontend/dist` mount, catch-all route) — dead deployment artifact that would crash or mis-serve if run; not part of the current backend. | `app/server_entry.py` | **P3** |
| No CSRF tokens — accepted because JSON APIs + SameSite=Lax cookies block cross-site state changes. | `auth.py:117,166` | accepted |

**No confirmed vulnerabilities** were found in the current code paths, and no
security certification is claimed: this is a code/config review plus automated
regression evidence, not a penetration test.

---

## 3. AI behavior & provider readiness

NVIDIA remains the customer-chat provider; nothing in this phase changed
prompts, models, or keys.

### 3.1 Focus eligibility & per-turn context — solid, tested
- Focus is revalidated server-side every turn: records via
  `get_public_record` (approved+available) — an ineligible record yields **no
  focus** (`main.py:524-545`); dataset ids via the index (unknown → None).
- Record-space focus is strictly per-turn and never enters the shared
  recommendation list or persisted cards (Phase 7 defect fix, tested agent-level
  and API-level).

### 3.2 Fictional-demo disclosure — tested + live-verified
- Demo focus adds an explicit "FICTIONAL DEMO" honesty instruction to the
  deterministic context block; live NVIDIA turn (Phase 7) answered that the
  listing is "a fictional demo property… not real, verified, or currently
  available".
- Scope note: the guard covers the *focus listing*; dataset cards are reference
  data presented with the existing dataset disclaimer.

### 3.3 Hallucination prevention — good, one prompt-test gap
- System prompt forbids inventing listings; cards are produced only by
  deterministic dataset search, never by model text; ordinal references are
  pinned to visible cards with a "do not invent / do not substitute" note; a
  search with zero matches produces no NEW-MATCHES block.
- **Gap:** no automated test asserts the guardrail text or the zero-match
  behavior (see test plan §5).

### 3.4 Multilingual (English / Tamil / Tanglish / mixed) — implemented, undertested
- Per-message detection (Tamil script, Tanglish word list + suffixes, mixed),
  reply-language enforcement, Tamil-leak repair, Tanglish→English+Tamil-question
  append, first-turn question append, localized deterministic strings.
- **Gap:** no unit tests for the detection thresholds or the recovery nets.
- **Known quirk:** the canned *fallback* map handles `"ta"`/`"mixed"` but not
  `"ta-Latn"` — a provider failure during a Tanglish turn falls back to the
  English canned reply (cosmetic, provider-failure-only).

### 3.5 NVIDIA provider handling — robust, partly untested
- 120 s read / 10 s connect timeout, 2 attempts (5xx and connect-error retried
  once, read-timeout deliberately not retried), **429 → immediate canned
  fallback (no backoff)**, missing key → canned fallback with no network call,
  no key/header logging, prompt-leak scrubbers on the reply.
- **Untested:** retry paths, 429 path, timeout→fallback, the Tamil/Tanglish
  fallback strings, the reply scrubbers, and a "no key in NVIDIA logs" assertion.

### 3.6 OpenAI structured extraction — well-tested, live-untested
- 30 s timeout, ≤2 attempts with 0.5 s backoff, 429/5xx retried once, 401/403
  never retried; missing key → `503 not_configured`; provider failures map to
  502/503/504; never fabricates a result; staff-only; review-only (no DB
  writes); 31 mocked tests including "no key or enquiry in logs".
- Live path untested: no `OPENAI_API_KEY` present; the single live test skips
  and requires explicit approval to run.

### 3.7 Voice readiness
- Browser Web Speech API is the working default (no keys needed). Server-side
  STT/TTS require keys that are currently unusable; endpoints degrade correctly
  (502; TTS failure inside `/api/voice/respond` is non-fatal, text-only reply).
  5 MB upload cap, 60 s/90 s timeouts, TTS text trimmed to 1,200 chars.
  Voice follows the detected language; no language selector exists (by design).

---

## 4. Test & CI readiness

### 4.1 How to run
- Backend: `cd backend; python -m pytest tests -q` → **396 passed, 1 skipped**
  (the skip is the live OpenAI smoke; also marked `live_openai`).
- Frontend: `cd frontend; npm run build` → ✅ 54 modules, no errors.

### 4.2 Isolation — verified reliable
- `tests/conftest.py` creates a **temporary file DB** and sets `DATABASE_URL`
  **before any `app` import** (`load_dotenv` never overrides preset env), so the
  entire suite binds to the temp DB; `APP_ENV=test` is pinned and the rate
  limiter is reset per test.
- Extra isolated engines are used where exact counts matter (seed, matching,
  dashboard tests).
- The live `backend\real_estate.db` is contacted by exactly two files, both
  read-only: the migration tests (byte-copy + hash guards proving the live file
  is unmodified) and config path-resolution tests (stat only). No test writes,
  drops, or deletes anything in the working database; `lykarealty.ae` is
  unreachable from any test.

### 4.3 Keys & network
- Exactly **one** test can hit the network (live OpenAI smoke), gated by
  `OPENAI_API_KEY` + `live_openai` marker — it skips today. Everything else
  monkeypatches providers (Phase 3, 4, 6, 7 harnesses) or uses the deterministic
  no-network paths.
- **CI can run with zero secrets**: verified — no key-gated test would run; no
  production URL exists.

### 4.4 Hygiene findings (P2/P3)
- `pytest.ini` declares a `live` (NVIDIA) marker that **no test uses**, and has
  **no `addopts`** — so if `OPENAI_API_KEY` ever lands in `.env`, a plain
  `pytest` run silently performs one real API call. Remedy: add
  `addopts = -m "not live_openai"` (or `-m "not live"`), keeping explicit
  opt-in for live runs.
- `test_request_limits.py` documents a monkeypatched chat guard that **does not
  exist in the file** — today every request fails validation before the handler
  (safe), but a future loosening of validation would turn those tests into real
  NVIDIA calls while a key sits in `.env`. Remedy: add the promised fake-agent
  monkeypatch.
- Temp dirs from `mkdtemp` are never cleaned (disk litter only).

### 4.5 Uncovered high-risk journeys (test plan for a future phase)
1. NVIDIA failure modes with a mocked `httpx` transport: 5xx retry, connect
   retry, read-timeout→fallback, 429→fallback; assert logs contain no key.
2. Language detection matrix (Tamil script, Tanglish words/suffixes, mixed,
   English) + Tamil-leak repair + Tanglish fallback strings.
3. SYSTEM_PROMPT guardrail text regression (string assertions) and zero-match
   behavior ("0 eligible listings" never rendered as cards).
4. `_clean_response`/`_trim_incomplete_tail` prompt-leak scrubbers.
5. Voice internals (missing-key RuntimeError, provider dispatch, trim caps)
   beyond the current endpoint-level tests.
6. Multi-turn record-focus continuity after conversation reload (known
   limitation — assert current documented behavior).

---

## 5. PostgreSQL recommendation

**Do not migrate now.** Rationale (evidence-based):

| Criterion | Current state | Verdict |
|---|---|---|
| Concurrent users/writes | Single-process uvicorn; tens of rows/day; SQLite single-writer is adequate; `synchronous=FULL` protects against power loss | Not justified |
| Deployment | Single file DB, zero ops, free backups by file copy when the server is stopped | SQLite wins |
| Backup/recovery | No automation exists yet — but that gap is identical for PG; the first real backup need is scheduled SQLite-backup-API copies | Fix backup first, engine later |
| Connection management | SQLAlchemy pool already abstracts engines; PG adds connection limits/config | Neutral |
| Transactions/locking | Service layer already uses single-transaction writes; PG would remove writer-serialization only when it actually hurts | Premature |
| Migration tooling | `_MIGRATIONS` is SQLite-specific; PG requires Alembic regardless — real engineering either way | Defer with the app |
| Cost/complexity | PG adds a server, credentials, TLS, monitoring | Negative at this scale |

**The real production blockers are not the database**: they are the in-process
agent state (`agents` dict), the per-process rate limiter, and single-writer
SQLite under multi-worker deployment (§2.2). Fix those in app form first; the
database engine is the last step.

### Staged strategy (for approval in a later phase)
- **Stage 0 — SQLite hardening (no engine change):** enable
  `PRAGMA foreign_keys=ON` per connection (after an orphan scan — currently 0),
  switch to WAL + busy-timeout, add `UNIQUE(customer_id, property_id)` on
  `saved_properties` (after resolving the id-space encoding), consolidate the
  duplicate `follow_ups` indexes, add a schema-version ledger table, and schedule
  **SQLite backup-API** snapshots to an off-site location with a documented
  restore drill.
- **Stage 1 — app readiness:** externalize conversation AI state (DB table or
  Redis) so any worker can serve any conversation; add a shared/distributed rate
  limiter (or accept an API-gateway limiter); introduce Alembic with the current
  schema as revision 1; freeze naive-UTC as a documented convention or migrate
  to timezone-aware columns via Alembic.
- **Stage 2 — PostgreSQL cutover (only when multi-writer traffic is real):**
  provision PG (managed, e.g. Neon/RDS) → Alembic upgrade → rehearse
  `pg_dump`-equivalent migration on a **copy** (SQLAlchemy reflection or
  Alembic autogenerate + data copy) → reconcile row counts and checksums per
  table, including the 16 legacy NULL-customer conversations and the saved-row
  id spaces → run the full suite + smoke against the copy → cut over with
  SQLite kept authoritative until parity is proven → rollback plan: revert
  `DATABASE_URL` to the last SQLite snapshot (RPO = last backup). Data
  reconciliation must also convert naive-UTC, `Float` money → `NUMERIC`, and
  JSON-Text → `jsonb`.

---

## 6. Outstanding uncertainties
- Live NVIDIA behavior under sustained load (429 frequency, latency
  distribution) is unmeasured; only individual turns were exercised.
- OpenAI extraction has never run against the real API in this environment (no
  key); its live schema adherence is unproven.
- The reserved-range saved-encoding has no live rows yet (all current bookmarks
  are dataset-space) — behavior is test-proven, not yet production-exercised.
- Multi-worker behavior is untested by construction (single-process dev server).
- This audit did not exercise any destructive or adversarial testing; risk
  ratings are code-review judgments, not certified findings.

## 7. Safety confirmations
- No schema/migration/seed changes; live DB opened **read-only** only
  (`mode=ro`), `integrity_check` ok, `foreign_key_check` 0 violations, row
  counts recorded above.
- No customer/lead data modified; no commits, resets, stashes, or discards;
  the 42 pre-existing working-tree entries are byte-for-byte preserved.
- `lykarealty.ae` never contacted; no secrets printed (variable names only).
