"""WorkPilot AI - Flask backend (PostgreSQL via psycopg2).

Run:  python app.py initdb   (creates tables + the single manager account)
      python app.py          (starts the server on http://localhost:5000)
"""
import os, re, sys, decimal, datetime as dt
from functools import wraps

import psycopg2, psycopg2.extras, psycopg2.errors
from flask import Flask, jsonify, request, session, g
from flask.json.provider import DefaultJSONProvider
from werkzeug.security import generate_password_hash, check_password_hash

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:Chandu%40270@localhost:5432/workpilot")


def _default(o):
    if isinstance(o, (dt.datetime, dt.date)):
        return o.isoformat()
    if isinstance(o, decimal.Decimal):
        return float(o)
    return DefaultJSONProvider.default(o)


class Provider(DefaultJSONProvider):
    default = staticmethod(_default)


app = Flask(__name__, static_folder="../frontend", static_url_path="")
app.json = Provider(app)
app.secret_key = os.getenv("SECRET_KEY", "dev-only-change-me")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")


# ---------------------------------------------------------------- db helpers
def db():
    if "db" not in g:
        g.db = psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return g.db


@app.teardown_appcontext
def close_db(_):
    con = g.pop("db", None)
    if con:
        con.close()


def q(sql, params=(), one=False, commit=False):
    try:
        with db().cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() if cur.description else None
        if commit:
            db().commit()
    except Exception:
        db().rollback()
        raise
    if one:
        return rows[0] if rows else None
    return rows


def err(msg, code=400):
    return jsonify(error=msg), code


def auth(role=None):
    def deco(f):
        @wraps(f)
        def wrapper(*a, **k):
            if "uid" not in session:
                return err("Please log in", 401)
            if role and session.get("role") != role:
                return err("Not allowed", 403)
            return f(*a, **k)
        return wrapper
    return deco


def notify(user_id, message, task_id=None):
    q("INSERT INTO notifications(user_id,task_id,message) VALUES(%s,%s,%s)",
      (user_id, task_id, message), commit=True)


def manager_id():
    return q("SELECT id FROM users WHERE role='manager'", one=True)["id"]


def parse_dt(s):
    try:
        return dt.datetime.fromisoformat(s)
    except Exception:
        raise ValueError("Invalid date/time")


def validate_password(pw):
    """Return an error message, or "" when the password is strong."""
    need = []
    if len(pw) < 8:
        need.append("at least 8 characters")
    if not re.search(r"[A-Z]", pw):
        need.append("an uppercase letter")
    if not re.search(r"[a-z]", pw):
        need.append("a lowercase letter")
    if not re.search(r"\d", pw):
        need.append("a number")
    if not re.search(r"[^A-Za-z0-9\s]", pw):
        need.append("a special character (e.g. @ # $ !)")
    msg = ("Password needs " + ", ".join(need)) if need else ""
    if re.search(r"\s", pw):
        msg = (msg + ". " if msg else "") + "Password must not contain spaces"
    return msg


# ---------------------------------------------------------------- AI-ish logic
def score_task(t):
    """Priority recommendation from deadline, dependencies, remaining work."""
    if t["status"] == "done":
        return {"score": 0, "label": "Done", "reason": "Completed"}
    days = (t["deadline"] - dt.datetime.now()).total_seconds() / 86400
    why = []
    if days < 0:
        s = 100
        why.append(f"overdue by {abs(days):.1f} day(s)")
    else:
        s = max(0, 50 - days * 5)
        why.append(f"due in {days:.1f} day(s)")
    if t["dependents"]:
        s += min(36, 12 * t["dependents"])
        why.append(f"{t['dependents']} other task(s) wait on this")
    s += (100 - t["progress"]) / 100 * 10
    if t["open_deps"]:
        s -= 20
        why.append(f"waiting on {t['open_deps']} unfinished dependency(ies)")
    s = round(max(0, min(150, s)), 1)
    label = "Critical" if s >= 70 else "High" if s >= 45 else "Medium" if s >= 25 else "Low"
    return {"score": s, "label": label, "reason": "; ".join(why)}


