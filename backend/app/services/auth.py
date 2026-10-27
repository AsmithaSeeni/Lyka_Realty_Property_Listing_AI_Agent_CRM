"""Authentication & authorization for the internal agent CRM.

Design:
- Passwords: bcrypt (salted, cost 12) — plaintext never stored or logged.
- Sessions: opaque random token issued at login, handed to the browser as an
  httpOnly cookie (and returned once in the JSON body for API clients that
  prefer `Authorization: Bearer <token>`). Only the SHA-256 hash of the token
  is persisted, so a database dump cannot be replayed as a live session.
- Customers: public visitors are identified by a separate random cookie so the
  chat API can scope conversations to one browser. Customer tokens never grant
  access to any /api/agent/* route.
"""

from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.database import (
    Agent, AgentRole, AgentSession, Conversation, Customer, Lead, SavedProperty, get_db,
)
from app.services import rbac

AGENT_COOKIE = "lyka_agent_session"
CUSTOMER_COOKIE = "lyka_customer"
SESSION_TTL_HOURS = 12


# ---------------------------------------------------------------- passwords

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------- sessions

def create_session(db: Session, agent: Agent) -> str:
    """Create a server-side session; returns the RAW token (shown once)."""
    token = AgentSession.new_token()
    db.add(AgentSession(
        agent_id=agent.id,
        token_hash=AgentSession.hash_token(token),
        expires_at=datetime.utcnow() + timedelta(hours=SESSION_TTL_HOURS),
    ))
    db.commit()
    return token


def revoke_session(db: Session, token: str) -> None:
    row = (
        db.query(AgentSession)
        .filter(AgentSession.token_hash == AgentSession.hash_token(token))
        .first()
    )
    if row and row.revoked_at is None:
        row.revoked_at = datetime.utcnow()
        db.commit()


def revoke_all_sessions(db: Session, agent_id: int) -> int:
    """Revoke every live session for an agent. Returns how many were revoked.

    Used when an account is suspended, its roles change, or its password is
    reset — so an already-open browser loses access immediately instead of
    waiting for the 12h TTL.
    """
    now = datetime.utcnow()
    count = (
        db.query(AgentSession)
        .filter(AgentSession.agent_id == agent_id,
                AgentSession.revoked_at.is_(None))
        .update({"revoked_at": now}, synchronize_session=False)
    )
    db.commit()
    return count


def _extract_token(request: Request) -> Optional[str]:
    """Bearer header first (API clients), then the httpOnly cookie (browser)."""
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return token
    return request.cookies.get(AGENT_COOKIE)


def get_current_agent(
    request: Request,
    db: Session = Depends(get_db),
) -> Agent:
    """FastAPI dependency: validates the session on EVERY protected request.

    Raises 401 when missing/invalid/expired/revoked or the agent is disabled.
    """
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session_row = (
        db.query(AgentSession)
        .filter(AgentSession.token_hash == AgentSession.hash_token(token))
        .first()
    )
    if (
        session_row is None
        or session_row.revoked_at is not None
        or (session_row.expires_at and session_row.expires_at < datetime.utcnow())
    ):
        raise HTTPException(status_code=401, detail="Session expired or invalid")

    agent = db.query(Agent).filter(Agent.id == session_row.agent_id).first()
    if agent is None or not agent.is_active:
        raise HTTPException(status_code=401, detail="Agent account disabled")

    # Resolve roles + permissions ONCE per request; every downstream
    # require_permission()/has_permission() check reuses this cached set.
    cache_permissions(db, agent)

    # Expose the validated token so logout can revoke exactly this session
    request.state.session_token = token
    return agent


def set_agent_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=AGENT_COOKIE,
        value=token,
        httponly=True,          # JS can never read the session token
        samesite="lax",         # no cross-site sends; works on the Vite proxy
        secure=settings.COOKIE_SECURE,  # False on http localhost; true in production/HTTPS
        max_age=SESSION_TTL_HOURS * 3600,
        path="/",
    )


def clear_agent_cookie(response: Response) -> None:
    response.delete_cookie(AGENT_COOKIE, path="/")


# ---------------------------------------------------------------- lockout
# Simple, honest failed-login controls (see audit G2). After
# LOGIN_LOCKOUT_THRESHOLD consecutive failures an account is locked for
# LOGIN_LOCKOUT_MINUTES. Counters reset on success. This is a targeted brake
# on password-spraying ONE account (the per-IP rate limit already damps
# volume). A locked account gets the SAME generic message as a bad password,
# so an attacker cannot confirm the account exists or that a lock tripped.

