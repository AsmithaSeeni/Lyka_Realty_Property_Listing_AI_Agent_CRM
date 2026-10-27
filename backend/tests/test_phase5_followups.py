"""Phase 5 — follow-up management on the existing `follow_ups` table.

Synthetic, unique-per-test data against the throwaway test DB only.
Timezone policy under test: aware inputs are converted to UTC, naive inputs
are read as UTC, output carries an explicit "Z", and the overdue /
due_today / upcoming buckets partition pending rows by UTC calendar day.
"""

import itertools
from datetime import datetime, time, timedelta

import pytest

ADMIN_EMAIL = "admin@lykarealty.ae"
ADMIN_PASS = "Admin@123"
AGENT_EMAIL = "agent@lykarealty.ae"
AGENT_PASS = "Agent@123"

LEADS_URL = "/api/agent/leads"
FOLLOWUPS_URL = "/api/agent/follow-ups"
_seq = itertools.count(11001)


def _uniq_phone():
    return f"+9716{next(_seq):07d}"


def _uniq_email():
    return f"p5fu{next(_seq)}@example.com"


def _login(client, email, password):
    r = client.post("/api/auth/login", json={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


def _make_lead(client, token, **over):
    body = {
        "name": "P5 FU Lead", "phone": _uniq_phone(), "email": _uniq_email(),
        "intent": "buy", "location": f"P5 FU Loc {next(_seq)}",
        "confirm": True,
    }
    body.update(over)
    r = client.post(LEADS_URL, json=body, headers=_hdr(token))
    assert r.status_code == 200, r.text
    return r.json()["lead"]["id"]


@pytest.fixture()
def admin_token(client):
    return _login(client, ADMIN_EMAIL, ADMIN_PASS)


@pytest.fixture()
def agent_token(client):
    return _login(client, AGENT_EMAIL, AGENT_PASS)


def _add_fu(client, token, lead_id, **over):
    body = {"type": "call", "due_at": "2030-01-01T10:00:00Z", "notes": ""}
    body.update(over)
    r = client.post(f"{LEADS_URL}/{lead_id}/follow-ups", json=body,
                    headers=_hdr(token))
    return r


# =========================== CREATE ===========================

def test_create_followup_success(client, agent_token):
    lead_id = _make_lead(client, agent_token)
    r = _add_fu(client, agent_token, lead_id, type="viewing",
                due_at="2030-01-02T15:00:00Z", notes="site visit")
    assert r.status_code == 200, r.text
    fu = r.json()["follow_up"]
    assert fu["lead_id"] == lead_id
    assert fu["type"] == "viewing"
    assert fu["notes"] == "site visit"
    assert fu["due_at"] == "2030-01-02T15:00:00Z"  # explicit Z
    assert fu["is_completed"] is False and fu["completed_at"] is None
    assert fu["bucket"] == "upcoming"
    me = client.get("/api/auth/me", headers=_hdr(agent_token)).json()["agent"]
    assert fu["assigned_agent_id"] == me["id"]  # defaults to the creator


def test_create_followup_requires_staff(client):
    r = client.post(f"{LEADS_URL}/1/follow-ups",
                    json={"type": "call", "due_at": "2030-01-01T10:00:00Z"})
    assert r.status_code == 401


def test_create_followup_invalid_type_rejected(client, agent_token):
    lead_id = _make_lead(client, agent_token)
    r = _add_fu(client, agent_token, lead_id, type="carrier_pigeon")
    assert r.status_code == 422
    assert "follow-up type" in r.json()["detail"].lower()


def test_create_followup_invalid_date_rejected(client, agent_token):
    lead_id = _make_lead(client, agent_token)
    for junk in ("not-a-date", "32/13/2026", ""):
        r = _add_fu(client, agent_token, lead_id, due_at=junk)
        assert r.status_code == 422, f"expected 422 for {junk!r}: {r.text}"


def test_create_followup_unknown_lead_404(client, agent_token):
    r = _add_fu(client, agent_token, 999_999)
    assert r.status_code == 404


def test_create_followup_out_of_scope_lead_404(client, admin_token, agent_token):
    # assigned to admin → invisible to the regular agent
    admin_id = client.get("/api/auth/me",
                          headers=_hdr(admin_token)).json()["agent"]["id"]
    lead_id = _make_lead(client, admin_token, assigned_agent_id=admin_id)
    r = _add_fu(client, agent_token, lead_id)
    assert r.status_code == 404


def test_followup_assignment_rules(client, admin_token, agent_token, db):
    from app.database import Agent
    from app.services.auth import hash_password

    n = next(_seq)
    password = f"FuPw!{n}"
    other = Agent(email=f"p5fu.other{n}@lykarealty.ae", username=f"p5fu.other{n}",
                  full_name=f"P5 FU Other {n}",
                  password_hash=hash_password(password), role="agent")
    db.add(other)
    db.commit()
    db.refresh(other)

    lead_id = _make_lead(client, agent_token)
    # agent may not assign a follow-up to a different agent
    r = _add_fu(client, agent_token, lead_id, assigned_agent_id=other.id)
    assert r.status_code == 403
    # admin may
    admin_lead = _make_lead(client, admin_token)
    r = _add_fu(client, admin_token, admin_lead, assigned_agent_id=other.id)
    assert r.status_code == 200
    assert r.json()["follow_up"]["assigned_agent_id"] == other.id


# =========================== READ / UPDATE ===========================

def test_lead_followups_sorted_and_scoped(client, agent_token):
    lead_id = _make_lead(client, agent_token)
    _add_fu(client, agent_token, lead_id, due_at="2030-03-01T10:00:00Z")
    _add_fu(client, agent_token, lead_id, due_at="2029-01-01T10:00:00Z",
            type="email")
    r = client.get(f"{LEADS_URL}/{lead_id}/follow-ups",
                   headers=_hdr(agent_token))
    assert r.status_code == 200
    rows = r.json()["results"]
    dues = [f["due_at"] for f in rows]
    assert dues == sorted(dues)  # oldest first
    assert len(rows) == 2


def test_patch_followup_complete_and_restore(client, agent_token):
    lead_id = _make_lead(client, agent_token)
    fu = _add_fu(client, agent_token, lead_id).json()["follow_up"]

    r = client.patch(f"{FOLLOWUPS_URL}/{fu['id']}",
                     json={"is_completed": True}, headers=_hdr(agent_token))
    assert r.status_code == 200, r.text
    done = r.json()["follow_up"]
    assert done["is_completed"] is True
    assert done["completed_at"] is not None and done["bucket"] is None

    r2 = client.patch(f"{FOLLOWUPS_URL}/{fu['id']}",
                      json={"is_completed": False}, headers=_hdr(agent_token))
    restored = r2.json()["follow_up"]
    assert restored["is_completed"] is False
    assert restored["completed_at"] is None


def test_patch_followup_fields(client, agent_token):
    lead_id = _make_lead(client, agent_token)
    fu = _add_fu(client, agent_token, lead_id).json()["follow_up"]
    r = client.patch(f"{FOLLOWUPS_URL}/{fu['id']}",
                     json={"type": "whatsapp", "notes": "rescheduled",
                           "due_at": "2030-06-01T09:00:00Z"},
                     headers=_hdr(agent_token))
    assert r.status_code == 200
    got = r.json()["follow_up"]
    assert (got["type"], got["notes"], got["due_at"]) == (
        "whatsapp", "rescheduled", "2030-06-01T09:00:00Z")


def test_patch_followup_invalid_values_rejected(client, agent_token):
    lead_id = _make_lead(client, agent_token)
    fu = _add_fu(client, agent_token, lead_id).json()["follow_up"]
    assert client.patch(f"{FOLLOWUPS_URL}/{fu['id']}",
                        json={"type": "telepathy"},
                        headers=_hdr(agent_token)).status_code == 422
    assert client.patch(f"{FOLLOWUPS_URL}/{fu['id']}",
                        json={"due_at": "tomorrow-ish"},
                        headers=_hdr(agent_token)).status_code == 422
    assert client.patch(f"{FOLLOWUPS_URL}/{fu['id']}",
                        json={"due_at": "2030-01-01T10:00:00Z"},
                        headers=_hdr(agent_token)).status_code == 200  # sanity


def test_patch_followup_unknown_and_out_of_scope_404(client, admin_token,
                                                     agent_token):
    assert client.patch(f"{FOLLOWUPS_URL}/999999",
                        json={"notes": "x"},
                        headers=_hdr(agent_token)).status_code == 404
    admin_id = client.get("/api/auth/me",
                          headers=_hdr(admin_token)).json()["agent"]["id"]
    lead_id = _make_lead(client, admin_token, assigned_agent_id=admin_id)
    fu = _add_fu(client, admin_token, lead_id).json()["follow_up"]
    # regular agent cannot touch another agent's follow-up
    assert client.patch(f"{FOLLOWUPS_URL}/{fu['id']}", json={"notes": "hijack"},
                        headers=_hdr(agent_token)).status_code == 404
    # nor even list it
    r = client.get(FOLLOWUPS_URL, params={"lead_id": lead_id},
                   headers=_hdr(agent_token))
    assert r.status_code == 404


def test_patch_followup_requires_staff(client):
    assert client.patch(f"{FOLLOWUPS_URL}/1", json={"notes": "x"}).status_code == 401


# =========================== FILTERS / TIMEZONE ===========================

def _utc_day_bucket_due_times():
    """Fixed relative times that always land in each UTC bucket."""
    today_end = datetime.combine(datetime.utcnow().date() + timedelta(days=1),
                                 time.min)
    return {
        "overdue": (today_end - timedelta(days=1, hours=12)).isoformat() + "Z",
        "due_today": (today_end - timedelta(hours=1)).isoformat() + "Z",
        "upcoming": (today_end + timedelta(hours=12)).isoformat() + "Z",
    }


def test_global_list_filters(client, agent_token):
    lead_id = _make_lead(client, agent_token)
    dues = _utc_day_bucket_due_times()
    ids = {}
    for bucket, due in dues.items():
        r = _add_fu(client, agent_token, lead_id, due_at=due,
                    notes=f"bucket {bucket}")
        assert r.status_code == 200, r.text
        ids[bucket] = r.json()["follow_up"]["id"]
    done_fu = _add_fu(client, agent_token, lead_id, due_at=dues["upcoming"],
                      notes="already done").json()["follow_up"]
    client.patch(f"{FOLLOWUPS_URL}/{done_fu['id']}",
                 json={"is_completed": True}, headers=_hdr(agent_token))

    def q(filt):
        r = client.get(FOLLOWUPS_URL,
                       params={"filter": filt, "lead_id": lead_id},
                       headers=_hdr(agent_token))
        assert r.status_code == 200, r.text
        return {f["id"] for f in r.json()["results"]}

    assert ids["overdue"] in q("overdue")
    assert ids["due_today"] in q("due_today")
    assert ids["upcoming"] in q("upcoming")
    assert done_fu["id"] in q("completed")
    assert done_fu["id"] not in q("pending")
    # buckets partition pending rows (no overlap, nothing lost)
    pending = q("pending")
    assert pending == {ids["overdue"], ids["due_today"], ids["upcoming"]}
    assert q("all") == pending | {done_fu["id"]}


def test_timezone_aware_input_converted_to_utc(client, agent_token):
    lead_id = _make_lead(client, agent_token)
    r = _add_fu(client, agent_token, lead_id, due_at="2027-03-10T14:00:00+04:00")
    assert r.status_code == 200, r.text
    assert r.json()["follow_up"]["due_at"] == "2027-03-10T10:00:00Z"


def test_timezone_naive_input_read_as_utc(client, agent_token):
    lead_id = _make_lead(client, agent_token)
    r = _add_fu(client, agent_token, lead_id, due_at="2027-03-10T10:00:00")
    assert r.status_code == 200, r.text
    assert r.json()["follow_up"]["due_at"] == "2027-03-10T10:00:00Z"


def test_bucket_semantics_unit():
    from app.services.followups import follow_up_bucket

    now = datetime(2027, 3, 10, 12, 0)  # noon UTC
    assert follow_up_bucket(datetime(2027, 3, 9, 23, 30), now) == "overdue"
    assert follow_up_bucket(datetime(2027, 3, 10, 0, 30), now) == "due_today"
    assert follow_up_bucket(datetime(2027, 3, 10, 11, 59), now) == "due_today"
    assert follow_up_bucket(datetime(2027, 3, 11, 0, 30), now) == "upcoming"


def test_parse_due_at_unit():
    from app.services.followups import parse_due_at

    assert parse_due_at("2027-03-10T14:00:00+04:00") == datetime(2027, 3, 10, 10, 0)
    assert parse_due_at("2027-03-10T10:00:00Z") == datetime(2027, 3, 10, 10, 0)
    assert parse_due_at("2027-03-10T10:00:00") == datetime(2027, 3, 10, 10, 0)
    with pytest.raises(ValueError):
        parse_due_at("next tuesday")


def test_lead_list_follow_up_filter(client, agent_token):
    loc = f"P5 FU Filter {next(_seq)}"
    with_fu = _make_lead(client, agent_token, location=loc)
    without = _make_lead(client, agent_token, location=loc)
    _add_fu(client, agent_token, with_fu,
            due_at=_utc_day_bucket_due_times()["overdue"])

    r = client.get(LEADS_URL, params={"location": loc, "follow_up": "overdue"},
                   headers=_hdr(agent_token))
    assert r.status_code == 200
    ids = [row["id"] for row in r.json()["results"]]
    assert with_fu in ids and without not in ids

    r2 = client.get(LEADS_URL, params={"location": loc, "follow_up": "pending"},
                    headers=_hdr(agent_token))
    ids2 = [row["id"] for row in r2.json()["results"]]
    assert with_fu in ids2 and without not in ids2


def test_followup_writes_do_not_touch_unrelated_records(client, agent_token, db):
    from app.database import FollowUp, Lead

    lead_a = _make_lead(client, agent_token)
    lead_b = _make_lead(client, agent_token)
    fu_b = _add_fu(client, agent_token, lead_b).json()["follow_up"]

    before_leads = db.query(Lead).count()
    before_fus = db.query(FollowUp).count()

    r = _add_fu(client, agent_token, lead_a, notes="only mine")
    assert r.status_code == 200

    db.expire_all()
    assert db.query(Lead).count() == before_leads          # no lead churn
    assert db.query(FollowUp).count() == before_fus + 1    # exactly one row
    row_b = db.query(FollowUp).filter(FollowUp.id == fu_b["id"]).first()
    assert row_b.notes == "" and row_b.is_completed is False  # untouched


def test_detail_next_follow_up_reflects_earliest_pending(client, agent_token):
    lead_id = _make_lead(client, agent_token)
    later = _add_fu(client, agent_token, lead_id,
                    due_at="2030-05-01T10:00:00Z").json()["follow_up"]
    earlier = _add_fu(client, agent_token, lead_id,
                      due_at="2030-04-01T10:00:00Z").json()["follow_up"]
    detail = client.get(f"{LEADS_URL}/{lead_id}",
                        headers=_hdr(agent_token)).json()["lead"]
    assert detail["next_follow_up"]["id"] == earlier["id"]
    # completing the earlier one moves the next pointer
    client.patch(f"{FOLLOWUPS_URL}/{earlier['id']}",
                 json={"is_completed": True}, headers=_hdr(agent_token))
    detail2 = client.get(f"{LEADS_URL}/{lead_id}",
                         headers=_hdr(agent_token)).json()["lead"]
    assert detail2["next_follow_up"]["id"] == later["id"]
