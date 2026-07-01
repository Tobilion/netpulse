# NetPulse

**Track how your ISP *actually* performs — not what they promise.**

NetPulse logs your internet connection's real performance over time — download/upload speed, latency, packet loss, and outages — into a local SQLite database, and visualizes everything in a clean dark-themed web dashboard.

## Screenshots

*(placeholder — add screenshots of the dashboard here)*

## Features

NetPulse runs a full measurement cycle on demand or on a schedule: a speed test via speedtest.net, plus 10 pings each to Cloudflare (1.1.1.1) and Google (8.8.8.8) DNS. If the network is down or the speed test fails, the cycle is recorded as an outage instead of crashing — so gaps in your connection become data, not lost data. The dashboard shows speed and latency over time, uptime percentage, averages, an hour-of-day speed profile (great for spotting evening congestion), and a date-range filter (24h / 7d / 30d / all).

## Setup (Windows)

Requires Python 3.9+. In PowerShell or Command Prompt:

```
cd netpulse
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

```
python main.py once                  # run one measurement cycle
python main.py watch --interval 30   # run a cycle every 30 minutes, forever
python main.py serve                 # dashboard at http://localhost:5000
python main.py export                # export all data to CSV
python main.py demo                  # seed 14 days of fake data (to preview the dashboard)
```

A typical setup: schedule `once` to run every 30 minutes (see below), and open the dashboard whenever you want to check on your ISP.

## Scheduling with Windows Task Scheduler

To log measurements automatically every 30 minutes:

1. Press `Win + R`, type `taskschd.msc`, press Enter.
2. In the right panel, click **Create Task…** (not "Create Basic Task").
3. **General tab:** name it `NetPulse Logger`. Check **Run whether user is logged on or not** if you want it running in the background.
4. **Triggers tab:** click **New…** → Begin the task **On a schedule** → **Daily** → under Advanced settings, check **Repeat task every** and set it to **30 minutes** for a duration of **Indefinitely** → OK.
5. **Actions tab:** click **New…** → Action: **Start a program**.
   - Program/script: full path to your venv Python, e.g. `C:\Users\you\netpulse\venv\Scripts\python.exe`
   - Add arguments: `main.py once`
   - Start in: the full path to the `netpulse` folder, e.g. `C:\Users\you\netpulse`
6. **Conditions tab:** uncheck **Start the task only if the computer is on AC power** (otherwise it stops on battery).
7. Click **OK**, enter your Windows password if prompted, and you're done. Right-click the task → **Run** to test it.

## Project structure

```
netpulse/
├── main.py               # CLI entry point (once / watch / export / demo / serve)
├── logger.py             # one measurement cycle: speed test + pings
├── db.py                 # SQLite storage layer
├── dashboard.py          # Flask app + JSON API
├── templates/
│   └── dashboard.html    # dark-themed dashboard (Chart.js via CDN)
├── tests/
│   └── test_db.py        # pytest suite for the db module
├── requirements.txt
└── netpulse.db           # created on first run
```

## Running the tests

```
pip install pytest
python -m pytest tests/ -v
```

## Why I built this

I live in Lagos, and like many people here I pay for an internet plan whose advertised speed and my actual experience often feel like two different products. Rather than arguing from vibes, I wanted numbers: how fast is my connection really, at what times of day does it degrade, and how often does it go down entirely? NetPulse gives me that evidence — and it was a fun way to practice building a complete small system: data collection, storage, a CLI, a REST API, a dashboard, and tests.

— Tobiloba Jagun
