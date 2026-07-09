"""Sample employees and their digital-twin agents (fictional demo roles only)."""

from typing import Optional

from agent_network.models import Employee, Skill

# Demo role IDs — use these in demos/tests instead of real employee names.
DEMO_MANAGER_ID = "emp-manager"
DEMO_ASSIGNEE_ID = "emp-assignee"
DEMO_OBSERVER_ID = "emp-observer"
DEMO_INTERN_ID = "emp-intern"

# Replace with real roster from HR/Workday when mentor provides access.
SAMPLE_EMPLOYEES: list[Employee] = [
    Employee(
        employee_id=DEMO_MANAGER_ID,
        name="Demo Manager",
        email="agent-network-manager@demo.local",
        team="Engineering",
        skills=[Skill.JIRA, Skill.GITLAB, Skill.TEAMS],
        is_absent=True,
    ),
    Employee(
        employee_id=DEMO_ASSIGNEE_ID,
        name="Demo Assignee",
        email="agent-network-assignee@demo.local",
        team="Engineering",
        skills=[Skill.JIRA, Skill.GITLAB],
    ),
    Employee(
        employee_id=DEMO_INTERN_ID,
        name="Demo Intern",
        email="agent-network-intern@demo.local",
        team="Engineering",
        skills=[Skill.JIRA],
    ),
    Employee(
        employee_id=DEMO_OBSERVER_ID,
        name="Demo Observer",
        email="agent-network-observer@demo.local",
        team="Engineering",
        skills=[Skill.JIRA, Skill.TEAMS, Skill.WORKDAY],
    ),
]


def employee_by_id(employee_id: str) -> Optional[Employee]:
    for emp in SAMPLE_EMPLOYEES:
        if emp.employee_id == employee_id:
            return emp
    return None


def employee_by_email(email: str) -> Optional[Employee]:
    if not email:
        return None
    email = email.strip().lower()
    for emp in SAMPLE_EMPLOYEES:
        if emp.email.lower() == email:
            return emp
    return None


def employee_by_name(name: str) -> Optional[Employee]:
    if not name:
        return None
    name = name.strip().lower()
    for emp in SAMPLE_EMPLOYEES:
        if emp.name.lower() == name or name in emp.name.lower():
            return emp
    return None


def employee_display_name(employee_id: str) -> str:
    """Human-friendly label for logs (no real employee names)."""
    emp = employee_by_id(employee_id)
    return emp.name if emp else employee_id


def employee_has_skill(employee_id: str, skill: Skill) -> bool:
    emp = employee_by_id(employee_id)
    return bool(emp and skill in emp.skills)


def set_employee_absent(employee_id: str, absent: bool) -> bool:
    """Update absence flag on demo roster (in-process)."""
    emp = employee_by_id(employee_id)
    if not emp:
        return False
    emp.is_absent = absent
    return True


def reset_demo_roster_state() -> None:
    """Restore demo absence flags to default demo-start values."""
    set_employee_absent(DEMO_MANAGER_ID, True)
    for emp_id in (DEMO_ASSIGNEE_ID, DEMO_INTERN_ID, DEMO_OBSERVER_ID):
        set_employee_absent(emp_id, False)
