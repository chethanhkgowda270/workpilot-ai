import datetime as dt
from conftest import STRONG, messages


def test_add_employee_requires_strong_password(mgr):
    r = mgr.post("/api/manager/employees", json={"emp_code": "EMP001", "name": "Ravi", "password": "weakpass"})
    assert r.status_code == 400


def test_duplicate_employee_id_is_rejected(mgr, make_employee):
    make_employee("EMP001")
    r = mgr.post("/api/manager/employees", json={"emp_code": "EMP001", "name": "Again", "password": STRONG})
    assert r.status_code == 409


def test_employee_cannot_use_manager_routes(make_employee):
    emp = make_employee()
    assert emp.get("/api/manager/dashboard").status_code == 403
    assert emp.post("/api/manager/tasks", json={}).status_code == 403


def test_lookup_returns_profile_and_experience(mgr, make_employee):
    make_employee("EMP001", "Ravi", prior_experience_years=2)
    data = mgr.get("/api/manager/employees/EMP001").get_json()
    assert data["profile"]["name"] == "Ravi"
    assert data["profile"]["post"] == "Developer"
    assert data["profile"]["total_experience_years"] >= 2
    assert data["stats"]["open"] == 0


def test_lookup_unknown_employee_is_404(mgr):
    assert mgr.get("/api/manager/employees/NOPE").status_code == 404


def test_assigning_a_task_notifies_the_employee(mgr, make_employee, make_task):
    emp = make_employee("EMP001")
    make_task("EMP001", "Write the API")
    assert any("New task assigned: Write the API" in m for m in messages(emp))


def test_deadline_in_the_past_is_rejected(mgr, make_employee):
    make_employee("EMP001")
    past = (dt.datetime.now() - dt.timedelta(hours=1)).isoformat(timespec="minutes")
    r = mgr.post("/api/manager/tasks", json={"emp_code": "EMP001", "title": "X", "deadline": past})
    assert r.status_code == 400


def test_assigning_to_unknown_employee_is_404(mgr):
    future = (dt.datetime.now() + dt.timedelta(days=1)).isoformat(timespec="minutes")
    r = mgr.post("/api/manager/tasks", json={"emp_code": "GHOST", "title": "X", "deadline": future})
    assert r.status_code == 404


def test_bringing_a_deadline_earlier_notifies_the_employee(mgr, make_employee, make_task):
    emp = make_employee("EMP001")
    tid = make_task("EMP001", "Report", hours=72)
    earlier = (dt.datetime.now() + dt.timedelta(hours=10)).isoformat(timespec="minutes")
    assert mgr.patch(f"/api/manager/tasks/{tid}", json={"deadline": earlier}).status_code == 200
    assert any("moved earlier" in m for m in messages(emp))


def test_dashboard_counts(mgr, make_employee, make_task):
    make_employee("EMP001")
    make_task("EMP001", "A")
    make_task("EMP001", "B")
    counts = mgr.get("/api/manager/dashboard").get_json()["counts"]
    assert counts["employees"] == 1 and counts["open"] == 2 and counts["done"] == 0


def test_working_today_lists_busy_and_free_employees(mgr, make_employee, make_task):
    make_employee("EMP001", "Busy")
    make_employee("EMP002", "Free")
    make_task("EMP001", "Job")
    today = mgr.get("/api/manager/dashboard").get_json()["today"]
    assert [e["name"] for e in today["working"]] == ["Busy"]
    assert [e["name"] for e in today["free"]] == ["Free"]