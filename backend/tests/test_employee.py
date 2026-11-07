from conftest import messages


def test_employee_sees_only_their_own_tasks(make_employee, make_task):
    ravi, priya = make_employee("EMP001", "Ravi"), make_employee("EMP002", "Priya")
    make_task("EMP001", "Ravi task")
    make_task("EMP002", "Priya task")
    assert [t["title"] for t in ravi.get("/api/employee/tasks").get_json()] == ["Ravi task"]
    assert [t["title"] for t in priya.get("/api/employee/tasks").get_json()] == ["Priya task"]


def test_completing_a_task_notifies_the_manager(mgr, make_employee, make_task):
    emp = make_employee("EMP001", "Ravi")
    tid = make_task("EMP001", "Ship it")
    r = emp.post(f"/api/employee/tasks/{tid}/update", json={"progress": 100, "status": "done"})
    assert r.status_code == 200
    assert any("Task completed by Ravi (EMP001): Ship it" in m for m in messages(mgr))


def test_progress_100_forces_status_done(make_employee, make_task):
    emp = make_employee()
    tid = make_task("EMP001")
    emp.post(f"/api/employee/tasks/{tid}/update", json={"progress": 100, "status": "in_progress"})
    task = emp.get("/api/employee/tasks").get_json()[0]
    assert task["status"] == "done" and task["progress"] == 100


def test_any_progress_moves_todo_to_in_progress(make_employee, make_task):
    emp = make_employee()
    tid = make_task("EMP001")
    emp.post(f"/api/employee/tasks/{tid}/update", json={"progress": 30, "status": "todo"})
    assert emp.get("/api/employee/tasks").get_json()[0]["status"] == "in_progress"


def test_marking_blocked_notifies_the_manager(mgr, make_employee, make_task):
    emp = make_employee("EMP001", "Ravi")
    tid = make_task("EMP001", "Stuck task")
    emp.post(f"/api/employee/tasks/{tid}/update", json={"progress": 10, "status": "blocked"})
    assert any("marked blocked: Stuck task" in m for m in messages(mgr))


def test_employee_cannot_update_someone_elses_task(make_employee, make_task):
    make_employee("EMP001")
    intruder = make_employee("EMP002", "Other")
    tid = make_task("EMP001")
    r = intruder.post(f"/api/employee/tasks/{tid}/update", json={"progress": 100, "status": "done"})
    assert r.status_code == 404


def test_invalid_status_is_rejected(make_employee, make_task):
    emp = make_employee()
    tid = make_task("EMP001")
    assert emp.post(f"/api/employee/tasks/{tid}/update", json={"status": "flying"}).status_code == 400


def test_finishing_a_dependency_notifies_the_waiting_employee(make_employee, make_task):
    ravi, priya = make_employee("EMP001", "Ravi"), make_employee("EMP002", "Priya")
    first = make_task("EMP001", "Foundation")
    make_task("EMP002", "Roof", depends_on=[first])
    ravi.post(f"/api/employee/tasks/{first}/update", json={"progress": 100, "status": "done"})
    assert any("dependency finished" in m and "Roof" in m for m in messages(priya))


def test_daily_report_is_saved_and_overwritten_not_duplicated(make_employee, sql):
    emp = make_employee()
    emp.post("/api/employee/daily-report", json={"content": "First version"})
    emp.post("/api/employee/daily-report", json={"content": "Second version"})
    assert emp.get("/api/employee/daily-report").get_json()["content"] == "Second version"
    assert sql("SELECT count(*) AS c FROM daily_reports")[0]["c"] == 1


def test_empty_daily_report_is_rejected(make_employee):
    assert make_employee().post("/api/employee/daily-report", json={"content": "  "}).status_code == 400