"""Phase 5 — dashboard statistics from real database queries.

Exact-count assertions run against an ISOLATED per-test SQLite engine (no
shared-state flakiness); endpoint assertions run against the throwaway
conftest DB. Nothing here ever touches the live database.
"""

import itertools
import tempfile
import pathlib
from datetime import datetime, time, timedelta

import pytest

ADMIN_EMAIL = "admin@lykarealty.ae"
ADMIN_PASS = "Admin@123"
AGENT_EMAIL = "agent@lykarealty.ae"
AGENT_PASS = "Agent@123"

_seq = itertools.count(15001)


def _login(client, email, password):
    r = client.post("/api/auth/login", json={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------- isolated engine for exact counts ----------------

@pytest.fixture()
def iso_db():
    """A brand-new empty database with its own session (per test)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base

    d = pathlib.Path(tempfile.mkdtemp(prefix="p5_iso_dash_"))
    eng = create_engine("sqlite:///" + (d / "iso.db").as_posix())
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    try:
        yield session
    finally:
        session.close()
        eng.dispose()


def _agent(iso_db, name, role="agent"):
    from app.database import Agent
    from app.services.auth import hash_password

    n = next(_seq)
    a = Agent(email=f"p5dash{n}@example.com", username=f"p5dash{n}",
              full_name=name, password_hash=hash_password(f"Pw!{n}"),
              role=role)
    iso_db.add(a)
    iso_db.commit()
    iso_db.refresh(a)
    return a


def _lead(iso_db, agent_id=None, status="new", priority=None, name="P5 D"):
    from app.database import Lead

    lead = Lead(name=name, status=status, priority=priority,
                lead_score=(None if priority is None else 70.0),
                assigned_agent_id=agent_id)
    iso_db.add(lead)
    iso_db.commit()
    iso_db.refresh(lead)
    return lead


def _fu(iso_db, lead_id, due_at, completed=False):
    from app.database import FollowUp

    fu = FollowUp(lead_id=lead_id, type="call", notes="", due_at=due_at,
                  is_completed=completed,
                  completed_at=(datetime.utcnow() if completed else None))
    iso_db.add(fu)
    iso_db.commit()
    return fu


# ---------------- service-level (isolated) ----------------

def test_empty_database_returns_zeros(iso_db):
    from app.services.crm_stats import dashboard_stats

    agent = _agent(iso_db, "P5 Empty Agent")
    stats = dashboard_stats(iso_db, agent)
    assert stats["counts"]["total"] == 0
    assert all(stats["counts"][s] == 0 for s in (
        "new", "contacted", "qualified", "viewing", "negotiation",
        "closed_won", "closed_lost"))
    assert stats["priority"] == {"high": 0, "medium": 0, "low": 0,
                                 "unscored": 0}
    assert stats["follow_ups"] == {"overdue": 0, "due_today": 0, "upcoming": 0}


def test_counts_reflect_inserted_records(iso_db):
    from app.services.crm_stats import dashboard_stats

    agent = _agent(iso_db, "P5 Count Agent")
    _lead(iso_db, agent.id, status="new", priority="high")
    _lead(iso_db, agent.id, status="new", priority="medium")
    _lead(iso_db, agent.id, status="contacted", priority="low")
    _lead(iso_db, agent.id, status="closed_won", priority="high")
    _lead(iso_db, agent.id, status="closed_lost", priority=None)  # unscored

    stats = dashboard_stats(iso_db, agent)
    c = stats["counts"]
    assert c["total"] == 5
    assert (c["new"], c["contacted"], c["qualified"]) == (2, 1, 0)
    assert c["closed_won"] == 1 and c["closed_lost"] == 1
    assert c["closed"] == 1 and c["lost"] == 1          # stat-card aliases
    assert stats["priority"] == {"high": 2, "medium": 1, "low": 1,
                                 "unscored": 1}


def test_followup_bucket_math(iso_db):
    from app.services.crm_stats import dashboard_stats

    agent = _agent(iso_db, "P5 Bucket Agent")
    lead = _lead(iso_db, agent.id)
    today_end = datetime.combine(datetime.utcnow().date() + timedelta(days=1),
                                 time.min)
    _fu(iso_db, lead.id, today_end - timedelta(days=1, hours=12))   # overdue
    _fu(iso_db, lead.id, today_end - timedelta(hours=1))            # due today
    _fu(iso_db, lead.id, today_end + timedelta(hours=12))           # upcoming
    _fu(iso_db, lead.id, today_end - timedelta(days=2), completed=True)  # done

    stats = dashboard_stats(iso_db, agent)
    assert stats["follow_ups"] == {"overdue": 1, "due_today": 1,
                                   "upcoming": 1}   # completed excluded


def test_agent_scoping_excludes_other_agents(iso_db):
    from app.services.crm_stats import dashboard_stats

    a1 = _agent(iso_db, "P5 Agent One")
    a2 = _agent(iso_db, "P5 Agent Two")
    admin = _agent(iso_db, "P5 Admin", role="admin")

    _lead(iso_db, a1.id, priority="high")   # a1's own
    _lead(iso_db, None, priority="high")    # unassigned pool
    _lead(iso_db, a2.id, priority="low")    # a2's own — invisible to a1
    _fu(iso_db, _lead(iso_db, a2.id).id,
        datetime.utcnow() - timedelta(days=1))  # a2's overdue — invisible

    s1 = dashboard_stats(iso_db, a1)
    assert s1["counts"]["total"] == 2                       # own + pool
    assert s1["priority"]["high"] == 2
    assert s1["follow_ups"]["overdue"] == 0                 # not a2's

    s2 = dashboard_stats(iso_db, a2)
    assert s2["counts"]["total"] == 3                       # own x2 + pool
    assert s2["priority"]["low"] == 1
    assert s2["follow_ups"]["overdue"] == 1

    sa = dashboard_stats(iso_db, admin)
    assert sa["counts"]["total"] == 4                       # everything
    assert sa["follow_ups"]["overdue"] == 1


def test_null_status_counts_as_new(iso_db):
    from app.database import Lead
    from app.services.crm_stats import dashboard_stats

    agent = _agent(iso_db, "P5 Null Status")
    iso_db.add(Lead(name="legacy no status"))  # status NULL (legacy row)
    iso_db.commit()

    stats = dashboard_stats(iso_db, agent)
    assert stats["counts"]["total"] == 1
    assert stats["counts"]["new"] == 1
    assert stats["priority"]["unscored"] == 1


# ---------------- endpoint-level (conftest DB) ----------------

def test_dashboard_requires_staff(client):
    assert client.get("/api/agent/dashboard").status_code == 401


def test_dashboard_endpoint_shape_and_consistency(client):
    token = _login(client, ADMIN_EMAIL, ADMIN_PASS)
    r = client.get("/api/agent/dashboard", headers=_hdr(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "agent" in body and body["agent"]["email"] == ADMIN_EMAIL

    counts = body["counts"]
    assert isinstance(counts["total"], int) and counts["total"] >= 0
    for key in ("new", "contacted", "qualified", "viewing", "negotiation",
                "closed", "lost", "closed_won", "closed_lost"):
        assert counts[key] >= 0
    prio = body["priority"]
    assert set(prio) == {"high", "medium", "low", "unscored"}
    assert sum(prio.values()) == counts["total"]          # complete partition
    assert set(body["follow_ups"]) == {"overdue", "due_today", "upcoming"}
    assert all(v >= 0 for v in body["follow_ups"].values())
    assert isinstance(body["recent_leads"], list)
    assert isinstance(body["recent_conversations"], list)

    # dashboard total == lead-list total for the same (admin) scope
    listed = client.get("/api/agent/leads", params={"limit": 500},
                        headers=_hdr(token)).json()
    assert listed["total"] == counts["total"]