TASK_SQL = """
SELECT t.*, u.name AS employee_name, u.emp_code, p.name AS project_name,
  (SELECT count(*) FROM task_dependencies d JOIN tasks x ON x.id=d.task_id
     WHERE d.depends_on_id=t.id AND x.status<>'done') AS dependents,
  (SELECT count(*) FROM task_dependencies d JOIN tasks x ON x.id=d.depends_on_id
     WHERE d.task_id=t.id AND x.status<>'done') AS open_deps,
  (SELECT max(created_at) FROM task_updates WHERE task_id=t.id) AS last_update,
  (t.status<>'done' AND t.deadline < LOCALTIMESTAMP) AS overdue
FROM tasks t JOIN users u ON u.id=t.assigned_to LEFT JOIN projects p ON p.id=t.project_id
"""


def fetch_tasks(where="TRUE", params=()):
    rows = q(f"{TASK_SQL} WHERE {where}", params)
    for t in rows:
        t["ai_priority"] = score_task(t)
    rows.sort(key=lambda t: (t["status"] == "done", -t["ai_priority"]["score"]))
    return rows


def flag_overdue():
    """Automatically detect newly overdue tasks and notify employee + manager once."""
    rows = q("""UPDATE tasks SET overdue_notified=TRUE
                WHERE status<>'done' AND deadline < LOCALTIMESTAMP AND NOT overdue_notified
                RETURNING id,title,assigned_to""", commit=True)
    if rows:
        mid = manager_id()
        for r in rows:
            notify(r["assigned_to"], f"Task overdue: {r['title']}", r["id"])
            notify(mid, f"Overdue task: {r['title']}", r["id"])


def find_bottlenecks():
    out, now = [], dt.datetime.now()
    tasks = [t for t in fetch_tasks() if t["status"] != "done"]
    for t in tasks:
        stale = (now - (t["last_update"] or t["assigned_on"])).days
        if t["dependents"] and (t["overdue"] or t["progress"] < 50 and (t["deadline"] - now).days <= 2):
            out.append({"severity": "high", "type": "Blocking task at risk",
                        "message": f"'{t['title']}' ({t['employee_name']}) is holding up {t['dependents']} task(s) and is "
                                   f"{'overdue' if t['overdue'] else 'behind'} ({t['progress']}% done)."})
        if t["status"] == "blocked":
            out.append({"severity": "high", "type": "Blocked task",
                        "message": f"'{t['title']}' ({t['employee_name']}) is marked blocked."})
        elif t["open_deps"] and (t["deadline"] - now).days <= 3:
            out.append({"severity": "medium", "type": "Waiting on dependency",
                        "message": f"'{t['title']}' ({t['employee_name']}) is due soon but still waits on {t['open_deps']} task(s)."})
        if t["status"] == "in_progress" and stale >= 3:
            out.append({"severity": "medium", "type": "Stalled work",
                        "message": f"'{t['title']}' ({t['employee_name']}) had no update for {stale} days."})
    load = {}
    for t in tasks:
        e = load.setdefault(t["employee_name"], {"open": 0, "soon": 0})
        e["open"] += 1
        if (t["deadline"] - now).days <= 3:
            e["soon"] += 1
    for name, e in load.items():
        if e["open"] >= 5 or e["soon"] >= 3:
            out.append({"severity": "medium", "type": "Overloaded employee",
                        "message": f"{name} has {e['open']} open tasks, {e['soon']} due within 3 days."})
    out.sort(key=lambda b: b["severity"] != "high")
    return out


def working_today():
    rows = q("""
      SELECT u.id, u.emp_code, u.name, u.post,
        COALESCE(json_agg(json_build_object('id',t.id,'title',t.title,'deadline',t.deadline,
                 'progress',t.progress,'status',t.status,'overdue',t.deadline < LOCALTIMESTAMP)
                 ORDER BY t.deadline) FILTER (WHERE t.id IS NOT NULL), '[]') AS tasks
      FROM users u LEFT JOIN tasks t ON t.assigned_to=u.id AND t.status<>'done'
           AND t.assigned_on::date <= CURRENT_DATE
      WHERE u.role='employee' AND u.active GROUP BY u.id ORDER BY u.name""")
    return {"working": [r for r in rows if r["tasks"]], "free": [r for r in rows if not r["tasks"]]}


