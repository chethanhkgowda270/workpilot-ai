"""Overdue detection, priorities, bottlenecks, reports and summaries, tested through the API."""
from conftest import messages


def test_tasks_are_sorted_by_recommended_priority(make_employee, make_task):
    emp = make_employee()
    make_task("EMP001", "Later", hours=24 * 10)
    make_task("EMP001", "Soon", hours=6)
    titles = [t["title"] for t in emp.get("/api/employee/tasks").get_json()]
    assert titles == ["Soon", "Later"]


def test_a_task_that_blocks_others_ranks_higher(make_employee, make_task):
    emp = make_employee()
    blocker = make_task("EMP001", "Blocker", hours=72)
    make_task("EMP001", "Waiting", hours=72, depends_on=[blocker])
    make_task("EMP001", "Plain", hours=72)
    tasks = {t["title"]: t["ai_priority"]["score"] for t in emp.get("/api/employee/tasks").get_json()}
    assert tasks["Blocker"] > tasks["Plain"] > tasks["Waiting"]


def test_overdue_task_is_detected_and_announced_exactly_once(mgr, make_employee, make_task, sql):
    emp = make_employee()
    tid = make_task("EMP001", "Late job")
    sql("UPDATE tasks SET deadline = LOCALTIMESTAMP - interval '1 day' WHERE id=%s", (tid,))

    dash = mgr.get("/api/manager/dashboard").get_json()
    assert dash["counts"]["overdue"] == 1 and dash["overdue"][0]["title"] == "Late job"

    mgr.get("/api/manager/dashboard")            # loading the page again must NOT notify again
    emp.get("/api/employee/tasks")
    assert sum("Task overdue: Late job" in m for m in messages(emp)) == 1
    assert sum("Overdue task: Late job" in m for m in messages(mgr)) == 1


def test_moving_an_overdue_deadline_into_the_future_clears_the_overdue_flag(mgr, make_employee, make_task, sql):
    make_employee()
    tid = make_task("EMP001", "Recovered")
    sql("UPDATE tasks SET deadline = LOCALTIMESTAMP - interval '1 day' WHERE id=%s", (tid,))
    mgr.get("/api/manager/dashboard")
    import datetime as dt
    later = (dt.datetime.now() + dt.timedelta(days=2)).isoformat(timespec="minutes")
    mgr.patch(f"/api/manager/tasks/{tid}", json={"deadline": later})
    assert mgr.get("/api/manager/dashboard").get_json()["counts"]["overdue"] == 0


def test_blocked_task_appears_as_a_bottleneck(mgr, make_employee, make_task):
    emp = make_employee("EMP001", "Ravi")
    tid = make_task("EMP001", "Stuck")
    emp.post(f"/api/employee/tasks/{tid}/update", json={"progress": 10, "status": "blocked"})
    items = mgr.get("/api/manager/dashboard").get_json()["bottlenecks"]
    assert any(b["type"] == "Blocked task" and "Stuck" in b["message"] for b in items)


def test_late_blocking_task_is_flagged_high_severity(mgr, make_employee, make_task, sql):
    make_employee()
    blocker = make_task("EMP001", "Foundation")
    make_task("EMP001", "Roof", depends_on=[blocker])
    sql("UPDATE tasks SET deadline = LOCALTIMESTAMP - interval '1 day' WHERE id=%s", (blocker,))
    items = mgr.get("/api/manager/dashboard").get_json()["bottlenecks"]
    assert items[0]["severity"] == "high" and items[0]["type"] == "Blocking task at risk"


def test_overloaded_employee_is_flagged(mgr, make_employee, make_task):
    make_employee("EMP001", "Ravi")
    for i in range(5):
        make_task("EMP001", f"Task {i}", hours=24 * 10)
    items = mgr.get("/api/manager/dashboard").get_json()["bottlenecks"]
    assert any(b["type"] == "Overloaded employee" and "Ravi" in b["message"] for b in items)


def test_weekly_report_scores_an_on_time_completion(mgr, make_employee, make_task):
    emp = make_employee("EMP001", "Ravi")
    tid = make_task("EMP001", "Done on time")
    emp.post(f"/api/employee/tasks/{tid}/update", json={"progress": 100, "status": "done"})
    row = mgr.get("/api/manager/weekly-report").get_json()["rows"][0]
    assert row["completed"] == 1 and row["on_time"] == 1 and row["late"] == 0
    assert row["score"] == 60 and row["rating"] == "Good"


def test_daily_summary_lists_blockers(mgr, make_employee):
    emp = make_employee("EMP001", "Ravi")
    emp.post("/api/employee/daily-report", json={"content": "Built the form. Waiting for the design from the client."})
    data = mgr.get("/api/manager/daily-summary").get_json()
    assert len(data["reports"]) == 1
    assert any("Waiting" in b for b in data["blockers"])