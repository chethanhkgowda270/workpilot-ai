const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = d => d ? new Date(d).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "-";
const bar = p => `<div class="bar"><i style="width:${p}%"></i></div>`;
const statusLabel = s => ({ todo: "To do", in_progress: "In progress", blocked: "Blocked", done: "Done" }[s] || s);
const toLocalInput = d => { const x = new Date(d); x.setMinutes(x.getMinutes() - x.getTimezoneOffset()); return x.toISOString().slice(0, 16); };

async function api(url, method = "GET", body) {
  const r = await fetch(url, { method, credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { if (r.status === 401 && me) { location.reload(); } throw new Error(j.error || "Request failed"); }
  return j;
}

let me = null, pollTimer = null, seenNotifs = new Set(), currentEmp = null;

/* ---------------------------------------------------------- boot / login */
async function boot() {
  try { me = await api("/api/me"); startApp(); return; } catch { }
  const st = await api("/api/setup-status");
  st.needs_setup ? showSetup() : showLogin();
}

/* strong-password rules (the server checks the same rules again) */
const PW_RULES = [
  [/.{8,}/, "At least 8 characters"], [/[A-Z]/, "One uppercase letter"], [/[a-z]/, "One lowercase letter"],
  [/\d/, "One number"], [/[^A-Za-z0-9\s]/, "One special character (@ # $ ! ...)"], [/^\S+$/, "No spaces"]
];
const pwStrong = pw => PW_RULES.every(([r]) => r.test(pw));
function pwChecklist(inputId, boxId) {
  const pw = $("#" + inputId).value;
  $("#" + boxId).innerHTML = PW_RULES.map(([r, label]) => r.test(pw) ? `<div class="okc">✔ ${label}</div>` : `<div class="mute">○ ${label}</div>`).join("");
}

function showSetup() {
  $("#topbar").hidden = true;
  $("#view").innerHTML = `
  <div class="auth-wrap"><div class="auth-card" data-role="manager">
    <div class="auth-logo">🚀</div>
    <h2>Welcome to WorkPilot <span>AI</span></h2>
    <p class="auth-sub">First-time setup: create the manager account. You will use this ID and password to log in from now on.</p>
    <label>Your full name</label><input id="s_name" placeholder="e.g. Chethan H K Gowda">
    <label>Choose your manager ID</label><input id="s_id" autocomplete="username" placeholder="e.g. manager.chethan">
    <label>Choose a password</label><input id="s_pw" type="password" autocomplete="new-password" oninput="pwChecklist('s_pw','s_box')">
    <div id="s_box" class="mute" style="margin-top:6px"></div>
    <label>Confirm password</label><input id="s_pw2" type="password" autocomplete="new-password">
    <button class="btn-main" onclick="doSetup()">Create manager account</button>
    <div id="serr" class="err"></div>
  </div></div>`;
  pwChecklist("s_pw", "s_box");
}

async function doSetup() {
  const pw = $("#s_pw").value;
  if (pw !== $("#s_pw2").value) { $("#serr").textContent = "Passwords do not match"; return; }
  if (!pwStrong(pw)) { $("#serr").textContent = "Password is not strong enough - see the checklist"; return; }
  try {
    me = await api("/api/setup", "POST", { name: $("#s_name").value, emp_code: $("#s_id").value, password: pw });
    startApp();
  } catch (e) { $("#serr").textContent = e.message; }
}

function showLogin(role = "manager") {
  const mgr = role === "manager";
  $("#topbar").hidden = true;
  $("#view").innerHTML = `
  <div class="auth-wrap"><div class="auth-card" data-role="${role}">
    <div class="auth-logo">${mgr ? "👔" : "👤"}</div>
    <h2>WorkPilot <span>AI</span></h2>
    <p class="auth-sub">${mgr ? "Manager sign in: manage your team, tasks and deadlines" : "Employee sign in: see your tasks and deadlines"}</p>
    <div class="seg">
      <button class="${mgr ? "on" : ""}" onclick="showLogin('manager')">👔 Manager</button>
      <button class="${mgr ? "" : "on"}" onclick="showLogin('employee')">👤 Employee</button>
    </div>
    <label>${mgr ? "Manager ID" : "Employee ID (given by your manager)"}</label>
    <input id="lid" autocomplete="username" placeholder="${mgr ? "e.g. manager0**" : "e.g. emp0**"}" onkeydown="if(event.key==='Enter')$('#lpw').focus()">
    <label>Password</label>
    <div class="pwbox">
      <input id="lpw" type="password" autocomplete="current-password" placeholder="Your password" onkeydown="if(event.key==='Enter')doLogin('${role}')">
      <button type="button" id="pwt" onclick="togglePw()">Show</button>
    </div>
    <button class="btn-main" onclick="doLogin('${role}')">Log in as ${mgr ? "Manager" : "Employee"}</button>
    <div id="lerr" class="err"></div>
  </div></div>`;
  $("#lid").focus();
}

function togglePw() {
  const i = $("#lpw"), b = $("#pwt"), show = i.type === "password";
  i.type = show ? "text" : "password"; b.textContent = show ? "Hide" : "Show";
}

async function doLogin(role) {
  try {
    me = await api("/api/login", "POST", { emp_code: $("#lid").value, password: $("#lpw").value, role });
    startApp();
  } catch (e) { $("#lerr").textContent = e.message; }
}

async function logout() { clearInterval(pollTimer); seenNotifs.clear(); await api("/api/logout", "POST"); me = null; showLogin(); }

function startApp() {
  $("#topbar").hidden = false;
  $("#whoami").textContent = `${me.name} (${me.role})`;
  const tabs = me.role === "manager"
    ? [["dashboard", "Dashboard"], ["lookup", "Employee lookup"], ["requests", "Requests"], ["team", "New Employee and Project"], ["reports", "Reports"], ["notifs", "Notifications"]]
    : [["tasks", "My tasks"], ["report", "Daily report"], ["myreq", "My requests"], ["notifs", "Notifications"]];
  $("#nav").innerHTML = tabs.map(([k, l]) => `<button data-k="${k}" onclick="go('${k}')">${l}</button>`).join("");
  go(tabs[0][0]);
  initNotifications();
}

function go(k) {
  document.querySelectorAll("#nav button").forEach(b => b.classList.toggle("active", b.dataset.k === k));
  ({ dashboard: viewDashboard, lookup: viewLookup, team: viewTeam, reports: viewReports, notifs: viewNotifs,
     tasks: viewTasks, report: viewDailyReport, requests: viewRequests, myreq: viewMyRequests }[k])();
}

/* ---------------------------------------------------------- notifications / popups */
async function initNotifications() {
  const first = await api("/api/notifications?unread=1");
  if (first.length) {
    first.forEach(n => seenNotifs.add(n.id));
    $("#modalBox").innerHTML = `<h3 style="margin-top:0">🔔 You have ${first.length} new notification(s)</h3>` +
      first.map(n => `<div class="card" style="padding:10px;margin-bottom:8px">${esc(n.message)}<div class="mute">${fmt(n.created_at)}</div></div>`).join("") +
      `<button onclick="closeModal()">Got it</button>`;
    $("#modal").hidden = false;
    api("/api/notifications/read", "POST", { ids: first.map(n => n.id) });
  }
  clearInterval(pollTimer);
  pollTimer = setInterval(pollNotifications, 15000);
}
function closeModal() { $("#modal").hidden = true; }

async function pollNotifications() {
  try {
    const rows = await api("/api/notifications?unread=1");
    const fresh = rows.filter(n => !seenNotifs.has(n.id));
    fresh.forEach(n => { seenNotifs.add(n.id); toast(n.message); });
    if (fresh.length) {
      api("/api/notifications/read", "POST", { ids: fresh.map(n => n.id) });
      const active = document.querySelector("#nav button.active")?.dataset.k;
      if (["tasks", "dashboard", "requests", "myreq"].includes(active)) go(active);
    }
  } catch { }
}
function toast(msg) {
  const t = document.createElement("div"); t.className = "toast"; t.textContent = "🔔 " + msg;
  $("#toasts").appendChild(t); setTimeout(() => t.remove(), 9000);
}
async function viewNotifs() {
  const rows = await api("/api/notifications");
  $("#view").innerHTML = `<div class="card"><h3>Notifications</h3>` +
    (rows.length ? rows.map(n => `<div style="padding:8px 0;border-bottom:1px solid var(--line)">${esc(n.message)}<div class="mute">${fmt(n.created_at)}</div></div>`).join("") : `<p class="mute">Nothing yet.</p>`) + `</div>`;
}

/* ---------------------------------------------------------- manager: dashboard */
async function viewDashboard() {
  const d = await api("/api/manager/dashboard"), c = d.counts;
  const taskRows = (ts, extra) => ts.length ? `<table><tr><th>Task</th><th>Employee</th><th>${extra}</th></tr>` + ts.map(t => `<tr><td>${esc(t.title)}</td><td>${esc(t.employee_name)}</td><td>${extra === "Priority" ? `<span class="badge ${t.ai_priority.label}">${t.ai_priority.label}</span> <span class="mute">${esc(t.ai_priority.reason)}</span>` : fmt(t.deadline)}</td></tr>`).join("") + `</table>` : `<p class="mute">None 🎉</p>`;
  $("#view").innerHTML = `
  <div class="grid g4">
    ${[["Employees", c.employees], ["Open tasks", c.open], ["Completed", c.done], ["Overdue", c.overdue], ["Pending requests", c.pending_requests]].map(([l, v]) => `<div class="card"><div class="stat">${v}<small>${l}</small></div></div>`).join("")}
  </div>
  <div class="card"><h3>👥 Who is working today</h3>
    ${d.today.working.length ? `<table><tr><th>Employee</th><th>Active tasks</th></tr>` + d.today.working.map(e => `<tr><td><b>${esc(e.name)}</b><div class="mute">${esc(e.emp_code)} · ${esc(e.post || "")}</div></td><td>${e.tasks.map(t => `<div>${esc(t.title)} ${t.overdue ? '<span class="badge bad">overdue</span>' : ""} <span class="mute">due ${fmt(t.deadline)} · ${statusLabel(t.status)}</span>${bar(t.progress)}</div>`).join("")}</td></tr>`).join("") + `</table>` : `<p class="mute">Nobody has active tasks today.</p>`}
    ${d.today.free.length ? `<p class="mute">Available (no active tasks): ${d.today.free.map(e => esc(e.name)).join(", ")}</p>` : ""}
  </div>
  <div class="grid g2">
    <div class="card"><h3>📁 Project progress</h3>${d.projects.length ? d.projects.map(p => `<div style="margin-bottom:10px"><b>${esc(p.name)}</b> <span class="mute">${p.done}/${p.total} tasks · ${p.progress}% avg</span>${bar(p.progress)}</div>`).join("") : `<p class="mute">No projects yet. Add one in Team & projects.</p>`}</div>
    <div class="card"><h3>🚧 Bottlenecks</h3>${d.bottlenecks.length ? d.bottlenecks.map(b => `<p><span class="badge ${b.severity}">${esc(b.type)}</span> ${esc(b.message)}</p>`).join("") : `<p class="mute">No bottlenecks detected.</p>`}</div>
  </div>
  <div class="grid g2">
    <div class="card"><h3>⏰ Overdue tasks</h3>${taskRows(d.overdue, "Deadline")}</div>
    <div class="card"><h3>🎯 AI-recommended priorities</h3>${taskRows(d.top_priorities, "Priority")}</div>
  </div>`;
}

/* ---------------------------------------------------------- manager: employee lookup */
function viewLookup() {
  $("#view").innerHTML = `<div class="card"><h3>Find employee by unique ID</h3>
    <div class="row"><div><label>Employee ID</label><input id="empid" onkeydown="if(event.key==='Enter')lookup()"></div><button onclick="lookup()">Search</button></div>
    <div id="lerr" class="err"></div></div><div id="empview"></div>`;
  if (currentEmp) { $("#empid").value = currentEmp; lookup(); }
}

async function lookup() {
  const code = $("#empid").value.trim(); if (!code) return;
  try {
    const d = await api("/api/manager/employees/" + encodeURIComponent(code));
    currentEmp = code; $("#lerr").textContent = "";
    const p = d.profile, s = d.stats;
    const [projects, openTasks] = await Promise.all([api("/api/manager/projects"), api("/api/manager/open-tasks")]);
    $("#empview").innerHTML = `
    <div class="card"><h3>${esc(p.name)} <span class="mute">· ${esc(p.emp_code)}</span></h3>
      <div class="grid g4">
        <div><div class="mute">Post</div><b>${esc(p.post || "-")}</b></div>
        <div><div class="mute">Department</div><b>${esc(p.department || "-")}</b></div>
        <div><div class="mute">Experience in this company</div><b>${p.time_in_company}</b></div>
        <div><div class="mute">Total experience</div><b>${p.total_experience_years} yrs</b></div>
        <div><div class="mute">Joined</div><b>${fmt(p.joined_on).split(",").slice(0, 2).join(",")}</b></div>
        <div><div class="mute">Email</div><b>${esc(p.email || "-")}</b></div>
        <div><div class="mute">Tasks (open / done)</div><b>${s.open} / ${s.done}</b></div>
        <div><div class="mute">Overdue · avg progress</div><b>${s.overdue} · ${s.avg_progress}%</b></div>
      </div></div>
    <div class="card"><h3>Assigned work &amp; progress</h3>
      ${d.tasks.length ? d.tasks.map(t => `
        <div class="task ${t.overdue ? "overdue" : ""}">
          <div class="task-head"><b>${esc(t.title)}</b>
            <span><span class="badge ${t.ai_priority.label}">${t.ai_priority.label}</span> <span class="badge">${statusLabel(t.status)}</span> ${t.overdue ? '<span class="badge bad">overdue</span>' : ""}</span></div>
          <div class="mute">${esc(t.project_name || "No project")} · assigned ${fmt(t.assigned_on)} · deadline <b>${fmt(t.deadline)}</b></div>
          ${t.description ? `<p>${esc(t.description)}</p>` : ""}
          <div class="row" style="align-items:center"><div>${bar(t.progress)}</div><div class="mute" style="flex:0">${t.progress}%</div></div>
          <div class="mute">AI: ${esc(t.ai_priority.reason)}</div>
          ${t.status !== "done" ? `<div class="row" style="margin-top:8px"><div><label>Change deadline (e.g. bring it earlier)</label><input type="datetime-local" id="dl${t.id}" value="${toLocalInput(t.deadline)}"></div><button class="sm" onclick="saveDeadline(${t.id})">Update deadline</button></div>` : ""}
        </div>`).join("") : `<p class="mute">No work assigned yet.</p>`}
    </div>
    <div class="card"><h3>Assign new task</h3>
      <label>Title</label><input id="nt">
      <label>Description</label><textarea id="nd" rows="3"></textarea>
      <div class="row"><div><label>Project</label><select id="np"><option value="">- none -</option>${projects.map(x => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select></div>
        <div><label>Deadline</label><input type="datetime-local" id="ndl"></div></div>
      <label>Depends on (hold Ctrl/Cmd to pick several)</label>
      <select id="ndep" multiple size="4">${openTasks.map(x => `<option value="${x.id}"> ${esc(x.title)} (${esc(x.employee_name)})</option>`).join("")}</select>
      <div style="margin-top:12px"><button onclick="assignTask('${esc(p.emp_code)}')">Assign &amp; notify employee</button></div><div id="aerr" class="err"></div>
    </div>`;
  } catch (e) { $("#lerr").textContent = e.message; $("#empview").innerHTML = ""; }
}

async function assignTask(code) {
  try {
    await api("/api/manager/tasks", "POST", {
      emp_code: code, title: $("#nt").value, description: $("#nd").value, project_id: $("#np").value || null,
      deadline: $("#ndl").value, depends_on: [...$("#ndep").selectedOptions].map(o => o.value)
    });
    toast("Task assigned. The employee has been notified."); lookup();
  } catch (e) { $("#aerr").textContent = e.message; }
}
async function saveDeadline(id) {
  try { await api("/api/manager/tasks/" + id, "PATCH", { deadline: $("#dl" + id).value }); toast("Deadline updated. Employee notified."); lookup(); }
  catch (e) { toast(e.message); }
}

/* ---------------------------------------------------------- manager: team & projects */
async function viewTeam() {
  const projects = await api("/api/manager/projects");
  $("#view").innerHTML = `
  <div class="grid g2">
    <div class="card"><h3>Add employee</h3>
      <div class="row"><div><label>Unique employee ID</label><input id="e_code"></div><div><label>Initial password</label><input id="e_pw" oninput="pwChecklist('e_pw','e_pwbox')"></div></div>
      <div id="e_pwbox" class="mute"></div>
      <label>Full name</label><input id="e_name">
      <div class="row"><div><label>Post / designation</label><input id="e_post" placeholder="Software Engineer"></div><div><label>Department</label><input id="e_dept" placeholder="Engineering"></div></div>
      <div class="row"><div><label>Email</label><input id="e_mail" type="email"></div><div><label>Joined on</label><input id="e_join" type="date" value="${new Date().toISOString().slice(0, 10)}"></div><div><label>Prior experience (yrs)</label><input id="e_exp" type="number" step="0.5" value="0"></div></div>
      <div style="margin-top:12px"><button onclick="addEmployee()">Create employee</button></div><div id="eerr" class="err"></div></div>
    <div class="card"><h3>Projects</h3>
      <ul>${projects.map(p => `<li>${esc(p.name)}</li>`).join("") || '<li class="mute">None yet</li>'}</ul>
      <label>New project name</label><input id="p_name"><label>Description</label><input id="p_desc">
      <div style="margin-top:12px"><button onclick="addProject()">Add project</button></div><div id="perr" class="err"></div></div>
  </div>`;
}
async function addEmployee() {
  if (!pwStrong($("#e_pw").value)) { $("#eerr").textContent = "Password is not strong enough - see the checklist"; return; }
  try {
    await api("/api/manager/employees", "POST", { emp_code: $("#e_code").value, password: $("#e_pw").value, name: $("#e_name").value, post: $("#e_post").value, department: $("#e_dept").value, email: $("#e_mail").value, joined_on: $("#e_join").value, prior_experience_years: $("#e_exp").value });
    toast("Employee created. Share their ID and password with them."); viewTeam();
  } catch (e) { $("#eerr").textContent = e.message; }
}
async function addProject() {
  try { await api("/api/manager/projects", "POST", { name: $("#p_name").value, description: $("#p_desc").value }); viewTeam(); }
  catch (e) { $("#perr").textContent = e.message; }
}

/* ---------------------------------------------------------- manager: reports */
async function viewReports() {
  const w = await api("/api/manager/weekly-report");
  $("#view").innerHTML = `
  <div class="card"><h3>📊 Weekly performance (last 7 days)</h3>
    <table><tr><th>Employee</th><th>Completed</th><th>On time</th><th>Late</th><th>Open</th><th>Overdue</th><th>Avg open progress</th><th>Daily reports</th><th>Score</th></tr>
    ${w.rows.map(r => `<tr><td><b>${esc(r.name)}</b><div class="mute">${esc(r.emp_code)}</div></td><td>${r.completed}</td><td>${r.on_time}</td><td>${r.late}</td><td>${r.open_tasks}</td><td>${r.overdue_open}</td><td>${r.avg_open_progress}%</td><td>${r.reports}/7</td><td><b>${r.score}</b> <span class="badge ${r.score >= 60 ? "ok" : r.score >= 40 ? "warn" : "bad"}">${r.rating}</span></td></tr>`).join("")}</table>
    <p class="mute">Score = 50 + 10 per on-time completion − 5 per late completion − 10 per overdue open task + 2 per daily report (max 5).</p></div>
  <div class="card"><h3>📝 Daily report summary</h3>
    <div class="row"><div><label>Date</label><input type="date" id="sd" value="${new Date().toISOString().slice(0, 10)}"></div><button onclick="loadSummary()">Summarize</button></div>
    <div id="sum" style="margin-top:12px"></div></div>`;
  loadSummary();
}
async function loadSummary() {
  const d = await api("/api/manager/daily-summary?date=" + $("#sd").value);
  $("#sum").innerHTML = `<pre>${esc(d.summary)}</pre>` +
    (d.blockers.length ? `<h4>Possible blockers</h4><ul>${d.blockers.map(b => `<li>${esc(b)}</li>`).join("")}</ul>` : "") +
    `<p class="mute">${d.reports.length} report(s) · summarized by ${d.source}</p>`;
}

/* ---------------------------------------------------------- employee */
async function viewTasks() {
    const ts = await api("/api/employee/tasks"); myTasks = ts;
  const open = ts.filter(t => t.status !== "done"), done = ts.filter(t => t.status === "done");
  $("#view").innerHTML = `<div class="card"><h3>My tasks <span class="mute">(sorted by AI-recommended priority)</span></h3>
    ${open.map(t => `
    <div class="task ${t.overdue ? "overdue" : ""}">
      <div class="task-head"><b>${esc(t.title)}</b><span><span class="badge ${t.ai_priority.label}">${t.ai_priority.label}</span> ${t.overdue ? '<span class="badge bad">overdue</span>' : ""}</span></div>
      <div class="mute">${esc(t.project_name || "No project")} · deadline <b>${fmt(t.deadline)}</b></div>
      ${t.description ? `<p>${esc(t.description)}</p>` : ""}
      <div class="mute">Why this priority: ${esc(t.ai_priority.reason)}</div>
      <div class="row" style="margin-top:8px">
        <div><label>Progress: <span id="pv${t.id}">${t.progress}</span>%</label><input type="range" min="0" max="100" step="5" value="${t.progress}" id="pr${t.id}" oninput="$('#pv${t.id}').textContent=this.value"></div>
        <div><label>Status</label><select id="st${t.id}">${["todo", "in_progress", "blocked", "done"].map(s => `<option value="${s}" ${t.status === s ? "selected" : ""}>${statusLabel(s)}</option>`).join("")}</select></div>
        <div><label>Note</label><input id="nt${t.id}" placeholder="optional"></div>
        <button class="sm" onclick="saveTask(${t.id})">Save</button>
          <button class="sm ghost" onclick="openRequest(${t.id})">Request change</button>
      </div>
    </div>`).join("") || `<p class="mute">No open tasks. 🎉</p>`}</div>
    ${done.length ? `<div class="card"><h3>Completed</h3>${done.map(t => `<div>✅ ${esc(t.title)} <span class="mute">${fmt(t.completed_at)}</span></div>`).join("")}</div>` : ""}`;
}
async function saveTask(id) {
  try { await api(`/api/employee/tasks/${id}/update`, "POST", { progress: $("#pr" + id).value, status: $("#st" + id).value, note: $("#nt" + id).value }); toast("Progress saved"); viewTasks(); }
  catch (e) { toast(e.message); }
}
async function viewDailyReport() {
  const r = await api("/api/employee/daily-report");
  $("#view").innerHTML = `<div class="card"><h3>Today's work report</h3>
    <p class="mute">What did you do today? Mention anything blocking you. Your manager gets an automatic summary.</p>
    <textarea id="rep" rows="8">${esc(r.content)}</textarea>
    <div style="margin-top:12px"><button onclick="saveReport()">Submit report</button></div></div>`;
}
async function saveReport() {
  try { await api("/api/employee/daily-report", "POST", { content: $("#rep").value }); toast("Report submitted"); } catch (e) { toast(e.message); }
}

/* ---------------------------------------------------------- employee: ask the manager to change a task */
let myTasks = [];

function openRequest(id) {
  const t = myTasks.find(x => x.id === id); if (!t) return;
  $("#modalBox").innerHTML = `
    <h3 style="margin-top:0">Request a change</h3>
    <p class="mute">Task: <b>${esc(t.title)}</b></p>
    <label>Reason</label>
    <select id="rq_cat">
      <option value="too_many_tasks">I have been given too many tasks</option>
      <option value="other">Something else</option>
    </select>
    <label>Explain to your manager</label>
    <textarea id="rq_msg" rows="4" placeholder="e.g. I already have 5 open tasks due this week, so I cannot finish this one in time."></textarea>
    <div style="margin-top:14px;display:flex;gap:8px">
      <button onclick="sendRequest(${id})">Send to manager</button>
      <button class="ghost" onclick="closeModal()">Cancel</button>
    </div>
    <div id="rq_err" class="err"></div>`;
  $("#modal").hidden = false;
}

async function sendRequest(id) {
  try {
    await api("/api/employee/requests", "POST", { task_id: id, category: $("#rq_cat").value, message: $("#rq_msg").value });
    closeModal(); toast("Request sent to your manager.");
  } catch (e) { $("#rq_err").textContent = e.message; }
}

const REQ_LABEL = { pending: "Waiting for manager", reassigned: "Approved: reassigned", stopped: "Approved: task stopped", declined: "Declined" };
const REQ_CLASS = { pending: "warn", reassigned: "ok", stopped: "ok", declined: "bad" };
const REQ_REASON = c => c === "too_many_tasks" ? "Too many tasks" : "Other";

async function viewMyRequests() {
  const rows = await api("/api/employee/requests");
  $("#view").innerHTML = `<div class="card"><h3>My change requests</h3>` + (rows.length
    ? `<table><tr><th>Task</th><th>Reason</th><th>Status</th><th>Manager's reply</th><th>Sent</th></tr>` +
      rows.map(r => `<tr><td>${esc(r.task_title)}</td><td>${REQ_REASON(r.category)}<div class="mute">${esc(r.message)}</div></td><td><span class="badge ${REQ_CLASS[r.status]}">${REQ_LABEL[r.status]}</span></td><td>${esc(r.manager_reply || "-")}</td><td class="mute">${fmt(r.created_at)}</td></tr>`).join("") + `</table>`
    : `<p class="mute">You have not sent any requests.</p>`) + `</div>`;
}

/* ---------------------------------------------------------- manager: handle employee requests */
async function viewRequests() {
  const [rows, emps] = await Promise.all([api("/api/manager/requests"), api("/api/manager/employee-list")]);
  const pending = rows.filter(r => r.status === "pending"), done = rows.filter(r => r.status !== "pending");
  $("#view").innerHTML = `
  <div class="card"><h3>Pending requests (${pending.length})</h3>
    ${pending.map(r => `
      <div class="task">
        <div class="task-head"><b>${esc(r.task_title)}</b><span class="badge ${r.category === "too_many_tasks" ? "warn" : ""}">${REQ_REASON(r.category)}</span></div>
        <div class="mute">From <b>${esc(r.employee_name)}</b> (${esc(r.emp_code)}) · ${r.open_tasks} open task(s) · deadline ${fmt(r.deadline)} · ${r.progress ?? 0}% done · sent ${fmt(r.created_at)}</div>
        <p>${esc(r.message)}</p>
        <div class="row">
          <div><label>Reassign to</label><select id="rn${r.id}"><option value="">- choose employee -</option>${emps.filter(e => e.emp_code !== r.emp_code).map(e => `<option value="${esc(e.emp_code)}">${esc(e.name)} (${e.open_tasks} open)</option>`).join("")}</select></div>
          <div><label>Reply to employee (optional)</label><input id="rr${r.id}"></div>
        </div>
        <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
          <button class="sm" onclick="resolveRequest(${r.id},'reassign')">Reassign task</button>
          <button class="sm" onclick="resolveRequest(${r.id},'stop')">Stop task</button>
          <button class="sm ghost" onclick="resolveRequest(${r.id},'decline')">Decline request</button>
        </div>
      </div>`).join("") || `<p class="mute">No pending requests.</p>`}
  </div>
  <div class="card"><h3>History</h3>${done.length
    ? `<table><tr><th>Employee</th><th>Task</th><th>Outcome</th><th>Your reply</th><th>Handled</th></tr>` +
      done.map(r => `<tr><td>${esc(r.employee_name)}</td><td>${esc(r.task_title)}</td><td><span class="badge ${REQ_CLASS[r.status]}">${REQ_LABEL[r.status]}</span></td><td>${esc(r.manager_reply || "-")}</td><td class="mute">${fmt(r.resolved_at)}</td></tr>`).join("") + `</table>`
    : `<p class="mute">Nothing handled yet.</p>`}</div>`;
}

async function resolveRequest(id, action) {
  if (action === "stop" && !confirm("Stop this task? It will be removed permanently.")) return;
  try {
    await api(`/api/manager/requests/${id}/resolve`, "POST", { action, new_emp_code: $("#rn" + id).value, reply: $("#rr" + id).value });
    toast("Done. The employee has been notified."); viewRequests();
  } catch (e) { toast(e.message); }
}

boot();
