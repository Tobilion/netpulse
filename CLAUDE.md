# NetPulse — CLAUDE.md

ISP performance tracker: logs speed tests, ping latency (1.1.1.1 + 8.8.8.8), packet loss, and outages to local SQLite; Flask dashboard visualizes trends. Windows-first (Task Scheduler for background collection).

## Stack
- Python 3.9+, Flask, speedtest-cli, SQLite (`netpulse.db`, WAL — `-shm`/`-wal`/`-journal` files are normal)
- Files: `main.py` (CLI entry), `logger.py` (measurement cycle), `db.py`, `dashboard.py` (Flask), `templates/`, `tests/`

## Run
```
cd C:\Users\tobil\Desktop\Projects\netpulse
venv\Scripts\activate
python main.py once                  # one measurement (~30-60s)
python main.py watch --interval 30   # measure every 30 min while terminal open
python main.py serve                 # dashboard on http://localhost:5000
python main.py demo                  # seed 14 days of fake data
python main.py export                # dump CSVs
```
Background collection = Windows Task Scheduler running `venv\Scripts\python.exe` with args `main.py once`, "Start in" = this folder (7-step guide in README).

## Gotchas
- **The venv hard-codes its creation path.** This folder was moved once already (from `newproject\netpulse`); if Python errors look weird after any move, delete `venv/` and recreate (`python -m venv venv` → activate → `pip install -r requirements.txt`).
- **Do not move/rename this folder** without updating the Task Scheduler task ("Start in" path) — collection silently stops otherwise.
- `netpulse.db` is live user data — never delete casually. Deleting it is only correct when intentionally resetting after `demo`.
- Failed speed tests are recorded as outages by design, not crashes. Gaps (PC off/asleep) are absence of data, not outages.
- localhost:5000 only works while `serve` runs; collection and serving are fully independent (DB is the only link).
- Speed tests behind VPN/proxy can fail or read low.
