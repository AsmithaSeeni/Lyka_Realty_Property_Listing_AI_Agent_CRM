# Phase 8 — Recommended Roadmap

Prioritized follow-up plan derived from
[`PHASE8_PRODUCTION_READINESS_AUDIT.md`](./PHASE8_PRODUCTION_READINESS_AUDIT.md).
**Nothing in this table has been implemented.** Every row marked "Approval
required" must be explicitly approved before any code change; rows marked as a
migration additionally require a stop-and-report before the schema is touched.

Priority key: **P0** = required before any real-user production deployment ·
**P1** = required for production hardening · **P2** = data-integrity / quality ·
**P3** = optional improvement.

## 1. Prioritized findings & actions

| # | Priority | Finding | Evidence (audit) | Impact | Recommended action | Dependencies | Approval |
|---|---|---|---|---|---|---|---|
| 1 | **P0** | SQLite FK enforcement is OFF globally; integrity is service-layer only | live `PRAGMA foreign_keys = 0`; `foreign_key_check` currently 0 violations | Orphans become possible the day a service path misses a check; silent data corruption | Add a SQLAlchemy connect-event setting `PRAGMA foreign_keys=ON`; run an orphan scan first; add a regression test | Orphan scan must pass (it does today) | Yes (code change) |
| 2 | **P0** | In-process `agents` dict for conversation AI state — unbounded, single-worker | `main.py:125-126, 485-522, 812` | Memory growth; multi-worker deployments lose/duplicate conversation context | Externalize conversation state (DB table or Redis) behind the same interface; evict on TTL | Decision: DB vs Redis | Yes |
| 3 | **P0** | Per-process in-memory rate limiter | `services/ratelimit.py:3-8` | Limits multiply with workers; reset on restart | Put a gateway/proxy limiter in front (nginx/Cloudflare) or adopt Redis-backed limiter | Deployment target decision | Yes |
| 4 | **P0** | Production configuration posture (not yet exercised) | `config.py` (`APP_ENV`, `CORS_ORIGINS`, `COOKIE_SECURE`, `SEED_*_PASSWORD` guards exist) | Demo credentials/wildcard CORS would be catastrophic if misconfigured | Deployment checklist: `APP_ENV=production`, real CORS origins, HTTPS, explicit seed passwords or pre-created accounts, disable `/docs` | Hosting choice | Yes (ops only) |
| 5 | **P0** | No automated backup for the working database | no backup code/schedule anywhere | Data loss on disk failure | Scheduled SQLite backup-API snapshots → off-site, plus a documented restore drill | None | Yes (ops only) |
| 6 | **P1** | Chunked uploads bypass the 413 size guard | `main.py:97-111` | Memory pressure from hostile non-browser clients | Cap the ASGI body (middleware or proxy `client_max_body_size`) | None | Yes |
| 7 | **P1** | SQLite single-writer (`journal_mode=delete`), no explicit busy timeout | live PRAGMA; `database.py:23-30` | "database is locked" under parallel writes | WAL mode + `timeout=` in `create_engine` connect args (SQLite-only branch) | None | Yes |
| 8 | **P1** | Public API docs exposed | FastAPI defaults | Information disclosure of the full attack surface | Disable docs when `APP_ENV=production` | None | Yes |
| 9 | **P1** | Test-suite hygiene: `live` marker unused; no `addopts`; `test_request_limits` missing its promised chat mock | `pytest.ini`; `test_request_limits.py:1-6` | A future `.env` key silently turns unit runs into live API calls | Add `addopts = -m "not live_openai"`; add the fake-agent monkeypatch; delete or use the `live` marker | None | Yes |
| 10 | **P2** | Saved-property id-space encoding has no DB representation | `saved_properties` schema; live rows all dataset-space | Support/debug fragility; collision risk if the dataset ever exceeds 1M ids | **Migration:** add `source` column (`dataset\|record`), backfill from the reserved range, add `UNIQUE(customer_id, property_id)` | None | **Yes — migration stop-and-report first** |
| 11 | **P2** | No price period on `properties` (yearly-amount convention is implicit) | `database.py:292`; `PRICE_PERIOD_BY_PURPOSE` | Ambiguous raw prices; future multi-currency/period bugs | **Migration:** nullable `price_period` + backfill from `purpose` | None | **Yes — migration stop-and-report first** |
| 12 | **P2** | Duplicate indexes on `follow_ups` (`ix_followups_*` + `ix_follow_ups_*`) | live index dump | Minor write overhead / clutter | Drop the redundant family (keep model indexes) in an Alembic/ledger-tracked change | Migration tooling (item 16) | Yes |
| 13 | **P2** | No schema-version ledger; `_MIGRATIONS` is ad-hoc | `database.py:367-451` | Migration history is implicit; unsafe for PG | Introduce Alembic with current schema as revision 1 (SQLite-compatible first) | None | Yes |
| 14 | **P2** | Customer email uniqueness is check-then-insert (race) | `main.py:1023-1039`; no unique index | Duplicate accounts with one email under concurrency | **Migration:** unique index on `customers.email` (after a duplicate scan) | None | **Yes — migration stop-and-report first** |
| 15 | **P2** | NVIDIA failure paths untested (429, timeouts, retries, fallback strings, log hygiene) | audit §4.5 | Regressions in provider resilience would ship unnoticed | Add mocked-httpx tests per the audit's test plan (no prompt changes) | None | Yes |
| 16 | **P2** | Language machinery untested (detection matrix, Tamil repair, Tanglish fallback) | audit §3.4/§4.5 | Multilingual regressions ship unnoticed | Table-driven unit tests for `detect_language_and_style` + recovery nets | None | Yes |
| 17 | **P2** | Guardrail regressions untested (SYSTEM_PROMPT text, zero-match behavior, reference pinning) | audit §3.3/§4.5 | Hallucination guardrails could silently regress | String-assertion + zero-match tests (tests only — prompts untouched) | None | Yes |
| 18 | **P2** | PostgreSQL data-model risks (naive-UTC, Float money, JSON-in-Text, no-FK columns) | audit §1.8 | Painful/lossy migration if attempted ad hoc | Resolve in the Stage-2 migration plan (audit §5) before any PG move | Items 10, 11, 13, 16 | Deferred |
| 19 | **P3** | `voice.py` reads keys via `os.getenv` instead of `settings` | `voice.py:16,28,37` | Config precedence divergence | Route voice config through `settings` | None | Yes |
| 20 | **P3** | Stale `server_entry.py` (v1.0.0) deployment artifact | `app/server_entry.py` | Misleading/crashy if executed | Retire or rewrite as a documented static-frontend entry | None | Yes |
| 21 | **P3** | Tanglish (`ta-Latn`) provider-failure fallback answers in English | `nvidia_client.py:316` | Cosmetic, failure-path only | Extend `_fallback_response` with a Tanglish canned reply | None (code, not prompt) | Yes |
| 22 | **P3** | Demo rows eligible for public browse by design | audit §1.3 | Product-acceptable today (labels + honesty guard) | Optional production flag to hide `is_demo` rows | Product decision | Yes |
| 23 | **P3** | `leads` lacks a direct customer FK; no activity/audit table | audit §1.5/1.6 | "My leads" views need joins; no edit audit trail | Optional **migration:** `leads.customer_id` FK + audit table (pending Phase 5 decision) | None | **Yes — migration stop-and-report first** |
| 24 | **P3** | No rate limit on public property reads | route definitions | Damping only (local reads are cheap) | Optionally add a generous public bucket | None | Yes |
| 25 | **P3** | Temp test dirs never cleaned | `conftest.py:21` | Disk litter | `tempfile.TemporaryDirectory`/fixture teardown | None | Yes |