def llm_summary(text):
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        r = client.messages.create(
            model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"), max_tokens=600,
            messages=[{"role": "user", "content":
                       "Summarize these employee daily work reports for a manager in under 150 words. "
                       "Cover progress, blockers and risks. Use short bullet points.\n\n" + text}])
        return r.content[0].text
    except Exception:
        return None


BLOCK_WORDS = re.compile(r"\b(blocked|waiting|stuck|issue|delay|delayed|bug|failed|risk|pending)\b", re.I)


def summarize_reports(rows):
    if not rows:
        return {"summary": "No daily reports submitted for this date.", "blockers": [], "source": "none"}
    text = "\n\n".join(f"{r['name']}: {r['content']}" for r in rows)
    ai = llm_summary(text)
    blockers = []
    lines = []
    for r in rows:
        sents = re.split(r"(?<=[.!?])\s+|\n+", r["content"].strip())
        sents = [s for s in sents if s]
        lines.append(f"- {r['name']}: " + " ".join(sents[:2]))
        blockers += [f"{r['name']}: {s}" for s in sents if BLOCK_WORDS.search(s)]
    summary = ai or (f"{len(rows)} report(s) received.\n" + "\n".join(lines))
    return {"summary": summary, "blockers": blockers, "source": "claude" if ai else "built-in"}


def profile(u):
    j, today = u["joined_on"], dt.date.today()
    months = (today.year - j.year) * 12 + today.month - j.month - (1 if today.day < j.day else 0)
    months = max(months, 0)
    prior = float(u["prior_experience_years"] or 0)
    return {"id": u["id"], "emp_code": u["emp_code"], "name": u["name"], "role": u["role"], "post": u["post"],
            "department": u["department"], "email": u["email"], "joined_on": u["joined_on"],
            "time_in_company": f"{months // 12} yr {months % 12} mo",
            "total_experience_years": round(prior + months / 12, 1)}


# ---------------------------------------------------------------- auth
@app.get("/api/setup-status")
def setup_status():
    """The frontend asks this to decide: show first-time setup or the normal login?"""
    return jsonify(needs_setup=q("SELECT 1 FROM users WHERE role='manager'", one=True) is None)


@app.post("/api/setup")
def first_time_setup():
    """Lets the very first visitor create the (only) manager account."""
    if q("SELECT 1 FROM users WHERE role='manager'", one=True):
        return err("A manager account already exists", 403)
    d = request.get_json(silent=True) or {}
    code, name, pw = (d.get("emp_code") or "").strip(), (d.get("name") or "").strip(), d.get("password") or ""
    if not name:
        return err("Your name is required")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,30}", code):
        return err("Manager ID must be 3-30 characters: letters, numbers, . _ -")
    problem = validate_password(pw)
    if problem:
        return err(problem)
    try:
        u = q("""INSERT INTO users(emp_code,name,role,password_hash,post,department)
                 VALUES(%s,%s,'manager',%s,'Manager','Management') RETURNING *""",
              (code, name, generate_password_hash(pw)), one=True, commit=True)
    except psycopg2.errors.UniqueViolation:
        return err("A manager account already exists", 403)
    session.clear()
    session.update(uid=u["id"], role="manager", name=u["name"], code=u["emp_code"])
    return jsonify(profile(u))


@app.post("/api/login")
def login():
    d = request.get_json(silent=True) or {}
    u = q("SELECT * FROM users WHERE emp_code=%s AND active", ((d.get("emp_code") or "").strip(),), one=True)
    if not u or u["role"] != d.get("role") or not check_password_hash(u["password_hash"], d.get("password") or ""):
        return err("Invalid ID or password", 401)
    session.clear()
    session.update(uid=u["id"], role=u["role"], name=u["name"], code=u["emp_code"])
    return jsonify(profile(u))


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
@auth()
def me():
    return jsonify(profile(q("SELECT * FROM users WHERE id=%s", (session["uid"],), one=True)))


# ---------------------------------------------------------------- notifications
@app.get("/api/notifications")
@auth()
def notifications():
    unread = request.args.get("unread") == "1"
    rows = q(f"SELECT * FROM notifications WHERE user_id=%s {'AND NOT is_read' if unread else ''} "
             "ORDER BY created_at DESC LIMIT 50", (session["uid"],))
    return jsonify(rows)


