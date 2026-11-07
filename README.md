# WorkPilot AI

Employee productivity and workflow management for small companies.
Stack: Flask (Python) + vanilla JavaScript + PostgreSQL.

## Setup
1. Create the database:  `createdb workpilot`
2. Install dependencies:
   ```
   cd backend
   python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Set environment variables (see `.env.example`), at minimum `DATABASE_URL` and `SECRET_KEY`.
4. Create the tables:  `python app.py initdb`
5. Run:  `python app.py`  then open http://localhost:5000
6. The first time you open the app it shows first-time setup: choose your own manager ID and a strong password. After that the normal login appears.

## How it works
- **Manager login** (one account only, enforced by a unique index). Employees log in with the ID the manager created plus a password.
- **Employee lookup**: enter an employee ID to see post, department, time in company, total experience, assigned work with progress, and to assign tasks or change a deadline (including bringing it earlier). The employee is notified.
- **Employee side**: popup on login for unread notifications, toast popups every 15 seconds while online, progress updates, daily report.
- **Dashboard**: counts, project progress, overdue tasks, AI priorities, bottlenecks, and who is working today.

## AI features (rule-based, no API key needed)
- Overdue detection: automatic on dashboard/task load, notifies employee and manager once.
- Priority: score from time to deadline, number of tasks waiting on it, remaining work, and unfinished dependencies.
- Bottlenecks: blocking tasks at risk, blocked tasks, stalled work (3+ days no update), overloaded employees.
- Weekly performance: completed, on-time, late, overdue, report consistency, score.
- Daily summary: built-in summarizer with blocker keyword detection. Set `ANTHROPIC_API_KEY` to get Claude-written summaries instead.
- Change requests: employees can ask the manager to reassign or stop a task (for example when overloaded); the manager approves, reassigns or declines, and the employee is notified.` 

## Before real use
Set a strong `SECRET_KEY`, run behind HTTPS, and use gunicorn instead of `app.run(debug=True)`.
