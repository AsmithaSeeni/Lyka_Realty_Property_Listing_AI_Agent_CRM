"""Centralized Query Scoping and Object-Level Authorization Service.

This service is the SINGLE REUSABLE SOURCE OF TRUTH for SQL-level filtering
and data isolation across all CRM entities:
  - Leads
  - Conversations
  - Messages
  - Customers
  - Follow-ups
  - Appointments / Viewings
  - Offers & Deals
  - Dashboard Aggregates & Analytics

Access Policy Enforcement:
- superadmin / admin: Unrestricted access across all CRM records.
- sales_manager: Authorized team/branch records (bounded; never silent global access).
- agent (Sales Agent): Strictly restricted to:
    1. Assigned leads (Lead.assigned_agent_id == current_agent.id).
    2. Conversations linked to those assigned leads (lead_id NOT NULL and assigned to agent).
    3. Messages belonging to authorized conversations.
    4. Customer profiles associated with those assigned leads or appointments.
    5. Follow-ups, appointments, offers, and deals associated with assigned leads.
    6. Personal activity and dashboard statistics only.
    7. NO unassigned pool visibility unless explicitly granted 'leads.read_unassigned'.
    8. NO unlinked conversations (lead_id IS NULL) visibility (admin-only).
- customer: Own portal profile, own conversations, own saved properties.
"""

from typing import Optional
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, Query

from app.database import (
    Agent, Lead, Conversation, Message, Customer,
    FollowUp, Appointment, Offer, Deal,
)
from app.services import rbac


# ---------------------------------------------------------------------------
# Capability Flags
# ---------------------------------------------------------------------------

def can_read_all_leads(agent: Agent) -> bool:
    """Return True if agent has global lead visibility (superadmin, admin)."""
    return rbac.has_permission(agent, "leads.read_all")


def can_read_unassigned_leads(agent: Agent) -> bool:
    """Return True if agent has permission to inspect the shared unassigned lead pool."""
    return can_read_all_leads(agent) or rbac.has_permission(agent, "leads.read_unassigned")


def can_read_all_conversations(agent: Agent) -> bool:
    """Return True if agent has global conversation visibility (superadmin, admin)."""
    return rbac.has_permission(agent, "conversations.read_all")


# ---------------------------------------------------------------------------
# Leads Scoping
# ---------------------------------------------------------------------------

def lead_in_scope(agent: Agent, lead: Optional[Lead]) -> bool:
    """Evaluate whether a specific Lead instance is accessible to the agent.
    
    A regular sales agent can ONLY access leads currently assigned to their account.
    Unassigned leads are NOT visible unless 'leads.read_unassigned' is granted.
    When a lead is reassigned to another agent, the original agent loses access.
    Creation ownership and current assignment ownership remain separate concepts.
    """
    if lead is None:
        return False
    if can_read_all_leads(agent):
        return True
    if lead.assigned_agent_id == agent.id:
        return True
    if lead.assigned_agent_id is None and can_read_unassigned_leads(agent):
        return True
    return False


def scoped_lead_query(db: Session, agent: Agent) -> Query:
    """Return a SQLAlchemy query for leads filtered strictly by agent authorization."""
    q = db.query(Lead)
    if can_read_all_leads(agent):
        return q
    if can_read_unassigned_leads(agent):
        return q.filter(
            or_(
                Lead.assigned_agent_id == agent.id,
                Lead.assigned_agent_id.is_(None),
            )
        )
    return q.filter(Lead.assigned_agent_id == agent.id)


# ---------------------------------------------------------------------------
# Conversations & Messages Scoping
# ---------------------------------------------------------------------------

def conversation_in_scope(db: Session, agent: Agent, conv: Optional[Conversation]) -> bool:
    """Evaluate whether a Conversation instance is accessible to the agent.
    
    For a sales agent:
    - Must be linked to a lead (lead_id is NOT NULL).
    - That linked lead must be assigned to this agent (assigned_agent_id == agent.id).
    - Unlinked conversations (lead_id IS NULL) are admin-only; never exposed to agents.
    """
    if conv is None:
        return False
    if can_read_all_conversations(agent):
        return True
    if conv.lead_id is None:
        # Unlinked conversation: protected from sales agents until officially reconciled
        return False
    if conv.lead is not None:
        return lead_in_scope(agent, conv.lead)
    # Lazy/unloaded relationship lookup
    lead = db.query(Lead).filter(Lead.id == conv.lead_id).first()
    return lead is not None and lead_in_scope(agent, lead)


def scoped_conversation_query(db: Session, agent: Agent) -> Query:
    """Return a SQLAlchemy query for conversations accessible to the agent.
    
    Admins see all conversations.
    Agents see ONLY conversations linked to their assigned leads.
    Conversations with lead_id NULL are excluded for non-admins.
    """
    q = db.query(Conversation)
    if can_read_all_conversations(agent):
        return q
    assigned_leads_subquery = (
        scoped_lead_query(db, agent)
        .with_entities(Lead.id)
        .subquery()
    )
    return q.filter(
        Conversation.lead_id.isnot(None),
        Conversation.lead_id.in_(assigned_leads_subquery),
    )


# ---------------------------------------------------------------------------
# Customer Profiles Scoping
# ---------------------------------------------------------------------------