@app.post("/api/notifications/read")
@auth()
def mark_read():
    ids = (request.get_json(silent=True) or {}).get("ids") or []
    q("UPDATE notifications SET is_read=TRUE WHERE user_id=%s AND id = ANY(%s)",
      (session["uid"], [int(i) for i in ids]), commit=True)
    return jsonify(ok=True)


# ---------------------------------------------------------------- manager
@app.post("/api/manager/employees")
@auth("manager")
def add_employee():
    d = request.get_json(silent=True) or {}
    code, name, pw = (d.get("emp_code") or "").strip(), (d.get("name") or "").strip(), d.get("password") or ""
    if not (code and name):
        return err("Employee ID and name are required")
    problem = validate_password(pw)
    if problem:
        return err(problem)
    try:
        q("""INSERT INTO users(emp_code,name,role,password_hash,post,department,email,joined_on,prior_experience_years)
             VALUES(%s,%s,'employee',%s,%s,%s,%s,%s,%s)""",
          (code, name, generate_password_hash(pw), d.get("post"), d.get("department"), d.get("email"),
           d.get("joined_on") or dt.date.today(), d.get("prior_experience_years") or 0), commit=True)
    except psycopg2.errors.UniqueViolation:
        return err("That employee ID already exists", 409)
    return jsonify(ok=True)


@app.get("/api/manager/employees/<code>")
@auth("manager")
def employee_detail(code):
    u = q("SELECT * FROM users WHERE emp_code=%s AND role='employee'", (code.strip(),), one=True)
    if not u:
        return err("No employee found with that ID", 404)
    tasks = fetch_tasks("t.assigned_to=%s", (u["id"],))
    open_t = [t for t in tasks if t["status"] != "done"]
    stats = {"total": len(tasks), "open": len(open_t), "done": len(tasks) - len(open_t),
             "overdue": sum(1 for t in open_t if t["overdue"]),
             "avg_progress": round(sum(t["progress"] for t in open_t) / len(open_t)) if open_t else 0}
    return jsonify(profile=profile(u), tasks=tasks, stats=stats)


@app.get("/api/manager/projects")
@auth("manager")
def projects():
    return jsonify(q("SELECT * FROM projects ORDER BY name"))


@app.post("/api/manager/projects")
@auth("manager")
def add_project():
    d = request.get_json(silent=True) or {}
    if not (d.get("name") or "").strip():
        return err("Project name required")
    try:
        q("INSERT INTO projects(name,description) VALUES(%s,%s)", (d["name"].strip(), d.get("description")), commit=True)
    except psycopg2.errors.UniqueViolation:
        return err("Project already exists", 409)
    return jsonify(ok=True)


@app.get("/api/manager/open-tasks")
@auth("manager")
def open_tasks():
    return jsonify(q("""SELECT t.id,t.title,u.name AS employee_name FROM tasks t JOIN users u ON u.id=t.assigned_to
                        WHERE t.status<>'done' ORDER BY t.id DESC"""))


@app.post("/api/manager/tasks")
@auth("manager")
def create_task():
    d = request.get_json(silent=True) or {}
    u = q("SELECT * FROM users WHERE emp_code=%s AND role='employee'", ((d.get("emp_code") or "").strip(),), one=True)
    if not u:
        return err("Employee not found", 404)
    title = (d.get("title") or "").strip()
    if not title:
        return err("Task title required")
    try:
        deadline = parse_dt(d.get("deadline") or "")
    except ValueError as e:
        return err(str(e))
    if deadline <= dt.datetime.now():
        return err("Deadline must be in the future")
    row = q("""INSERT INTO tasks(title,description,project_id,assigned_to,assigned_by,deadline)
               VALUES(%s,%s,%s,%s,%s,%s) RETURNING id""",
            (title, d.get("description"), d.get("project_id") or None, u["id"], session["uid"], deadline),
            one=True, commit=True)
    for dep in d.get("depends_on") or []:
        q("INSERT INTO task_dependencies VALUES(%s,%s) ON CONFLICT DO NOTHING", (row["id"], int(dep)), commit=True)
    notify(u["id"], f"New task assigned: {title} - deadline {deadline:%d %b %Y, %H:%M}", row["id"])
    return jsonify(id=row["id"])