## 2. Suggested phasing (each phase needs explicit approval)

- **Phase 9 — Test & CI hardening (P2 items 9, 15, 16, 17, 25).** Pure test
  work: mocked NVIDIA failure-path tests, language matrix, guardrail string
  assertions, pytest `addopts`, cleanup. Delivers the "feature G" test-depth
  goal with zero production risk. CI (GitHub Actions) can then run
  secret-free: `pytest` + `npm run build`.
- **Phase 10 — SQLite hardening (P0/P1 items 1, 6, 7, 8, 13).** FK enforcement,
  WAL + busy timeout, body-size cap, docs gating, Alembic ledger. Each is a
  small, isolated change with regression tests; the DB file itself is not
  rewritten beyond PRAGMA settings.
- **Phase 11 — Migrations requiring approval (items 10, 11, 12, 14, 23).** One
  stop-and-report per migration group: saved `source` + uniqueness, price
  period, duplicate-index cleanup, customer-email uniqueness, optional
  `leads.customer_id`/audit table. Each includes a verified backup and a
  row-count reconciliation before/after.
- **Phase 12 — Production deployment package (P0 items 2–5 + ops checklist).**
  Externalized conversation state, distributed/gateway rate limiting, backup
  automation + restore drill, deployment checklist (`APP_ENV=production`,
  HTTPS, CORS, seed passwords, docs disabled). Only after this does a real-user
  deployment become defensible.
- **Phase 13 — PostgreSQL (deferred, item 18 + audit §5 Stage 2).** Trigger
  condition: sustained multi-writer concurrency or managed-hosting requirement.
  Cutover only with rehearsal-on-copy, per-table reconciliation (including the
  16 legacy NULL-customer conversations and both saved-property id spaces), and
  a tested rollback to the last SQLite snapshot.

## 3. Explicit non-goals (scope guards)
- No replacement of the NVIDIA customer-chat provider, prompts, or models —
  language/fallback work is code-and-tests only.
- No feature additions beyond the fixes above; browse/CRM/AI behavior is
  considered complete through Phase 7.
- No destructive data cleanup: the 16 legacy NULL-customer conversations and
  all historical recommendation rows are preserved as-is.
- No commits, deployments, or migrations without per-phase approval.