def customer_in_scope(db: Session, agent: Agent, customer: Optional[Customer]) -> bool:
    """Evaluate whether a Customer dossier is accessible to the agent.
    
    Admins see all customer profiles.
    Agents see ONLY customers who have an assigned lead or an appointment with this agent.
    """
    if customer is None:
        return False
    if can_read_all_leads(agent):
        return True
    
    c_email = (customer.email or "").strip().lower()
    c_phone = (customer.phone or "").strip()
    
    # Check for assigned lead
    lead_conds = []
    if c_email:
        lead_conds.append(func.lower(Lead.email) == c_email)
    if c_phone:
        lead_conds.append(Lead.phone == c_phone)
    
    if lead_conds:
        has_lead = db.query(Lead.id).filter(
            Lead.assigned_agent_id == agent.id,
            or_(*lead_conds)
        ).first() is not None
        if has_lead:
            return True
            
    # Check for appointment
    has_appt = db.query(Appointment.id).filter(
        Appointment.assigned_agent_id == agent.id,
        Appointment.customer_id == customer.id,
    ).first() is not None
    return has_appt


def scoped_customer_query(db: Session, agent: Agent) -> Query:
    """Return a SQLAlchemy query for customers accessible to the agent."""
    q = db.query(Customer)
    if can_read_all_leads(agent):
        return q
        
    agent_lead_emails = (
        db.query(func.lower(Lead.email))
        .filter(Lead.assigned_agent_id == agent.id, Lead.email.isnot(None))
        .subquery()
    )
    agent_lead_phones = (
        db.query(Lead.phone)
        .filter(Lead.assigned_agent_id == agent.id, Lead.phone.isnot(None))
        .subquery()
    )
    agent_appt_cust_ids = (
        db.query(Appointment.customer_id)
        .filter(Appointment.assigned_agent_id == agent.id, Appointment.customer_id.isnot(None))
        .subquery()
    )
    return q.filter(
        or_(
            func.lower(Customer.email).in_(agent_lead_emails),
            Customer.phone.in_(agent_lead_phones),
            Customer.id.in_(agent_appt_cust_ids),
        )
    )


# ---------------------------------------------------------------------------
# Follow-ups Scoping
# ---------------------------------------------------------------------------

def followup_in_scope(agent: Agent, fu: Optional[FollowUp]) -> bool:
    """Evaluate whether a FollowUp is in scope."""
    if fu is None:
        return False
    if can_read_all_leads(agent):
        return True
    if fu.lead is not None:
        return lead_in_scope(agent, fu.lead)
    return False


def scoped_followup_query(db: Session, agent: Agent) -> Query:
    """Return a SQLAlchemy query for follow-ups on leads in agent scope."""
    if can_read_all_leads(agent):
        return db.query(FollowUp)
    assigned_leads_subquery = (
        scoped_lead_query(db, agent)
        .with_entities(Lead.id)
        .subquery()
    )
    return db.query(FollowUp).filter(FollowUp.lead_id.in_(assigned_leads_subquery))


# ---------------------------------------------------------------------------
# Appointments, Offers, Deals Scoping
# ---------------------------------------------------------------------------

def appointment_in_scope(agent: Agent, appt: Optional[Appointment]) -> bool:
    if appt is None:
        return False
    if can_read_all_leads(agent):
        return True
    if appt.assigned_agent_id == agent.id:
        return True
    if appt.lead is not None and lead_in_scope(agent, appt.lead):
        return True
    return False


def scoped_appointment_query(db: Session, agent: Agent) -> Query:
    if can_read_all_leads(agent):
        return db.query(Appointment)
    assigned_leads_subquery = (
        scoped_lead_query(db, agent)
        .with_entities(Lead.id)
        .subquery()
    )
    return db.query(Appointment).filter(
        or_(
            Appointment.assigned_agent_id == agent.id,
            Appointment.lead_id.in_(assigned_leads_subquery),
        )
    )


def offer_in_scope(agent: Agent, offer: Optional[Offer]) -> bool:
    if offer is None:
        return False
    if can_read_all_leads(agent):
        return True
    if offer.assigned_agent_id == agent.id:
        return True
    if offer.lead is not None and lead_in_scope(agent, offer.lead):
        return True
    return False


def scoped_offer_query(db: Session, agent: Agent) -> Query:
    if can_read_all_leads(agent):
        return db.query(Offer)
    assigned_leads_subquery = (
        scoped_lead_query(db, agent)
        .with_entities(Lead.id)
        .subquery()
    )
    return db.query(Offer).filter(
        or_(
            Offer.assigned_agent_id == agent.id,
            Offer.lead_id.in_(assigned_leads_subquery),
        )
    )


def deal_in_scope(agent: Agent, deal: Optional[Deal]) -> bool:
    if deal is None:
        return False
    if can_read_all_leads(agent):
        return True
    if deal.assigned_agent_id == agent.id:
        return True
    if deal.lead is not None and lead_in_scope(agent, deal.lead):
        return True
    return False


def scoped_deal_query(db: Session, agent: Agent) -> Query:
    if can_read_all_leads(agent):
        return db.query(Deal)
    assigned_leads_subquery = (
        scoped_lead_query(db, agent)
        .with_entities(Lead.id)
        .subquery()
    )
    return db.query(Deal).filter(
        or_(
            Deal.assigned_agent_id == agent.id,
            Deal.lead_id.in_(assigned_leads_subquery),
        )
    )