@app.patch("/api/manager/tasks/<int:tid>")
@auth("manager")
def edit_task(tid):
    t = q("SELECT * FROM tasks WHERE id=%s", (tid,), one=True)
    if not t:
        return err("Task not found", 404)
    d = request.get_json(silent=True) or {}
    try:
        nd = parse_dt(d.get("deadline") or "")
    except ValueError as e:
        return err(str(e))
    if t["status"] == "done":
        return err("Task is already completed")
    q("UPDATE tasks SET deadline=%s, overdue_notified=(%s < LOCALTIMESTAMP) WHERE id=%s", (nd, nd, tid), commit=True)
    way = "moved earlier" if nd < t["deadline"] else "extended"
    notify(t["assigned_to"], f"Deadline {way} for '{t['title']}': now {nd:%d %b %Y, %H:%M}", tid)
    return jsonify(ok=True)


@app.get("/api/manager/dashboard")
@auth("manager")
def dashboard():
    flag_overdue()
    tasks = fetch_tasks()
    open_t = [t for t in tasks if t["status"] != "done"]
    projects_ = q("""SELECT p.id,p.name,count(t.id) AS total, count(t.id) FILTER (WHERE t.status='done') AS done,
                     COALESCE(round(avg(t.progress)),0) AS progress
                     FROM projects p LEFT JOIN tasks t ON t.project_id=p.id GROUP BY p.id ORDER BY p.name""")
        return jsonify(
        counts={"total": len(tasks), "open": len(open_t), "done": len(tasks) - len(open_t),
                "overdue": sum(1 for t in open_t if t["overdue"]),
                "employees": q("SELECT count(*) AS c FROM users WHERE role='employee' AND active", one=True)["c"],
                "pending_requests": q("SELECT count(*) AS c FROM task_requests WHERE status='pending'", one=True)["c"]},
        projects=projects_, overdue=[t for t in open_t if t["overdue"]][:10],
        top_priorities=open_t[:5], today=working_today(), bottlenecks=find_bottlenecks())


@app.get("/api/manager/weekly-report")
@auth("manager")
def weekly_report():
    rows = q("""
      SELECT u.emp_code,u.name,u.post,
       count(t.id) FILTER (WHERE t.completed_at >= LOCALTIMESTAMP - interval '7 days') AS completed,
       count(t.id) FILTER (WHERE t.completed_at >= LOCALTIMESTAMP - interval '7 days' AND t.completed_at <= t.deadline) AS on_time,
       count(t.id) FILTER (WHERE t.status<>'done' AND t.deadline < LOCALTIMESTAMP) AS overdue_open,
       count(t.id) FILTER (WHERE t.status<>'done') AS open_tasks,
       COALESCE(round(avg(t.progress) FILTER (WHERE t.status<>'done')),0) AS avg_open_progress,
       (SELECT count(*) FROM daily_reports r WHERE r.user_id=u.id AND r.report_date >= CURRENT_DATE-6) AS reports
      FROM users u LEFT JOIN tasks t ON t.assigned_to=u.id
      WHERE u.role='employee' AND u.active GROUP BY u.id ORDER BY u.name""")
    for r in rows:
        late = r["completed"] - r["on_time"]
        score = 50 + r["on_time"] * 10 - late * 5 - r["overdue_open"] * 10 + min(r["reports"], 5) * 2
        r["late"], r["score"] = late, max(0, min(100, score))
        r["rating"] = "Excellent" if r["score"] >= 80 else "Good" if r["score"] >= 60 else \
            "Needs attention" if r["score"] >= 40 else "At risk"
    return jsonify(period_end=dt.date.today(), rows=rows)


@app.get("/api/manager/daily-summary")
@auth("manager")
def daily_summary():
    day = request.args.get("date") or dt.date.today().isoformat()
    rows = q("""SELECT u.name, r.content FROM daily_reports r JOIN users u ON u.id=r.user_id
                WHERE r.report_date=%s ORDER BY u.name""", (day,))
    return jsonify(date=day, reports=rows, **summarize_reports(rows))


