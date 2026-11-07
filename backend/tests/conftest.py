"""Shared test setup.

The tests run against a SEPARATE PostgreSQL database (for example 'workpilot_test'),
never your real one. Set it before running:

    $env:TEST_DATABASE_URL="host=localhost port=5432 dbname=workpilot_test user=postgres password=YOUR_PASSWORD"
"""
import os
import datetime as dt

import psycopg2
import psycopg2.extras
import psycopg2.extensions
import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL")
if not TEST_DB:
    pytest.exit("Set TEST_DATABASE_URL to a TEST database first (see the top of tests/conftest.py).", returncode=2)

# Safety net: refuse to run against anything that is not clearly a test database,
# because every test wipes all tables.
if "test" not in psycopg2.extensions.parse_dsn(TEST_DB).get("dbname", "").lower():
    pytest.exit("Refusing to run: the database name must contain 'test'.", returncode=2)

# app.py reads DATABASE_URL when it is imported, so point it at the test database BEFORE importing.
os.environ["DATABASE_URL"] = TEST_DB
os.environ.pop("ANTHROPIC_API_KEY", None)      # tests must never call a paid API
import app as app_module                       # noqa: E402

STRONG = "Str0ng@Pass"


def _sql(query, params=()):
    con = psycopg2.connect(TEST_DB, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        with con.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall() if cur.description else None
        con.commit()
        return rows
    finally:
        con.close()


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    app_module.init_db()          # runs schema.sql on the test database


@pytest.fixture(autouse=True)
def clean_database(create_tables):
    # CASCADE also empties every table that points at users or projects
    _sql("TRUNCATE users, projects RESTART IDENTITY CASCADE")


@pytest.fixture
def app():
    app_module.app.config["TESTING"] = True
    return app_module.app


@pytest.fixture
def sql():
    """Run raw SQL in a test, e.g. to move a deadline into the past."""
    return _sql


@pytest.fixture
def mgr(app):
    """A test client that is already logged in as the manager."""
    client = app.test_client()
    r = client.post("/api/setup", json={"name": "Boss", "emp_code": "boss1", "password": STRONG})
    assert r.status_code == 200, r.get_json()
    return client


@pytest.fixture
def make_employee(app, mgr):
    """make_employee('EMP001', 'Ravi') -> a client logged in as that employee."""
    def _make(code="EMP001", name="Ravi", password=STRONG, **extra):
        body = {"emp_code": code, "name": name, "password": password,
                "post": "Developer", "department": "Engineering", **extra}
        r = mgr.post("/api/manager/employees", json=body)
        assert r.status_code == 200, r.get_json()
        client = app.test_client()                 # its own cookies = its own login
        r = client.post("/api/login", json={"emp_code": code, "password": password, "role": "employee"})
        assert r.status_code == 200, r.get_json()
        return client
    return _make


@pytest.fixture
def make_task(mgr):
    """make_task('EMP001', 'Write API', hours=48) -> task id."""
    def _make(code, title="Task", hours=48, depends_on=None):
        deadline = (dt.datetime.now() + dt.timedelta(hours=hours)).isoformat(timespec="minutes")
        r = mgr.post("/api/manager/tasks", json={"emp_code": code, "title": title,
                                                  "deadline": deadline, "depends_on": depends_on or []})
        assert r.status_code == 200, r.get_json()
        return r.get_json()["id"]
    return _make


def messages(client):
    """All notification texts for the logged-in user (newest first)."""
    return [n["message"] for n in client.get("/api/notifications").get_json()]