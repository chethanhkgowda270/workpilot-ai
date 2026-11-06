CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  emp_code VARCHAR(30) UNIQUE NOT NULL,
  name VARCHAR(120) NOT NULL,
  role VARCHAR(10) NOT NULL CHECK (role IN ('manager','employee')),
  password_hash TEXT NOT NULL,
  post VARCHAR(80),
  department VARCHAR(80),
  email VARCHAR(120),
  joined_on DATE NOT NULL DEFAULT CURRENT_DATE,
  prior_experience_years NUMERIC(4,1) DEFAULT 0,
  active BOOLEAN NOT NULL DEFAULT TRUE
);
-- only ONE manager can ever exist
CREATE UNIQUE INDEX IF NOT EXISTS one_manager ON users(role) WHERE role = 'manager';

CREATE TABLE IF NOT EXISTS projects (
  id SERIAL PRIMARY KEY,
  name VARCHAR(120) UNIQUE NOT NULL,
  description TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
  id SERIAL PRIMARY KEY,
  title VARCHAR(200) NOT NULL,
  description TEXT,
  project_id INT REFERENCES projects(id) ON DELETE SET NULL,
  assigned_to INT NOT NULL REFERENCES users(id),
  assigned_by INT REFERENCES users(id),
  assigned_on TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP,
  deadline TIMESTAMP NOT NULL,
  status VARCHAR(12) NOT NULL DEFAULT 'todo' CHECK (status IN ('todo','in_progress','blocked','done')),
  progress INT NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
  completed_at TIMESTAMP,
  overdue_notified BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS task_dependencies (
  task_id INT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  depends_on_id INT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  PRIMARY KEY (task_id, depends_on_id)
);

CREATE TABLE IF NOT EXISTS task_updates (
  id SERIAL PRIMARY KEY,
  task_id INT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  user_id INT NOT NULL REFERENCES users(id),
  progress INT,
  status VARCHAR(12),
  note TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP
);

CREATE TABLE IF NOT EXISTS daily_reports (
  id SERIAL PRIMARY KEY,
  user_id INT NOT NULL REFERENCES users(id),
  report_date DATE NOT NULL DEFAULT CURRENT_DATE,
  content TEXT NOT NULL,
  UNIQUE (user_id, report_date)
);

CREATE TABLE IF NOT EXISTS notifications (
  id SERIAL PRIMARY KEY,
  user_id INT NOT NULL REFERENCES users(id),
  task_id INT REFERENCES tasks(id) ON DELETE CASCADE,
  message TEXT NOT NULL,
  is_read BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assigned_to, status);
CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id, is_read);

CREATE TABLE IF NOT EXISTS task_requests (
  id SERIAL PRIMARY KEY,
  task_id INT REFERENCES tasks(id) ON DELETE SET NULL,
  task_title VARCHAR(200) NOT NULL,
  employee_id INT NOT NULL REFERENCES users(id),
  category VARCHAR(20) NOT NULL CHECK (category IN ('too_many_tasks','other')),
  message TEXT NOT NULL,
  status VARCHAR(12) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','reassigned','stopped','declined')),
  manager_reply TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP,
  resolved_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_requests_status ON task_requests(status);