# ---------------------------------------------------------------- employee
@app.get("/api/employee/tasks")
@auth("employee")
def my_tasks():
    flag_overdue()
    return jsonify(fetch_tasks("t.assigned_to=%s", (session["uid"],)))


@app.post("/api/employee/tasks/<int:tid>/update")
@auth("employee")
def update_task(tid):
    t = q("SELECT * FROM tasks WHERE id=%s AND assigned_to=%s", (tid, session["uid"]), one=True)
    if not t:
        return err("Task not found", 404)
    d = request.get_json(silent=True) or {}
    try:
        progress = max(0, min(100, int(d.get("progress", t["progress"]))))
    except (TypeError, ValueError):
        return err("Invalid progress")
    status = d.get("status") or t["status"]
    if status not in ("todo", "in_progress", "blocked", "done"):
        return err("Invalid status")
    if progress == 100:
        status = "done"
    if status == "done":
        progress = 100
    elif status == "todo" and progress > 0:
        status = "in_progress"
    q("""UPDATE tasks SET progress=%s, status=%s,
         completed_at = CASE WHEN %s='done' THEN COALESCE(completed_at, LOCALTIMESTAMP) ELSE NULL END WHERE id=%s""",
      (progress, status, status, tid), commit=True)
    q("INSERT INTO task_updates(task_id,user_id,progress,status,note) VALUES(%s,%s,%s,%s,%s)",
      (tid, session["uid"], progress, status, d.get("note")), commit=True)
    if status == "done" and t["status"] != "done":
        notify(manager_id(), f"Task completed by {session['name']} ({session.get('code', '')}): {t['title']}", tid)
        for r in q("SELECT DISTINCT assigned_to,title FROM tasks x JOIN task_dependencies d ON d.task_id=x.id "
                   "WHERE d.depends_on_id=%s", (tid,)):
            notify(r["assigned_to"], f"A dependency finished - you can progress on '{r['title']}'", tid)
    elif status == "blocked" and t["status"] != "blocked":
        notify(manager_id(), f"{session['name']} marked blocked: {t['title']}", tid)
    return jsonify(ok=True)


@app.post("/api/employee/daily-report")
@auth("employee")
def daily_report():
    content = ((request.get_json(silent=True) or {}).get("content") or "").strip()
    if not content:
        return err("Report cannot be empty")
    q("""INSERT INTO daily_reports(user_id,content) VALUES(%s,%s)
         ON CONFLICT (user_id,report_date) DO UPDATE SET content=EXCLUDED.content""",
      (session["uid"], content), commit=True)
    return jsonify(ok=True)


@app.get("/api/employee/daily-report")
@auth("employee")
def get_daily_report():
    r = q("SELECT content FROM daily_reports WHERE user_id=%s AND report_date=CURRENT_DATE", (session["uid"],), one=True)
    return jsonify(content=r["content"] if r else "")

# ---------------------------------------------------------------- change requests
@app.post("/api/employee/requests")
@auth("employee")
def create_request():
    d = request.get_json(silent=True) or {}
    try:
        tid = int(d.get("task_id"))
    except (TypeError, ValueError):
        return err("Choose the task you want to change")
    t = q("SELECT * FROM tasks WHERE id=%s AND assigned_to=%s AND status<>'done'", (tid, session["uid"]), one=True)
    if not t:
        return err("Task not found", 404)
    category = d.get("category")
    if category not in ("too_many_tasks", "other"):
        return err("Choose a reason")
    message = (d.get("message") or "").strip()
    if len(message) < 5:
        return err("Please explain your request (at least 5 characters)")
    if q("SELECT 1 FROM task_requests WHERE task_id=%s AND status='pending'", (tid,), one=True):
        return err("There is already a pending request for this task")
    q("""INSERT INTO task_requests(task_id,task_title,employee_id,category,message)
         VALUES(%s,%s,%s,%s,%s)""", (tid, t["title"], session["uid"], category, message), commit=True)
    why = "too many tasks" if category == "too_many_tasks" else "other reason"
    notify(manager_id(), f"{session['name']} ({session.get('code', '')}) asked for a change to "
                         f"'{t['title']}' ({why}): {message[:120]}", tid)
    return jsonify(ok=True)


