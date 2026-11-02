"""Stage 6J — HR Management Service Module.

Provides business logic and database queries for:
- Employee Master Records & Directory
- Attendance Tracking (Check-in, Check-out, Timezone handling, Manual Corrections)
- Leave Management (Applications, Approvals, Rejections, Cancellations)
- HR Dashboard Aggregates & Metrics
- Audit Logging & Status Transitions
"""

from datetime import datetime, date, time, timedelta
from typing import Dict, List, Optional, Tuple, Any
from zoneinfo import ZoneInfo
from sqlalchemy import func, or_, and_, desc
from sqlalchemy.orm import Session

from app.database import (
    Employee, Attendance, LeaveRequest, Agent, AuditLog
)
from app.services import audit as auditlog

DUBAI_TZ = ZoneInfo("Asia/Dubai")


def now_dubai() -> datetime:
    """Return current wall-clock datetime in Asia/Dubai timezone."""
    return datetime.now(DUBAI_TZ)


def today_dubai() -> date:
    """Return today's date in Asia/Dubai timezone."""
    return now_dubai().date()


def _to_dubai_iso(dt: Optional[datetime]) -> Optional[str]:
    """Convert UTC or naive datetime to ISO string in Asia/Dubai."""
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(DUBAI_TZ).isoformat()


# ---------------------------------------------------------------------------
# Employee Master Logic
# ---------------------------------------------------------------------------

def employee_dict(emp: Employee) -> Dict[str, Any]:
    """Format an Employee instance into a clean API response dictionary."""
    return {
        "id": emp.id,
        "employee_id": emp.employee_id,
        "agent_id": emp.agent_id,
        "full_name": emp.full_name,
        "official_email": emp.official_email,
        "contact_number": emp.contact_number,
        "department": emp.department,
        "designation": emp.designation,
        "reporting_manager_id": emp.reporting_manager_id,
        "reporting_manager_name": emp.reporting_manager.full_name if emp.reporting_manager else None,
        "employment_type": emp.employment_type,
        "joining_date": emp.joining_date.isoformat() if emp.joining_date else None,
        "employment_status": emp.employment_status,
        "crm_role": emp.crm_role,
        "branch": emp.branch,
        "is_active": emp.employment_status == "Active",
        "account": {
            "agent_id": emp.agent.id,
            "email": emp.agent.email,
            "username": emp.agent.username,
            "role": emp.agent.role,
            "is_active": emp.agent.is_active,
            "last_login_at": emp.agent.last_login_at.isoformat() if emp.agent.last_login_at else None,
            "created_at": emp.agent.created_at.isoformat() if emp.agent.created_at else None,
        } if emp.agent else None,
        "created_at": emp.created_at.isoformat() if emp.created_at else None,
        "updated_at": emp.updated_at.isoformat() if emp.updated_at else None,
    }


