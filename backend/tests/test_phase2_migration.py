"""Phase 2 — migration tests on a DISPOSABLE COPY of the live database.

The live backend/real_estate.db is only ever READ (byte-copied via
shutil.copy2); every migration/index statement runs against the copy in a
temp directory. Destructive experiments never touch the live file.
"""

import hashlib
import pathlib
import shutil
import sqlite3

import pytest
from sqlalchemy import create_engine, inspect

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
LIVE_DB = _BACKEND / "real_estate.db"
ROOT_STALE_DB = _BACKEND.parent / "real_estate.db"

EXISTING_TABLES = [
    "agents", "agent_sessions", "customers", "conversations",
    "messages", "leads", "property_recommendations", "saved_properties",
]

LEAD_NEW_COLS = [
    "original_enquiry", "budget_min", "budget_max", "budget_currency",
    "amenities", "lead_score", "priority", "score_breakdown",
    "missing_fields", "clarification_questions", "timeline_days",
    "extraction_source",
]

REC_NEW_COLS = ["match_score", "match_reasons", "match_mismatches",
                "property_record_id"]


def _counts(db_path: pathlib.Path):
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        return {
            t: con.execute(f"select count(*) from {t}").fetchone()[0]
            for t in EXISTING_TABLES
        }
    finally:
        con.close()


@pytest.fixture()
def live_copy(tmp_path):
    if not LIVE_DB.exists():
        pytest.skip("live database not present on this machine")
    src_hash = hashlib.sha256(LIVE_DB.read_bytes()).hexdigest()
    dst = tmp_path / "live_copy.db"
    shutil.copy2(LIVE_DB, dst)
    assert hashlib.sha256(dst.read_bytes()).hexdigest() == src_hash
    return dst


def _migrate_twice(db_path):
    from app.database import Base, _ensure_indexes, _run_migrations

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    # Full init sequence, deliberately run TWICE (repeat-safety requirement).
    for _ in range(2):
        Base.metadata.create_all(bind=engine)
        _run_migrations(engine)
        _ensure_indexes(engine)
    return engine


def test_live_db_only_read_never_written(live_copy):
    before = hashlib.sha256(LIVE_DB.read_bytes()).hexdigest()
    _migrate_twice(live_copy)
    after = hashlib.sha256(LIVE_DB.read_bytes()).hexdigest()
    assert before == after, "live database file was modified by the migration test"


def test_stale_root_db_untouched(live_copy):
    if not ROOT_STALE_DB.exists():
        pytest.skip("root-level stale db absent")
    before = hashlib.sha256(ROOT_STALE_DB.read_bytes()).hexdigest()
    _migrate_twice(live_copy)
    after = hashlib.sha256(ROOT_STALE_DB.read_bytes()).hexdigest()
    assert before == after


def test_migration_on_copy_creates_new_tables_and_columns(live_copy):
    engine = _migrate_twice(live_copy)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"properties", "follow_ups"} <= tables

    lead_cols = {c["name"] for c in inspector.get_columns("leads")}
    assert set(LEAD_NEW_COLS) <= lead_cols

    rec_cols = {c["name"] for c in inspector.get_columns("property_recommendations")}
    assert set(REC_NEW_COLS) <= rec_cols


def test_migration_preserves_row_counts(live_copy):
    before = _counts(live_copy)
    _migrate_twice(live_copy)
    after = _counts(live_copy)
    assert before == after
    # Sanity: the copy really carried data (not an empty shell).
    assert sum(before.values()) > 0


def test_old_rows_remain_readable_with_null_new_fields(live_copy):
    _migrate_twice(live_copy)
    con = sqlite3.connect(f"file:{live_copy.as_posix()}?mode=ro", uri=True)
    try:
        leads = con.execute(
            "select id, name, lead_score, original_enquiry, budget_min, "
            "budget_currency, score_breakdown, extraction_source "
            "from leads order by id"
        ).fetchall()
        for row in leads:
            # Historical leads: provenance/scored fields stay NULL — never fabricated.
            assert row[2] is None and row[3] is None and row[4] is None
            assert row[5] is None and row[6] is None and row[7] is None

        recs = con.execute(
            "select id, match_score, match_reasons, match_mismatches, "
            "property_record_id from property_recommendations limit 50"
        ).fetchall()
        assert recs, "expected historical recommendation rows"
        for row in recs:
            assert row[1] is None and row[2] is None and row[3] is None
            assert row[4] is None
        # Old dataset-style rows keep their original property_id values.
        old_pid = con.execute(
            "select property_id from property_recommendations "
            "where property_id is not null limit 1"
        ).fetchone()
        assert old_pid is not None
    finally:
        con.close()


def test_copy_integrity_after_migration(live_copy):
    _migrate_twice(live_copy)
    con = sqlite3.connect(f"file:{live_copy.as_posix()}?mode=ro", uri=True)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        # New indexes exist on the migrated copy.
        idx = {r[0] for r in con.execute(
            "select name from sqlite_master where type='index'"
        )}
        for name in [
            "ix_leads_priority", "ix_leads_lead_score", "ix_leads_created_at",
            "ix_properties_purpose_availability",
            "ix_properties_approved_availability", "ix_properties_price",
            "ix_followups_due_completed", "ix_followups_lead_id",
            "ix_recommendations_match_score",
        ]:
            assert name in idx, f"missing index {name}"
        # Follow-up FK is declared in DDL.
        ddl = con.execute(
            "select sql from sqlite_master where name='follow_ups'"
        ).fetchone()[0]
        assert "REFERENCES leads" in ddl
        assert "REFERENCES agents" in ddl
    finally:
        con.close()


def test_migrations_idempotent_on_fresh_db(tmp_path):
    from app.database import Base, _ensure_indexes, _run_migrations

    fresh = tmp_path / "fresh.db"
    engine = create_engine(f"sqlite:///{fresh.as_posix()}")
    for _ in range(3):  # triple-run: no duplicate columns/indexes, no errors
        Base.metadata.create_all(bind=engine)
        _run_migrations(engine)
        _ensure_indexes(engine)
    con = sqlite3.connect(f"file:{fresh.as_posix()}?mode=ro", uri=True)
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(leads)")]
        assert len(cols) == len(set(cols))
        idx_names = [r[0] for r in con.execute(
            "select name from sqlite_master where type='index'"
        )]
        assert len(idx_names) == len(set(idx_names))
        # Staff seeding is init_db()'s job (app-startup path, covered by the
        # app-module tests); this loop only proves schema ops are repeatable.
        assert con.execute("select count(*) from agents").fetchone()[0] == 0
    finally:
        con.close()
