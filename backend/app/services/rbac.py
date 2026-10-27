"""Central role & permission registry (Phase 2 — RBAC).

This module is the SINGLE SOURCE OF TRUTH for what each business role is
allowed to do. It replaces the eight hard-coded ``agent.role == "admin"``
comparisons that were previously scattered across ``main.py`` and
``services/auth.py``.

Design
------
- **Roles** group **permissions**; **permissions** gate individual actions.
- The registry is data (``ROLE_REGISTRY``), not code branches, so adding a
  role or permission never means editing authorisation call sites again.
- Every role carries a ``landing`` route, a ``module`` status (``"crm"`` when
  a real dashboard exists, ``"pending"`` when the module is not yet built) and
  a ``priority`` used to pick the default landing page for multi-role users.
- Only Real Estate Agent, System Administrator and Customer map to features
  that actually exist today. HR / Payroll / Operations / Finance / Property
  Manager / Support roles receive a genuine permission foundation so
  authorisation is real and extensible, but their dashboards are explicitly
  marked "not yet implemented". No employee, salary, payslip or attendance
  data is fabricated anywhere in this system.
- Authorisation is ALWAYS computed server-side from the database-assigned
  roles. A role or permission supplied by a client in a body, URL, cookie or
  frontend store is ignored for authorization decisions.
"""

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Optional

# ---------------------------------------------------------------- permissions


@dataclass(frozen=True)
class Permission:
    """One capability. ``key`` is the API-visible string; ``description`` is
    human-readable documentation only."""

    key: str
    description: str = ""


def _p(key: str, description: str = "") -> Permission:
    return Permission(key, description)


# The permission catalogue, adapted to the features that actually exist.
PERMISSIONS: Dict[str, Permission] = {
    p.key: p
    for p in (
        # ---- user & role administration (Phase 5) ----
        _p("users.read", "View staff accounts"),
        _p("users.create", "Create staff accounts"),
        _p("users.update", "Edit staff accounts and profiles"),
        _p("users.suspend", "Suspend / reactivate staff accounts"),
        _p("roles.read", "View the role registry"),
        _p("roles.manage", "Grant or revoke roles"),
        # ---- property listings ----
        _p("properties.read", "Browse property listings"),
        _p("properties.create", "Create property listings"),
        _p("properties.update", "Edit property listings"),
        _p("properties.delete", "Delete property listings"),
        # ---- CRM leads ----
        _p("leads.read_assigned", "Read leads assigned to you"),
        _p("leads.read_team", "Read leads assigned to your team"),
        _p("leads.read_all", "Read every lead"),
        _p("leads.create", "Create leads"),
        _p("leads.update", "Edit leads in scope"),
        _p("leads.assign", "Assign leads to any agent"),
        # ---- conversations & follow-ups ----
        _p("conversations.read_authorized", "Read customer conversations in scope"),
        _p("conversations.read_all", "Read every customer conversation"),
        _p("followups.manage_assigned", "Manage follow-ups on leads in scope"),
        # ---- HR (foundation only — no HR module exists yet) ----
        _p("hr.employees.read", "Read employee records (HR module not built)"),
        _p("hr.employees.manage", "Manage employee records (HR module not built)"),
        _p("hr.attendance.read", "Read attendance (HR module not built)"),
        _p("hr.attendance.manage", "Manage attendance (HR module not built)"),
        # ---- Payroll (foundation only — no payroll module exists yet) ----
        _p("payroll.read_own", "Read your own payroll (module not built)"),
        _p("payroll.read_authorized", "Read authorised payroll records (module not built)"),
        _p("payroll.calculate", "Run payroll calculation (module not built)"),
        _p("payroll.approve", "Approve payroll (module not built)"),
        _p("payroll.manage", "Administer payroll (module not built)"),
        # ---- reporting ----
        _p("reports.read_team", "Read team reports"),
        _p("reports.read_all", "Read organisation-wide reports"),
        # ---- audit ----
        _p("audit.read", "Read the security audit log"),
        # ---- customer self-service (implicit role "customer") ----
        _p("chat.use", "Use the LykAI concierge"),
        _p("conversations.read_own", "Read your own conversation history"),
        _p("saved.manage", "Save and unsave properties"),
        _p("profile.update_own", "Update your own profile"),
    )
}

ALL_PERMISSION_KEYS: FrozenSet[str] = frozenset(PERMISSIONS)


# ---------------------------------------------------------------- roles