def list_employees(
    db: Session,
    department: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """Search, filter, and paginate employee master records."""
    query = db.query(Employee)

    if department and department.strip() and department.lower() != "all":
        query = query.filter(func.lower(Employee.department) == department.strip().lower())

    if status and status.strip() and status.lower() != "all":
        query = query.filter(func.lower(Employee.employment_status) == status.strip().lower())

    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        query = query.filter(
            or_(
                func.lower(Employee.full_name).ilike(needle),
                func.lower(Employee.official_email).ilike(needle),
                func.lower(Employee.employee_id).ilike(needle),
                func.lower(Employee.designation).ilike(needle),
            )
        )

    total = query.count()
    rows = (
        query.order_by(Employee.employee_id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [employee_dict(e) for e in rows], total


def get_employee(db: Session, employee_id: int) -> Optional[Employee]:
    return db.query(Employee).filter(Employee.id == employee_id).first()


def get_employee_by_agent_id(db: Session, agent_id: int) -> Optional[Employee]:
    return db.query(Employee).filter(Employee.agent_id == agent_id).first()


def ensure_employee_for_agent(db: Session, agent: Agent) -> Employee:
    """Ensure every Agent account has a synchronized Employee profile."""
    emp = db.query(Employee).filter(Employee.agent_id == agent.id).first()
    if emp:
        return emp

    # Generate sequential or formatted Employee ID
    emp_count = db.query(Employee).count()
    code = f"EMP-{100 + emp_count + 1}"

    dept = "Management" if agent.role in ("admin", "superadmin") else "Human Resources" if agent.role in ("hr", "hr_manager") else "Sales"
    desig = "System Administrator" if agent.role in ("admin", "superadmin") else "HR Manager" if agent.role in ("hr", "hr_manager") else "Real Estate Consultant"

    emp = Employee(
        agent_id=agent.id,
        employee_id=code,
        full_name=agent.full_name or agent.username.title(),
        official_email=agent.email,
        department=dept,
        designation=desig,
        employment_type="Full-time",
        joining_date=agent.created_at.date() if agent.created_at else today_dubai(),
        employment_status="Active" if agent.is_active else "Terminated",
        crm_role=agent.role,
        branch="Dubai Main Branch",
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def create_employee(
    db: Session,
    payload: Dict[str, Any],
    creator_agent_id: int,
) -> Employee:
    """Create a new employee and optional linked CRM user account."""
    emp_id = payload.get("employee_id") or f"EMP-{100 + db.query(Employee).count() + 1}"
    existing = db.query(Employee).filter(
        or_(Employee.employee_id == emp_id, Employee.official_email == payload["official_email"])
    ).first()
    if existing:
        raise ValueError("An employee with this Employee ID or official email already exists.")

    joining = payload.get("joining_date")
    if isinstance(joining, str) and joining:
        joining = date.fromisoformat(joining)
    elif not joining:
        joining = today_dubai()

    emp = Employee(
        agent_id=payload.get("agent_id"),
        employee_id=emp_id,
        full_name=payload["full_name"].strip(),
        official_email=payload["official_email"].strip().lower(),
        contact_number=(payload.get("contact_number") or "").strip() or None,
        department=payload.get("department", "Sales").strip(),
        designation=payload.get("designation", "Real Estate Consultant").strip(),
        reporting_manager_id=payload.get("reporting_manager_id"),
        employment_type=payload.get("employment_type", "Full-time"),
        joining_date=joining,
        employment_status=payload.get("employment_status", "Active"),
        crm_role=payload.get("crm_role", "agent"),
        branch=payload.get("branch", "Dubai Main Branch"),
        created_by=creator_agent_id,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)

    auditlog.write_audit(
        db,
        "hr.employee.created",
        actor_type="staff",
        actor_id=creator_agent_id,
        subject_type="employee",
        subject_id=emp.id,
        subject_label=f"{emp.employee_id} - {emp.full_name}",
        detail=f"dept={emp.department}; role={emp.crm_role}",
    )
    return emp


def update_employee(
    db: Session,
    emp: Employee,
    payload: Dict[str, Any],
    modifier_agent_id: int,
) -> Employee:
    """Update permitted fields on an employee profile."""
    for field in (
        "full_name", "contact_number", "department", "designation",
        "reporting_manager_id", "employment_type", "branch", "crm_role",
    ):
        if field in payload and payload[field] is not None:
            setattr(emp, field, payload[field])

    if "joining_date" in payload and payload["joining_date"]:
        j = payload["joining_date"]
        emp.joining_date = date.fromisoformat(j) if isinstance(j, str) else j

    if "employment_status" in payload and payload["employment_status"]:
        emp.employment_status = payload["employment_status"]
        if emp.agent:
            emp.agent.is_active = (emp.employment_status == "Active")

    emp.updated_by = modifier_agent_id
    emp.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(emp)

    auditlog.write_audit(
        db,
        "hr.employee.updated",
        actor_type="staff",
        actor_id=modifier_agent_id,
        subject_type="employee",
        subject_id=emp.id,
        subject_label=f"{emp.employee_id} - {emp.full_name}",
        detail=f"status={emp.employment_status}; dept={emp.department}",
    )
    return emp


def deactivate_employee(
    db: Session,
    emp: Employee,
    reason: str,
    modifier_agent_id: int,
) -> Employee:
    """Deactivate employee, revoke login session, and require lead reassignment."""
    emp.employment_status = "Terminated"
    emp.updated_by = modifier_agent_id
    emp.updated_at = datetime.utcnow()

    # Revoke CRM agent login if account exists
    if emp.agent:
        emp.agent.is_active = False
        try:
            from app.services.auth import revoke_all_sessions
            revoke_all_sessions(db, emp.agent.id)
        except Exception:
            pass

    db.commit()
    db.refresh(emp)

    auditlog.write_audit(
        db,
        "hr.employee.deactivated",
        actor_type="staff",
        actor_id=modifier_agent_id,
        subject_type="employee",
        subject_id=emp.id,
        subject_label=f"{emp.employee_id} - {emp.full_name}",
        detail=f"reason={reason[:200]}",
    )
    return emp


# ---------------------------------------------------------------------------
# Attendance Management Logic
# ---------------------------------------------------------------------------

def attendance_dict(att: Attendance) -> Dict[str, Any]:
    """Format Attendance model into JSON dictionary."""
    emp = att.employee
    return {
        "id": att.id,
        "employee_id": att.employee_id,
        "employee_code": emp.employee_id if emp else None,
        "employee_name": emp.full_name if emp else None,
        "department": emp.department if emp else None,
        "designation": emp.designation if emp else None,
        "attendance_date": att.attendance_date.isoformat(),
        "status": att.status,
        "check_in": _to_dubai_iso(att.check_in),
        "check_out": _to_dubai_iso(att.check_out),
        "shift": att.shift,
        "work_mode": getattr(att, "work_mode", None) or "OFFICE",
        "source": att.source,
        "notes": att.notes,
        "correction_reason": att.correction_reason,
        "created_at": att.created_at.isoformat() if att.created_at else None,
        "updated_at": att.updated_at.isoformat() if att.updated_at else None,
        "last_modified_by": att.last_modified_by,
    }


def record_check_in(
    db: Session,
    emp: Employee,
    shift: Optional[str] = None,
    notes: Optional[str] = None,
    work_mode: Optional[str] = "OFFICE",
) -> Attendance:
    """Record employee self-service check-in for today (Asia/Dubai date)."""
    t_date = today_dubai()
    existing = (
        db.query(Attendance)
        .filter(Attendance.employee_id == emp.id, Attendance.attendance_date == t_date)
        .first()
    )
    now_utc = datetime.utcnow()

    if existing and existing.check_in:
        raise ValueError("You have already checked in today.")

    # Determine status & mode (e.g. Late if check-in after 09:30 GST for office mode)
    raw_mode = (work_mode or "OFFICE").strip().upper()
    if raw_mode in ("WORK_FROM_HOME", "WFH"):
        eff_work_mode = "WORK_FROM_HOME"
        status = "Work From Home"
    elif raw_mode in ("FIELD_DUTY", "FIELD"):
        eff_work_mode = "FIELD_DUTY"
        status = "Field Duty"
    else:
        eff_work_mode = "OFFICE"
        now_d = now_dubai()
        status = "Late" if (now_d.hour > 9 or (now_d.hour == 9 and now_d.minute > 30)) else "Present"

    if existing:
        existing.check_in = now_utc
        existing.status = status
        existing.work_mode = eff_work_mode
        if notes:
            existing.notes = f"{existing.notes or ''}\n{notes}".strip()
        existing.updated_at = now_utc
        att = existing
    else:
        att = Attendance(
            employee_id=emp.id,
            attendance_date=t_date,
            status=status,
            work_mode=eff_work_mode,
            check_in=now_utc,
            shift=shift or "Standard (09:00 - 18:00 GST)",
            source="web",
            notes=notes,
            created_by=emp.agent_id,
        )
        db.add(att)

    db.commit()
    db.refresh(att)

    auditlog.write_audit(
        db,
        "hr.attendance.check_in",
        actor_type="staff",
        actor_id=emp.agent_id or emp.id,
        subject_type="attendance",
        subject_id=att.id,
        subject_label=f"{emp.employee_id} Check-in {t_date}",
        detail=f"status={status}; time={_to_dubai_iso(att.check_in)}",
    )
    return att


def record_check_out(
    db: Session,
    emp: Employee,
    notes: Optional[str] = None,
) -> Attendance:
    """Record employee self-service check-out for today."""
    t_date = today_dubai()
    att = (
        db.query(Attendance)
        .filter(Attendance.employee_id == emp.id, Attendance.attendance_date == t_date)
        .first()
    )
    if not att or not att.check_in:
        raise ValueError("Cannot check out without an active check-in today.")

    now_utc = datetime.utcnow()
    att.check_out = now_utc
    if notes:
        att.notes = f"{att.notes or ''}\n{notes}".strip()
    att.updated_at = now_utc

    db.commit()
    db.refresh(att)

    auditlog.write_audit(
        db,
        "hr.attendance.check_out",
        actor_type="staff",
        actor_id=emp.agent_id or emp.id,
        subject_type="attendance",
        subject_id=att.id,
        subject_label=f"{emp.employee_id} Check-out {t_date}",
        detail=f"check_out={_to_dubai_iso(att.check_out)}",
    )
    return att


def get_today_attendance(db: Session, emp: Employee) -> Optional[Attendance]:
    """Retrieve today's attendance record for the employee."""
    return (
        db.query(Attendance)
        .filter(Attendance.employee_id == emp.id, Attendance.attendance_date == today_dubai())
        .first()
    )


def list_attendance(
    db: Session,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    employee_id: Optional[int] = None,
    department: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """List attendance records with filtering."""
    query = db.query(Attendance).join(Employee)

    if date_from:
        query = query.filter(Attendance.attendance_date >= date_from)
    if date_to:
        query = query.filter(Attendance.attendance_date <= date_to)
    if employee_id:
        query = query.filter(Attendance.employee_id == employee_id)
    if department and department.strip() and department.lower() != "all":
        query = query.filter(func.lower(Employee.department) == department.strip().lower())
    if status and status.strip() and status.lower() != "all":
        query = query.filter(func.lower(Attendance.status) == status.strip().lower())

    total = query.count()
    rows = (
        query.order_by(Attendance.attendance_date.desc(), Employee.employee_id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [attendance_dict(a) for a in rows], total


def correct_attendance(
    db: Session,
    attendance_id: int,
    new_status: str,
    new_check_in: Optional[datetime],
    new_check_out: Optional[datetime],
    reason: str,
    modifier_agent_id: int,
) -> Attendance:
    """HR-authorized manual attendance correction with reason and audit log."""
    att = db.query(Attendance).filter(Attendance.id == attendance_id).first()
    if not att:
        raise ValueError("Attendance record not found.")
    if not reason or len(reason.strip()) < 5:
        raise ValueError("A clear correction reason is required (minimum 5 characters).")

    old_status = att.status
    old_ci = _to_dubai_iso(att.check_in)
    old_co = _to_dubai_iso(att.check_out)

    att.status = new_status
    if new_check_in is not None:
        att.check_in = new_check_in
    if new_check_out is not None:
        att.check_out = new_check_out

    att.source = "manual_correction"
    att.correction_reason = f"[{now_dubai().strftime('%Y-%m-%d %H:%M')}] {reason.strip()}"
    att.last_modified_by = modifier_agent_id
    att.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(att)

    auditlog.write_audit(
        db,
        "hr.attendance.corrected",
        actor_type="staff",
        actor_id=modifier_agent_id,
        subject_type="attendance",
        subject_id=att.id,
        subject_label=f"Correction for Attendance #{att.id}",
        detail=f"old=({old_status},{old_ci},{old_co}); new=({new_status},{_to_dubai_iso(att.check_in)},{_to_dubai_iso(att.check_out)}); reason={reason[:100]}",
    )
    return att


# ---------------------------------------------------------------------------
# Leave Management Logic
# ---------------------------------------------------------------------------

def leave_dict(leave: LeaveRequest) -> Dict[str, Any]:
    emp = leave.employee
    return {
        "id": leave.id,
        "employee_id": leave.employee_id,
        "employee_code": emp.employee_id if emp else None,
        "employee_name": emp.full_name if emp else None,
        "department": emp.department if emp else None,
        "leave_type": leave.leave_type,
        "start_date": leave.start_date.isoformat(),
        "end_date": leave.end_date.isoformat(),
        "days_count": leave.days_count,
        "reason": leave.reason,
        "status": leave.status,
        "reviewed_by": leave.reviewed_by,
        "reviewer_name": leave.reviewer.full_name if leave.reviewer else None,
        "review_notes": leave.review_notes,
        "reviewed_at": _to_dubai_iso(leave.reviewed_at),
        "created_at": leave.created_at.isoformat() if leave.created_at else None,
    }


def submit_leave_request(
    db: Session,
    emp: Employee,
    leave_type: str,
    start_date: date,
    end_date: date,
    reason: str,
) -> LeaveRequest:
    """Submit a new employee leave request."""
    if end_date < start_date:
        raise ValueError("End date cannot be earlier than start date.")
    if not reason or len(reason.strip()) < 5:
        raise ValueError("Please provide a reason for your leave request (minimum 5 characters).")

    days = float((end_date - start_date).days + 1)
    req = LeaveRequest(
        employee_id=emp.id,
        leave_type=leave_type,
        start_date=start_date,
        end_date=end_date,
        days_count=days,
        reason=reason.strip(),
        status="pending",
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    auditlog.write_audit(
        db,
        "hr.leave.submitted",
        actor_type="staff",
        actor_id=emp.agent_id or emp.id,
        subject_type="leave_request",
        subject_id=req.id,
        subject_label=f"Leave {start_date} to {end_date}",
        detail=f"type={leave_type}; days={days}",
    )
    return req


def list_leave_requests(
    db: Session,
    employee_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    query = db.query(LeaveRequest).join(Employee)
    if employee_id:
        query = query.filter(LeaveRequest.employee_id == employee_id)
    if status and status.strip() and status.lower() != "all":
        query = query.filter(func.lower(LeaveRequest.status) == status.strip().lower())

    total = query.count()
    rows = (
        query.order_by(LeaveRequest.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [leave_dict(r) for r in rows], total


def review_leave_request(
    db: Session,
    request_id: int,
    approved: bool,
    review_notes: str,
    reviewer_agent_id: int,
) -> LeaveRequest:
    """Approve or reject an employee leave request."""
    req = db.query(LeaveRequest).filter(LeaveRequest.id == request_id).first()
    if not req:
        raise ValueError("Leave request not found.")
    if req.status != "pending":
        raise ValueError(f"Cannot review leave request with status '{req.status}'.")

    req.status = "approved" if approved else "rejected"
    req.review_notes = review_notes.strip() if review_notes else None
    req.reviewed_by = reviewer_agent_id
    req.reviewed_at = datetime.utcnow()
    req.updated_at = datetime.utcnow()

    # If approved, ensure attendance records for the dates are marked On Leave
    if approved:
        cur_d = req.start_date
        while cur_d <= req.end_date:
            att = (
                db.query(Attendance)
                .filter(Attendance.employee_id == req.employee_id, Attendance.attendance_date == cur_d)
                .first()
            )
            if att:
                att.status = "On Leave"
                att.notes = f"Approved {req.leave_type} #{req.id}"
            else:
                att = Attendance(
                    employee_id=req.employee_id,
                    attendance_date=cur_d,
                    status="On Leave",
                    notes=f"Approved {req.leave_type} #{req.id}",
                    source="system_auto",
                )
                db.add(att)
            cur_d += timedelta(days=1)

    db.commit()
    db.refresh(req)

    auditlog.write_audit(
        db,
        "hr.leave.reviewed",
        actor_type="staff",
        actor_id=reviewer_agent_id,
        subject_type="leave_request",
        subject_id=req.id,
        subject_label=f"Leave {req.id} {req.status}",
        detail=f"decision={req.status}; notes={review_notes[:100]}",
    )
    return req


def cancel_leave_request(
    db: Session,
    request_id: int,
    emp: Employee,
) -> LeaveRequest:
    """Employee cancel their own pending leave request."""
    req = (
        db.query(LeaveRequest)
        .filter(LeaveRequest.id == request_id, LeaveRequest.employee_id == emp.id)
        .first()
    )
    if not req:
        raise ValueError("Leave request not found.")
    if req.status != "pending":
        raise ValueError("Only pending leave requests can be cancelled.")

    req.status = "cancelled"
    req.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(req)

    auditlog.write_audit(
        db,
        "hr.leave.cancelled",
        actor_type="staff",
        actor_id=emp.agent_id or emp.id,
        subject_type="leave_request",
        subject_id=req.id,
        subject_label=f"Leave {req.id} cancelled",
        detail="Employee self-cancellation",
    )
    return req


# ---------------------------------------------------------------------------
# HR Dashboard Metrics
# ---------------------------------------------------------------------------

def get_hr_dashboard_stats(db: Session, target_date: Optional[date] = None) -> Dict[str, Any]:
    """Compute real PostgreSQL-backed metrics for the HR management dashboard."""
    t_date = target_date or today_dubai()

    total_emp = db.query(Employee).count()
    active_emp = db.query(Employee).filter(Employee.employment_status == "Active").count()

    # Attendance counts for target date
    att_rows = (
        db.query(Attendance.status, func.count(Attendance.id))
        .filter(Attendance.attendance_date == t_date)
        .group_by(Attendance.status)
        .all()
    )
    att_counts = {status: count for status, count in att_rows}

    present_today = att_counts.get("Present", 0) + att_counts.get("Late", 0)
    late_today = att_counts.get("Late", 0)
    absent_today = att_counts.get("Absent", 0)
    on_leave_today = att_counts.get("On Leave", 0)
    field_duty_today = att_counts.get("Field Duty", 0)

    pending_leaves = (
        db.query(LeaveRequest)
        .filter(LeaveRequest.status == "pending")
        .count()
    )

    # Department distribution
    dept_rows = (
        db.query(Employee.department, func.count(Employee.id))
        .filter(Employee.employment_status == "Active")
        .group_by(Employee.department)
        .all()
    )
    departments = [{"department": d, "count": c} for d, c in dept_rows]

    # Recent HR activity from audit log
    recent_audits = (
        db.query(AuditLog)
        .filter(AuditLog.event.like("hr.%"))
        .order_by(AuditLog.created_at.desc())
        .limit(10)
        .all()
    )
    activities = [
        {
            "id": a.id,
            "event": a.event,
            "actor_label": a.actor_label,
            "subject_label": a.subject_label,
            "detail": a.detail,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in recent_audits
    ]

    return {
        "date": t_date.isoformat(),
        "total_employees": total_emp,
        "active_employees": active_emp,
        "present_today": present_today,
        "absent_today": absent_today,
        "late_today": late_today,
        "on_leave_today": on_leave_today,
        "field_duty_today": field_duty_today,
        "pending_leave_requests": pending_leaves,
        "departments": departments,
        "recent_activities": activities,
    }

