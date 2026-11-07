"""Unit tests: pure functions, no database needed."""
import datetime as dt
import pytest
import app as app_module
from app import validate_password, score_task, summarize_reports, profile


# ---------------------------------------------------------------- strong passwords
@pytest.mark.parametrize("pw", ["Abcdef1!", "Str0ng@Pass", "Zz9#zzzz"])
def test_strong_passwords_are_accepted(pw):
    assert validate_password(pw) == ""


@pytest.mark.parametrize("pw, missing", [
    ("Ab1!", "at least 8 characters"),
    ("abcdefg1!", "an uppercase letter"),
    ("ABCDEFG1!", "a lowercase letter"),
    ("Abcdefgh!", "a number"),
    ("Abcdefg1", "a special character"),
])
def test_weak_passwords_are_rejected_with_a_reason(pw, missing):
    assert missing in validate_password(pw)


def test_spaces_are_not_allowed():
    assert "spaces" in validate_password("Abcd ef1!")


# ---------------------------------------------------------------- priority score
def task(hours_left=48, progress=0, status="todo", dependents=0, open_deps=0):
    return {"status": status, "progress": progress, "dependents": dependents, "open_deps": open_deps,
            "deadline": dt.datetime.now() + dt.timedelta(hours=hours_left)}


def test_overdue_task_is_critical():
    r = score_task(task(hours_left=-5))
    assert r["label"] == "Critical" and "overdue" in r["reason"]


def test_far_deadline_is_low_priority():
    assert score_task(task(hours_left=24 * 14, progress=90))["label"] == "Low"


def test_closer_deadline_scores_higher():
    assert score_task(task(hours_left=12))["score"] > score_task(task(hours_left=96))["score"]


def test_blocking_other_tasks_raises_priority():
    assert score_task(task(dependents=2))["score"] > score_task(task())["score"]


def test_waiting_on_unfinished_work_lowers_priority():
    assert score_task(task(open_deps=1))["score"] < score_task(task())["score"]


def test_done_task_has_no_priority():
    assert score_task(task(status="done"))["label"] == "Done"


# ---------------------------------------------------------------- daily report summary
def test_summary_finds_blockers_and_names_the_employee():
    rows = [{"name": "Ravi", "content": "Finished the login page. I am blocked on the database access."}]
    out = summarize_reports(rows)
    assert any("Ravi" in b and "blocked" in b.lower() for b in out["blockers"])
    assert out["source"] == "built-in"          # no API key in tests


def test_summary_with_no_reports():
    out = summarize_reports([])
    assert out["blockers"] == [] and "No daily reports" in out["summary"]


# ---------------------------------------------------------------- experience in company
def test_profile_calculates_time_in_company():
    joined = dt.date.today().replace(year=dt.date.today().year - 2)
    p = profile({"id": 1, "emp_code": "E1", "name": "A", "role": "employee", "post": "Dev", "department": "X",
                 "email": None, "joined_on": joined, "prior_experience_years": 1.5})
    assert p["time_in_company"].startswith("2 yr")
    assert p["total_experience_years"] == 3.5