@dataclass(frozen=True)
class RoleSpec:
    key: str
    display_name: str
    description: str
    landing: str                 # post-login route for this role alone
    module: str                  # "crm" (real) | "pending" (not built yet)
    priority: int                # lower wins for multi-role default landing
    permissions: FrozenSet[str] = field(default_factory=frozenset)


def _role(
    key: str,
    display_name: str,
    description: str,
    landing: str,
    module: str,
    priority: int,
    permissions: Iterable[str],
) -> RoleSpec:
    perms = frozenset(permissions)
    unknown = perms - ALL_PERMISSION_KEYS
    if unknown:  # guard against registry typos at import time
        raise ValueError(f"Role {key!r} references unknown permissions: {sorted(unknown)}")
    return RoleSpec(
        key=key,
        display_name=display_name,
        description=description,
        landing=landing,
        module=module,
        priority=priority,
        permissions=perms,
    )


# Shared building blocks -------------------------------------------------

_CRM_LEAD_SCOPE = {
    "properties.read",
    "leads.read_assigned",
    "leads.create",
    "leads.update",
    "conversations.read_authorized",
    "followups.manage_assigned",
    "reports.read_team",
}

_ROLE_LIST: List[RoleSpec] = [
    # ---- System Administrator (highest privilege) ----
    _role(
        "admin",
        "System Administrator",
        "Full administrative control over accounts, roles and all modules.",
        "/agent/dashboard",
        "crm",
        10,
        sorted(ALL_PERMISSION_KEYS - {"chat.use", "conversations.read_own",
                                      "saved.manage", "profile.update_own"}),
    ),
    # ---- Sales Manager / Team Lead ----
    _role(
        "sales_manager",
        "Sales Manager",
        "Leads the sales team; sees every lead and conversation in the org.",
        "/agent/dashboard",
        "crm",
        20,
        sorted(
            _CRM_LEAD_SCOPE
            | {"leads.read_all", "leads.assign", "conversations.read_all",
               "reports.read_all", "users.read"}
        ),
    ),
    # ---- Real Estate Agent (the existing "agent" role) ----
    _role(
        "agent",
        "Real Estate Agent",
        "Works assigned leads and the shared pickup pool.",
        "/agent/dashboard",
        "crm",
        30,
        sorted(_CRM_LEAD_SCOPE),
    ),
    # ---- Customer Support ----
    _role(
        "support",
        "Customer Support",
        "Reads customer conversations to assist; no lead editing rights.",
        "/agent/dashboard",
        "crm",
        40,
        sorted({"properties.read", "leads.read_assigned",
                "conversations.read_authorized", "reports.read_team"}),
    ),
    # ---- Property / Listing Manager ----
    _role(
        "property_manager",
        "Property Manager",
        "Owns the property catalogue. Listing-management UI is not built yet.",
        "/properties/manage",
        "pending",
        50,
        sorted({"properties.read", "properties.create", "properties.update",
                "properties.delete"}),
    ),
    # ---- Operations Manager ----
    _role(
        "operations_manager",
        "Operations Manager",
        "Operational oversight. Operations module is not built yet.",
        "/operations/dashboard",
        "pending",
        60,
        sorted({"properties.read", "reports.read_all", "leads.read_team"}),
    ),
    # ---- Finance / Accounts ----
    _role(
        "finance",
        "Finance",
        "Financial reporting access. Finance module is not built yet.",
        "/finance/dashboard",
        "pending",
        70,
        sorted({"reports.read_all", "payroll.read_authorized"}),
    ),
    # ---- HR Manager ----
    _role(
        "hr_manager",
        "HR Manager",
        "Manages employee records. HR module is not built yet.",
        "/hr/dashboard",
        "pending",
        80,
        sorted({"hr.employees.read", "hr.employees.manage",
                "hr.attendance.read", "hr.attendance.manage",
                "users.read", "reports.read_team"}),
    ),
    # ---- HR staff ----
    _role(
        "hr_staff",
        "HR Staff",
        "Reads employee records. HR module is not built yet.",
        "/hr/dashboard",
        "pending",
        85,
        sorted({"hr.employees.read", "hr.attendance.read"}),
    ),
    # ---- Payroll Officer ----
    _role(
        "payroll_officer",
        "Payroll Officer",
        "Calculates and approves payroll. Payroll module is not built yet.",
        "/payroll/dashboard",
        "pending",
        90,
        sorted({"payroll.read_authorized", "payroll.calculate",
                "payroll.approve", "payroll.manage", "reports.read_team"}),
    ),
]

ROLE_REGISTRY: Dict[str, RoleSpec] = {r.key: r for r in _ROLE_LIST}