@app.get("/api/employee/requests")
@auth("employee")
def my_requests():
    return jsonify(q("""SELECT id,task_title,category,message,status,manager_reply,created_at,resolved_at
                        FROM task_requests WHERE employee_id=%s ORDER BY created_at DESC""", (session["uid"],)))


@app.get("/api/manager/requests")
@auth("manager")
def list_requests():
    return jsonify(q("""
        SELECT r.id, r.task_id, r.task_title, r.category, r.message, r.status, r.manager_reply,
               r.created_at, r.resolved_at, u.name AS employee_name, u.emp_code, t.deadline, t.progress,
               (SELECT count(*) FROM tasks x WHERE x.assigned_to=r.employee_id AND x.status<>'done') AS open_tasks
        FROM task_requests r JOIN users u ON u.id=r.employee_id LEFT JOIN tasks t ON t.id=r.task_id
        ORDER BY (r.status='pending') DESC, r.created_at DESC LIMIT 100"""))


@app.get("/api/manager/employee-list")
@auth("manager")
def employee_list():
    return jsonify(q("""
        SELECT u.emp_code, u.name, u.post,
               (SELECT count(*) FROM tasks t WHERE t.assigned_to=u.id AND t.status<>'done') AS open_tasks
        FROM users u WHERE u.role='employee' AND u.active ORDER BY u.name"""))


@app.post("/api/manager/requests/<int:rid>/resolve")
@auth("manager")
def resolve_request(rid):
    r = q("SELECT * FROM task_requests WHERE id=%s", (rid,), one=True)
    if not r:
        return err("Request not found", 404)
    if r["status"] != "pending":
        return err("This request was already handled")
    d = request.get_json(silent=True) or {}
    action, reply = d.get("action"), (d.get("reply") or "").strip()
    if action not in ("reassign", "stop", "decline"):
        return err("Choose an action")
    t = q("SELECT * FROM tasks WHERE id=%s", (r["task_id"],), one=True) if r["task_id"] else None
    if action != "decline" and not t:
        return err("That task no longer exists")
    title, note = r["task_title"], (f" Manager's note: {reply}" if reply else "")

    if action == "reassign":
        new = q("SELECT * FROM users WHERE emp_code=%s AND role='employee' AND active",
                ((d.get("new_emp_code") or "").strip(),), one=True)
        if not new:
            return err("Choose an employee to reassign the task to")
        if new["id"] == r["employee_id"]:
            return err("Choose a different employee")
        q("UPDATE tasks SET assigned_to=%s, overdue_notified=FALSE WHERE id=%s", (new["id"], t["id"]), commit=True)
        notify(r["employee_id"], f"Request approved: '{title}' was reassigned to {new['name']}.{note}", t["id"])
        notify(new["id"], f"Task reassigned to you: {title} - deadline {t['deadline']:%d %b %Y, %H:%M}", t["id"])
        outcome = "reassigned"
    elif action == "stop":
        q("DELETE FROM tasks WHERE id=%s", (t["id"],), commit=True)   # the request row keeps task_title
        notify(r["employee_id"], f"Request approved: '{title}' has been stopped. You can stop working on it.{note}")
        outcome = "stopped"
    else:
        notify(r["employee_id"], f"Your request about '{title}' was declined.{note}", r["task_id"])
        outcome = "declined"

    q("UPDATE task_requests SET status=%s, manager_reply=%s, resolved_at=LOCALTIMESTAMP WHERE id=%s",
      (outcome, reply or None, rid), commit=True)
    return jsonify(ok=True)

@app.get("/")
def index():
    return app.send_static_file("index.html")


# ---------------------------------------------------------------- setup
def init_db():
    con = psycopg2.connect(DB_URL)
    cur = con.cursor()
    with open(os.path.join(os.path.dirname(__file__), "schema.sql")) as f:
        cur.execute(f.read())
    con.commit()
    con.close()
    print("Tables ready. Open the app in your browser to create the manager account.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "initdb":
        init_db()
    else:
        app.run(debug=True)
