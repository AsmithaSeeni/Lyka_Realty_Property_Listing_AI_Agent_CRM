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

from app.database import (
    Agent, AgentSession, Conversation, Customer, Lead, SavedProperty, get_db,
)

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

    # Expose the validated token so logout can revoke exactly this session
    request.state.session_token = token
    return agent


def set_agent_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=AGENT_COOKIE,
        value=token,
        httponly=True,          # JS can never read the session token
        samesite="lax",         # no cross-site sends; works on the Vite proxy
        secure=False,           # localhost is http; set True behind TLS
        max_age=SESSION_TTL_HOURS * 3600,
        path="/",
    )


def clear_agent_cookie(response: Response) -> None:
    response.delete_cookie(AGENT_COOKIE, path="/")


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
            secure=False,
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
        secure=False,
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
    """Role-based data scope.

    - admin  → every lead
    - agent  → leads assigned to them, plus unassigned leads (the shared
               pickup pool) so new AI leads are visible to the sales team.
    """
    if agent.role == "admin":
        return True
    return lead.assigned_agent_id is None or lead.assigned_agent_id == agent.id


def scoped_lead_query(db: Session, agent: Agent):
    """Leads this agent is allowed to see (admin sees everything)."""
    q = db.query(Lead)
    if agent.role != "admin":
        q = q.filter(
            (Lead.assigned_agent_id.is_(None)) | (Lead.assigned_agent_id == agent.id)
        )
    return q
