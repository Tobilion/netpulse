"""One measurement cycle for NetPulse.

Runs a speed test (speedtest-cli) and pings 1.1.1.1 and 8.8.8.8.
If everything fails, records an outage instead of crashing.
"""

import platform
import re
import subprocess
from datetime import datetime

import db

PING_TARGETS = {
    "cloudflare": "1.1.1.1",
    "google": "8.8.8.8",
}
PING_COUNT = 10


def run_ping(host, count=PING_COUNT):
    """Ping a host. Returns (avg_latency_ms, packet_loss_pct) or (None, 100.0) on failure."""
    is_windows = platform.system().lower() == "windows"
    count_flag = "-n" if is_windows else "-c"
    cmd = ["ping", count_flag, str(count), host]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=count * 3 + 15
        )
        output = result.stdout
    except (subprocess.TimeoutExpired, OSError):
        return None, 100.0

    loss_match = re.search(r"(\d+(?:\.\d+)?)% (?:packet )?loss", output)
    loss = float(loss_match.group(1)) if loss_match else 100.0

    avg = None
    # Linux/macOS: "rtt min/avg/max/mdev = 9.1/10.2/12.3/0.5 ms"
    unix_match = re.search(r"= [\d.]+/([\d.]+)/", output)
    if unix_match:
        avg = float(unix_match.group(1))
    else:
        # Windows: "Average = 23ms"
        win_match = re.search(r"Average = (\d+)ms", output)
        if win_match:
            avg = float(win_match.group(1))

    return avg, loss


def run_speed_test():
    """Run a speed test. Returns (download_mbps, upload_mbps). Raises on failure."""
    import speedtest  # imported lazily: the package is slow to import

    st = speedtest.Speedtest()
    st.get_best_server()
    download = st.download() / 1_000_000  # bits/s -> Mbps
    upload = st.upload() / 1_000_000
    return round(download, 2), round(upload, 2)


def run_cycle(db_path=db.DEFAULT_DB_PATH):
    """Run one full measurement cycle and store the result.

    Returns a dict describing what was recorded.
    """
    timestamp = datetime.now()

    pings = {}
    for name, host in PING_TARGETS.items():
        avg, loss = run_ping(host)
        pings[name] = {"avg": avg, "loss": loss}

    network_down = all(p["avg"] is None or p["loss"] >= 100 for p in pings.values())

    download = upload = None
    speed_error = None
    if not network_down:
        try:
            download, upload = run_speed_test()
        except Exception as exc:  # speedtest-cli raises various exception types
            speed_error = f"{type(exc).__name__}: {exc}"

    if network_down:
        db.insert_outage(timestamp, "Network unreachable (all pings failed)", db_path=db_path)
        return {"status": "outage", "reason": "network down", "timestamp": timestamp}

    if download is None:
        db.insert_outage(timestamp, f"Speed test failed: {speed_error}", db_path=db_path)
        return {"status": "outage", "reason": speed_error, "timestamp": timestamp}

    data = {
        "timestamp": timestamp,
        "download_mbps": download,
        "upload_mbps": upload,
        "ping_cloudflare_ms": pings["cloudflare"]["avg"],
        "loss_cloudflare_pct": pings["cloudflare"]["loss"],
        "ping_google_ms": pings["google"]["avg"],
        "loss_google_pct": pings["google"]["loss"],
    }
    db.insert_measurement(data, db_path=db_path)
    return {"status": "ok", **data}
