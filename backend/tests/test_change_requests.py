"""Tests for the 'Request change' feature (employee asks, manager reassigns / stops / declines)."""
from conftest import messages


def raise_request(emp, task_id, category="too_many_tasks", message="I have too many tasks this week"):
    return emp.post("/api/employee/requests", json={"task_id": task_id, "category": category, "message": message})


def test_employee_request_notifies_the_manager(mgr, make_employee, make_task):
    emp = make_employee("EMP001", "Ravi")
    tid = make_task("EMP001", "Big task")
    assert raise_request(emp, tid).status_code == 200
    assert any("Ravi" in m and "asked for a change" in m and "Big task" in m for m in messages(mgr))
    pending = mgr.get("/api/manager/requests").get_json()
    assert pending[0]["status"] == "pending" and pending[0]["emp_code"] == "EMP001"


def test_request_needs_a_real_message_and_reason(make_employee, make_task):
    emp = make_employee()
    tid = make_task("EMP001")
    assert raise_request(emp, tid, message="no").status_code == 400
    assert raise_request(emp, tid, category="whatever").status_code == 400


def test_only_one_pending_request_per_task(make_employee, make_task):
    emp = make_employee()
    tid = make_task("EMP001")
    assert raise_request(emp, tid).status_code == 200
    assert raise_request(emp, tid).status_code == 400


def test_employee_cannot_raise_a_request_for_someone_elses_task(make_employee, make_task):
    make_employee("EMP001")
    other = make_employee("EMP002", "Other")
    tid = make_task("EMP001")
    assert raise_request(other, tid).status_code == 404


def test_manager_reassigns_the_task(mgr, make_employee, make_task):
    ravi, priya = make_employee("EMP001", "Ravi"), make_employee("EMP002", "Priya")
    tid = make_task("EMP001", "Move me")
    raise_request(ravi, tid)
    rid = mgr.get("/api/manager/requests").get_json()[0]["id"]

    r = mgr.post(f"/api/manager/requests/{rid}/resolve",
                 json={"action": "reassign", "new_emp_code": "EMP002", "reply": "Priya has capacity"})
    assert r.status_code == 200
    assert [t["title"] for t in priya.get("/api/employee/tasks").get_json()] == ["Move me"]
    assert ravi.get("/api/employee/tasks").get_json() == []
    assert any("reassigned to Priya" in m and "Priya has capacity" in m for m in messages(ravi))
    assert any("Task reassigned to you: Move me" in m for m in messages(priya))
    assert ravi.get("/api/employee/requests").get_json()[0]["status"] == "reassigned"


def test_reassign_needs_a_different_valid_employee(mgr, make_employee, make_task):
    ravi = make_employee("EMP001", "Ravi")
    tid = make_task("EMP001")
    raise_request(ravi, tid)
    rid = mgr.get("/api/manager/requests").get_json()[0]["id"]
    assert mgr.post(f"/api/manager/requests/{rid}/resolve", json={"action": "reassign"}).status_code == 400
    assert mgr.post(f"/api/manager/requests/{rid}/resolve",
                    json={"action": "reassign", "new_emp_code": "EMP001"}).status_code == 400
    assert mgr.post(f"/api/manager/requests/{rid}/resolve",
                    json={"action": "reassign", "new_emp_code": "GHOST"}).status_code == 400


def test_manager_stops_the_task_but_history_keeps_its_title(mgr, make_employee, make_task):
    ravi = make_employee("EMP001", "Ravi")
    tid = make_task("EMP001", "Cancel me")
    raise_request(ravi, tid)
    rid = mgr.get("/api/manager/requests").get_json()[0]["id"]

    assert mgr.post(f"/api/manager/requests/{rid}/resolve", json={"action": "stop"}).status_code == 200
    assert ravi.get("/api/employee/tasks").get_json() == []
    assert any("has been stopped" in m for m in messages(ravi))
    history = ravi.get("/api/employee/requests").get_json()[0]
    assert history["status"] == "stopped" and history["task_title"] == "Cancel me"


def test_manager_declines_and_the_task_stays(mgr, make_employee, make_task):
    ravi = make_employee("EMP001", "Ravi")
    tid = make_task("EMP001", "Keep me")
    raise_request(ravi, tid)
    rid = mgr.get("/api/manager/requests").get_json()[0]["id"]

    mgr.post(f"/api/manager/requests/{rid}/resolve", json={"action": "decline", "reply": "Deadline is fixed"})
    assert [t["title"] for t in ravi.get("/api/employee/tasks").get_json()] == ["Keep me"]
    assert any("declined" in m and "Deadline is fixed" in m for m in messages(ravi))


def test_a_request_cannot_be_handled_twice(mgr, make_employee, make_task):
    ravi = make_employee()
    tid = make_task("EMP001")
    raise_request(ravi, tid)
    rid = mgr.get("/api/manager/requests").get_json()[0]["id"]
    assert mgr.post(f"/api/manager/requests/{rid}/resolve", json={"action": "decline"}).status_code == 200
    assert mgr.post(f"/api/manager/requests/{rid}/resolve", json={"action": "stop"}).status_code == 400


def test_employee_cannot_resolve_requests(make_employee, make_task):
    emp = make_employee()
    tid = make_task("EMP001")
    raise_request(emp, tid)
    assert emp.post("/api/manager/requests/1/resolve", json={"action": "stop"}).status_code == 403