# The implicit role every signed-in customer holds. Customers are not staff
# and never appear in the `agents`/`agent_roles` tables.
CUSTOMER_ROLE = "customer"
CUSTOMER_LANDING = "/"

_CUSTOMER_SPEC = RoleSpec(
    key=CUSTOMER_ROLE,
    display_name="Customer",
    description="Property seeker using the public site and LykAI concierge.",
    landing=CUSTOMER_LANDING,
    module="customer",
    priority=1000,
    permissions=frozenset({"properties.read", "chat.use",
                           "conversations.read_own", "saved.manage",
                           "profile.update_own"}),
)
ROLE_REGISTRY[CUSTOMER_ROLE] = _CUSTOMER_SPEC


# Legacy role strings that must keep resolving (the `agents.role` column has
# historically only ever held "admin" or "agent").
_LEGACY_ALIASES = {"admin": "admin", "agent": "agent"}


def normalize_role(raw: Optional[str]) -> Optional[str]:
    """Map a stored role value to a registry key (or None if unknown)."""
    if not raw:
        return None
    key = str(raw).strip().lower()
    if key in _LEGACY_ALIASES:
        return _LEGACY_ALIASES[key]
    return key if key in ROLE_REGISTRY else None


def is_known_role(raw: Optional[str]) -> bool:
    return normalize_role(raw) is not None


# ---------------------------------------------------------------- resolution


def permissions_for_roles(role_keys: Iterable[str]) -> FrozenSet[str]:
    """Union of the permissions of every known role in ``role_keys``."""
    perms: set = set()
    for key in role_keys:
        spec = ROLE_REGISTRY.get(normalize_role(key) or "")
        if spec is not None:
            perms |= spec.permissions
    return frozenset(perms)


def landing_for_roles(role_keys: Iterable[str]) -> str:
    """Default landing page for a set of roles.

    Multi-role policy: the role with the LOWEST ``priority`` number wins
    (System Administrator beats Sales Manager beats Agent, and so on). This
    is deterministic and documented; the user can still navigate anywhere their
    permissions allow.
    """
    best: Optional[RoleSpec] = None
    for key in role_keys:
        spec = ROLE_REGISTRY.get(normalize_role(key) or "")
        if spec is None:
            continue
        if best is None or spec.priority < best.priority:
            best = spec
    return best.landing if best is not None else CUSTOMER_LANDING


def module_for_roles(role_keys: Iterable[str]) -> str:
    """Module status of the winning role ("crm" | "pending" | "customer")."""
    best: Optional[RoleSpec] = None
    for key in role_keys:
        spec = ROLE_REGISTRY.get(normalize_role(key) or "")
        if spec is None:
            continue
        if best is None or spec.priority < best.priority:
            best = spec
    return best.module if best is not None else "customer"


def effective_roles(primary_role: Optional[str], extra_roles: Iterable[str] = ()) -> List[str]:
    """De-duplicated, registry-normalised role list for an identity.

    ``primary_role`` is the legacy ``agents.role`` column (always present and
    authoritative on its own). ``extra_roles`` are additional rows from the
    ``agent_roles`` table. Unknown values are dropped rather than trusted.
    """
    seen: List[str] = []
    for raw in (primary_role, *tuple(extra_roles)):
        key = normalize_role(raw)
        if key is not None and key not in seen:
            seen.append(key)
    return seen


def cached_permissions(agent) -> FrozenSet[str]:
    """Permission set for an ``Agent`` ORM object without touching the database.

    ``get_current_agent`` resolves the full multi-role set once per request and
    caches it on the instance (``_rbac_permissions``). Agents loaded straight
    from the ORM (tests, background jobs) fall back to the primary role, which
    is always authoritative on its own because ``agent_roles`` is backfilled
    from ``agents.role``.
    """
    cached = getattr(agent, "_rbac_permissions", None)
    if cached is not None:
        return cached
    return permissions_for_roles(effective_roles(getattr(agent, "role", None)))


def has_permission(agent, permission_key: str) -> bool:
    """True when ``agent`` holds ``permission_key``. Never trusts client input."""
    return permission_key in cached_permissions(agent)


def has_any_permission(agent, permission_keys: Iterable[str]) -> bool:
    perms = cached_permissions(agent)
    return any(p in perms for p in permission_keys)


def public_role_view(role_keys: Iterable[str]) -> List[dict]:
    """Safe, API-visible description of each role (no internal bookkeeping)."""
    out = []
    for key in role_keys:
        spec = ROLE_REGISTRY.get(normalize_role(key) or "")
        if spec is not None:
            out.append({
                "key": spec.key,
                "display_name": spec.display_name,
                "module": spec.module,
            })
    return out
