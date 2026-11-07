from conftest import STRONG


def test_setup_screen_is_needed_until_a_manager_exists(app):
    client = app.test_client()
    assert client.get("/api/setup-status").get_json()["needs_setup"] is True
    client.post("/api/setup", json={"name": "Boss", "emp_code": "boss1", "password": STRONG})
    assert client.get("/api/setup-status").get_json()["needs_setup"] is False


def test_setup_rejects_weak_password(app):
    r = app.test_client().post("/api/setup", json={"name": "Boss", "emp_code": "boss1", "password": "weak"})
    assert r.status_code == 400 and "Password needs" in r.get_json()["error"]


def test_setup_rejects_bad_manager_id(app):
    r = app.test_client().post("/api/setup", json={"name": "Boss", "emp_code": "a b", "password": STRONG})
    assert r.status_code == 400


def test_only_one_manager_can_ever_be_created(app, mgr):
    r = app.test_client().post("/api/setup", json={"name": "Other", "emp_code": "boss2", "password": STRONG})
    assert r.status_code == 403


def test_setup_logs_the_manager_in(mgr):
    r = mgr.get("/api/me")
    assert r.status_code == 200 and r.get_json()["role"] == "manager"


def test_login_with_wrong_password_fails(app, mgr):
    r = app.test_client().post("/api/login", json={"emp_code": "boss1", "password": "Wrong@123", "role": "manager"})
    assert r.status_code == 401


def test_manager_cannot_log_in_through_the_employee_tab(app, mgr):
    r = app.test_client().post("/api/login", json={"emp_code": "boss1", "password": STRONG, "role": "employee"})
    assert r.status_code == 401


def test_me_requires_login(app):
    assert app.test_client().get("/api/me").status_code == 401


def test_logout_ends_the_session(mgr):
    mgr.post("/api/logout")
    assert mgr.get("/api/me").status_code == 401


def test_password_is_stored_hashed(mgr, sql):
    row = sql("SELECT password_hash FROM users WHERE emp_code='boss1'")[0]
    assert row["password_hash"] != STRONG and len(row["password_hash"]) > 30