"""NetPulse CLI -- ISP performance tracker.

Commands:
    python main.py once                 Run one measurement cycle
    python main.py watch --interval 30  Run a cycle every N minutes forever
    python main.py export               Export all data to CSV
    python main.py demo                 Seed the DB with 14 days of fake data
    python main.py serve                Start the dashboard on localhost:5000
"""

import argparse
import csv
import math
import random
import time
from datetime import datetime, timedelta

import db


def cmd_once(_args):
    import logger

    print("Running measurement cycle...")
    result = logger.run_cycle()
    if result["status"] == "ok":
        print(
            f"OK  {result['download_mbps']} Mbps down / {result['upload_mbps']} Mbps up, "
            f"ping {result['ping_cloudflare_ms']} ms (1.1.1.1)"
        )
    else:
        print(f"OUTAGE recorded: {result['reason']}")


def cmd_watch(args):
    import logger

    interval_s = args.interval * 60
    print(f"Watching: one cycle every {args.interval} minute(s). Ctrl+C to stop.")
    while True:
        try:
            result = logger.run_cycle()
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {result['status']}")
        except Exception as exc:
            print(f"Cycle error (continuing): {exc}")
        time.sleep(interval_s)


def cmd_export(_args):
    measurements = db.get_measurements()
    outages = db.get_outages()

    with open("netpulse_measurements.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["id", "timestamp", "download_mbps", "upload_mbps",
             "ping_cloudflare_ms", "loss_cloudflare_pct",
             "ping_google_ms", "loss_google_pct"]
        )
        for m in measurements:
            writer.writerow([m[k] for k in
                             ("id", "timestamp", "download_mbps", "upload_mbps",
                              "ping_cloudflare_ms", "loss_cloudflare_pct",
                              "ping_google_ms", "loss_google_pct")])

    with open("netpulse_outages.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "timestamp", "reason"])
        for o in outages:
            writer.writerow([o["id"], o["timestamp"], o["reason"]])

    print(f"Exported {len(measurements)} measurements -> netpulse_measurements.csv")
    print(f"Exported {len(outages)} outages -> netpulse_outages.csv")


def cmd_demo(_args):
    """Seed 14 days of realistic fake data: a cycle every 30 minutes,
    speeds that dip in evening peak hours, and a few outages."""
    random.seed(42)
    db.init_db()

    start = datetime.now() - timedelta(days=14)
    ts = start.replace(minute=0, second=0, microsecond=0)
    count_m = count_o = 0

    # Pre-pick a few outage windows (start time, duration in cycles)
    outage_windows = []
    for _ in range(4):
        o_start = start + timedelta(hours=random.uniform(5, 14 * 24 - 5))
        outage_windows.append((o_start, random.randint(1, 4)))

    while ts <= datetime.now():
        in_outage = any(
            o_start <= ts < o_start + timedelta(minutes=30 * dur)
            for o_start, dur in outage_windows
        )
        if in_outage:
            db.insert_outage(ts, "Simulated outage (demo data)")
            count_o += 1
        else:
            hour = ts.hour
            # Base ~55 Mbps, dips in the 19:00-23:00 peak, best overnight
            peak_factor = 1.0 - 0.45 * math.exp(-((hour - 21) % 24 - 0) ** 2 / 8)
            night_bonus = 1.15 if 1 <= hour <= 6 else 1.0
            download = 55 * peak_factor * night_bonus * random.uniform(0.85, 1.15)
            upload = download * random.uniform(0.18, 0.28)
            ping = random.uniform(12, 25) * (1.6 if 19 <= hour <= 23 else 1.0)
            loss = random.choices([0.0, 0.0, 0.0, 10.0, 20.0], weights=[70, 15, 10, 3, 2])[0]
            db.insert_measurement({
                "timestamp": ts,
                "download_mbps": round(download, 2),
                "upload_mbps": round(upload, 2),
                "ping_cloudflare_ms": round(ping, 1),
                "loss_cloudflare_pct": loss,
                "ping_google_ms": round(ping * random.uniform(0.95, 1.25), 1),
                "loss_google_pct": loss,
            })
            count_m += 1
        ts += timedelta(minutes=30)

    print(f"Demo data seeded: {count_m} measurements, {count_o} outages over 14 days.")


def cmd_serve(_args):
    from dashboard import app

    print("NetPulse dashboard: http://localhost:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)


def main():
    parser = argparse.ArgumentParser(prog="netpulse", description="ISP performance tracker")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("once", help="Run one measurement cycle")

    watch = sub.add_parser("watch", help="Run a cycle every N minutes forever")
    watch.add_argument("--interval", type=int, default=30, help="Minutes between cycles (default 30)")

    sub.add_parser("export", help="Export all data to CSV")
    sub.add_parser("demo", help="Seed the DB with 14 days of fake data")
    sub.add_parser("serve", help="Start the dashboard on localhost:5000")

    args = parser.parse_args()
    {"once": cmd_once, "watch": cmd_watch, "export": cmd_export,
     "demo": cmd_demo, "serve": cmd_serve}[args.command](args)


if __name__ == "__main__":
    main()
