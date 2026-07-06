# NetPulse

**Track how your ISP *actually* performs — not what they promise.**

NetPulse logs your internet connection's real performance over time — download/upload speed, latency, packet loss, and outages — into a local SQLite database, and visualizes everything in a premium dark-themed web dashboard.

## Dashboard

The dashboard (`python main.py serve`) features a fully animated, component-rich UI:

- **Hero section** — live status headline with a text scramble animation, uptime progress ring, and "last measured N min ago" pill
- **Stat cards** — animated counters, spotlight glow on hover, 3D cursor tilt
- **Charts** — Download/upload speed (draws left→right on load), latency over time, and an hourly speed profile (great for spotting evening congestion) — all with gradient fills and dark custom tooltips
- **Outage log** — red-tinted incident cards; click any to open a detail modal
- **Empty state** — if the DB has no data, the dashboard explains exactly what to run with a one-click copy button
- **Time range filter** — 24h / 7d / 30d / All, with an animated sliding pill indicator

## Setup (Windows)

Requires Python 3.9+. In PowerShell:

```powershell
cd C:\Users\tobil\Desktop\Projects\netpulse
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

```powershell
# Single measurement cycle (~30–60s)
python main.py once

# Measure continuously every 30 minutes
python main.py watch --interval 30

# Open the dashboard at http://localhost:5000
python main.py serve

# Seed 14 days of realistic demo data (great for previewing the UI)
python main.py demo

# Export all data to CSV
python main.py export
```

A typical setup: use `watch` or Windows Task Scheduler to collect in the background, then open `serve` whenever you want to review your ISP.

## Scheduling with Windows Task Scheduler

To log measurements automatically every 30 minutes without keeping a terminal open:

1. Press `Win + R`, type `taskschd.msc`, press Enter.
2. Click **Create Task…** in the right panel.
3. **General tab:** name it `NetPulse Logger`. Check **Run whether user is logged on or not** for true background operation.
4. **Triggers tab:** New → On a schedule → Daily → Advanced: **Repeat task every 30 minutes**, Duration: **Indefinitely** → OK.
5. **Actions tab:** New → Start a program.
   - Program/script: `C:\Users\tobil\Desktop\Projects\netpulse\venv\Scripts\python.exe`
   - Arguments: `main.py once`
   - Start in: `C:\Users\tobil\Desktop\Projects\netpulse`
6. **Conditions tab:** uncheck **Start only if on AC power** (stops on battery otherwise).
7. Click OK, enter your Windows password if prompted, then right-click the task → **Run** to verify.

## Project structure

```
netpulse/
├── main.py               # CLI entry point (once / watch / export / demo / serve)
├── logger.py             # one measurement cycle: speed test + pings
├── db.py                 # SQLite storage layer
├── dashboard.py          # Flask app + /api/data JSON endpoint
├── templates/
│   └── dashboard.html    # Lean HTML shell (no inline CSS/JS)
├── static/
│   ├── css/
│   │   ├── main.css      # Design tokens, layout, hero, cards, footer
│   │   └── components.css # Nav, toast, modal, skeleton, empty state, ring
│   └── js/
│       ├── components.js # 13 reusable UI components (ES module)
│       ├── charts.js     # Chart.js config, gradients, draw animation
│       └── app.js        # Data fetch, render pipeline, component wiring
├── tests/
│   └── test_db.py        # pytest suite for the db module
├── requirements.txt
└── netpulse.db           # created on first run (git-ignored)
```

## Running the tests

```powershell
pip install pytest
python -m pytest tests/ -v
```

## Why I built this

I live in Lagos, and like many people here I pay for an internet plan whose advertised speed and my actual experience often feel like two different products. Rather than arguing from vibes, I wanted numbers: how fast is my connection really, at what times of day does it degrade, and how often does it go down entirely? NetPulse gives me that evidence — and it was a fun way to practice building a complete small system: data collection, storage, a CLI, a REST API, a dashboard, and tests.

— Tobiloba Jagun