LOGIN_LOCKOUT_THRESHOLD = max(1, settings.LOGIN_LOCKOUT_THRESHOLD)
LOGIN_LOCKOUT_MINUTES = max(1, settings.LOGIN_LOCKOUT_MINUTES)


def _is_locked(agent: Agent) -> bool:
    """True when the account is currently locked out."""
    return bool(agent.locked_until and agent.locked_until > datetime.utcnow())


def record_login_failure(db: Session, agent: Agent) -> None:
    """Bump the failure counter and lock when the threshold is reached.

    Only ever called for an account that EXISTS (a real password mismatch).
    Unknown identifiers are not tracked — there is no row to track and doing
    so would let an attacker create arbitrary rows.
    """
    agent.failed_login_count = (agent.failed_login_count or 0) + 1
    if agent.failed_login_count >= LOGIN_LOCKOUT_THRESHOLD:
        agent.locked_until = datetime.utcnow() + timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
    db.add(agent)
    db.commit()


def record_login_success(db: Session, agent: Agent) -> None:
    """Reset failure state and stamp the last successful sign-in."""
    agent.failed_login_count = 0
    agent.locked_until = None
    agent.last_login_at = datetime.utcnow()
    db.add(agent)
    db.commit()


# ---------------------------------------------------------------- roles

def load_role_keys(db: Session, agent: Agent) -> list:
    """Effective, normalised role keys for a staff identity.

    Primary role (``agents.role``) + any EXTRA roles from ``agent_roles``.
    Unknown/legacy values are normalised (or dropped) by rbac.effective_roles.
    """
    extra = [
        row.role_key for row in
        db.query(AgentRole.role_key).filter(AgentRole.agent_id == agent.id).all()
    ]
    return rbac.effective_roles(agent.role, extra)


def cache_permissions(db: Session, agent: Agent) -> Agent:
    """Resolve roles once and cache the permission set on the instance.

    Called by get_current_agent so every downstream ``has_permission`` check
    in the same request is a cheap set lookup with no extra queries.
    """
    agent._rbac_roles = load_role_keys(db, agent)
    agent._rbac_permissions = rbac.permissions_for_roles(agent._rbac_roles)
    return agent


def permissions_of(agent: Agent) -> set:
    """Effective permission set (falls back to primary role if not cached)."""
    return set(rbac.cached_permissions(agent))


def roles_of(agent: Agent) -> list:
    """Effective role keys (falls back to primary role if not cached)."""
    cached = getattr(agent, "_rbac_roles", None)
    if cached is not None:
        return list(cached)
    return rbac.effective_roles(getattr(agent, "role", None))


# ---------------------------------------------------------------- customers

def get_customer_token(request: Request) -> Optional[str]:
    return request.cookies.get(CUSTOMER_COOKIE)


def find_visitor_customer(db: Session, request: Request) -> Optional[Customer]:
    """Resolve the visitor behind the customer cookie without creating one."""
    token = get_customer_token(request)
    if not token:
        return None
    return (
        db.query(Customer)
        .filter(Customer.token_hash == Customer.hash_token(token))
        .first()
    )


def get_or_create_customer(db: Session, request: Request, response: Response) -> Customer:
    """Identify (or start) the public visitor for chat ownership scoping."""
    token = get_customer_token(request)
    customer = None
    if token:
        customer = (
            db.query(Customer)
            .filter(Customer.token_hash == Customer.hash_token(token))
            .first()
        )
    if customer is None:
        token = Customer.new_token()
        customer = Customer(token_hash=Customer.hash_token(token))
        db.add(customer)
        db.commit()
        db.refresh(customer)
        response.set_cookie(
            key=CUSTOMER_COOKIE,
            value=token,
            httponly=True,
            samesite="lax",
            secure=settings.COOKIE_SECURE,
            max_age=365 * 24 * 3600,
            path="/",
        )
    return customer


def set_customer_cookie(response: Response, token: str, max_age_days: int = 365) -> None:
    """Point the browser at a (possibly different) customer row."""
    response.set_cookie(
        key=CUSTOMER_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        max_age=max_age_days * 24 * 3600,
        path="/",
    )


def clear_customer_cookie(response: Response) -> None:
    response.delete_cookie(CUSTOMER_COOKIE, path="/")


def reissue_customer_token(db: Session, customer: Customer) -> str:
    """Rotate the customer's token (used at sign-in/register). Returns raw token."""
    token = Customer.new_token()
    customer.token_hash = Customer.hash_token(token)
    db.add(customer)
    db.commit()
    return token


def claim_guest_conversations(db: Session, guest: Customer, account: Customer) -> None:
    """Move a guest's chats/saves onto their account so history survives sign-in."""
    if guest.id == account.id:
        return
    (
        db.query(Conversation)
        .filter(Conversation.customer_id == guest.id)
        .update({"customer_id": account.id}, synchronize_session=False)
    )
    (
        db.query(SavedProperty)
        .filter(SavedProperty.customer_id == guest.id)
        .update({"customer_id": account.id}, synchronize_session=False)
    )
    # Carry over contact details the guest shared in chat (never overwrite)
    if not account.name and guest.name:
        account.name = guest.name
    if not account.phone and guest.phone:
        account.phone = guest.phone
    if not account.email and guest.email:
        account.email = guest.email
    db.commit()


# ---------------------------------------------------------------- RBAC scope

def lead_in_scope(agent: Agent, lead) -> bool:
    """Role-based data scope, driven by PERMISSIONS not role-name strings.

    - holds ``leads.read_all`` (admin, sales manager) → every lead
    - otherwise (agent, support) → leads assigned to them, plus unassigned
      leads (the shared pickup pool) so new AI leads are visible to the team.
    """
    if rbac.has_permission(agent, "leads.read_all"):
        return True
    return lead.assigned_agent_id is None or lead.assigned_agent_id == agent.id


def scoped_lead_query(db: Session, agent: Agent):
    """Leads this agent is allowed to see (permission-scoped)."""
    q = db.query(Lead)
    if not rbac.has_permission(agent, "leads.read_all"):
        q = q.filter(
            (Lead.assigned_agent_id.is_(None)) | (Lead.assigned_agent_id == agent.id)
        )
    return q


# ---------------------------------------------------------------- dependencies
# Reusable FastAPI authorisation dependencies. These enforce authorization on
# the SERVER for every protected request; frontend route guards are UX only.
#
# Contract:
#   401 — no valid session (unauthenticated)
#   403 — authenticated but lacking the required permission/role
# Neither response leaks whether a protected record exists.

def require_authenticated_user(
    agent: Agent = Depends(get_current_agent),
) -> Agent:
    """Baseline: any signed-in staff identity. Raises 401 via get_current_agent."""
    return agent


def require_roles(*role_keys: str):
    """Dependency factory: caller must hold at least one of ``role_keys``.

    Role names are matched against the NORMALISED registry keys, never the raw
    client input. Unknown role keys in the requirement raise at import time.
    """
    unknown = [r for r in role_keys if not rbac.is_known_role(r)]
    if unknown:
        raise RuntimeError(f"require_roles: unknown role(s) {unknown}")

    def dependency(agent: Agent = Depends(get_current_agent)) -> Agent:
        # get_current_agent already cached the full effective role list.
        if not set(roles_of(agent)) & set(role_keys):
            raise HTTPException(status_code=403, detail="Not authorised for this action")
        return agent

    return dependency


def require_permissions(*permission_keys: str, mode: str = "all"):
    """Dependency factory: caller must hold the required permission(s).

    Args:
        permission_keys: one or more permission keys from rbac.PERMISSIONS.
        mode: "all" (default) requires every listed permission; "any" requires
            at least one.

    Unknown permission keys raise at import time (fail fast, not at request
    time). Authorisation is computed from the DB-assigned roles cached on the
    request — a client-supplied role/permission is never consulted.
    """
    unknown = [p for p in permission_keys if p not in rbac.ALL_PERMISSION_KEYS]
    if unknown:
        raise RuntimeError(f"require_permissions: unknown permission(s) {unknown}")

    def dependency(agent: Agent = Depends(get_current_agent)) -> Agent:
        perms = rbac.cached_permissions(agent)
        ok = (
            all(p in perms for p in permission_keys) if mode == "all"
            else any(p in perms for p in permission_keys)
        )
        if not ok:
            raise HTTPException(status_code=403, detail="Not authorised for this action")
        return agent

    return dependency


def ensure_permission(agent: Agent, permission_key: str) -> None:
    """Imperative form for checks inside an already-resolved handler.

    Raises 403 when the permission is missing. Use the dependency form for
    whole-route gates; use this for conditional in-handler checks.
    """
    if not rbac.has_permission(agent, permission_key):
        raise HTTPException(status_code=403, detail="Not authorised for this action")
