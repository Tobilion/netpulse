"""Ookla JSONL parsing (extracted from live_sampler.py).

Covers the real shapes seen with speedtest 1.2.0.84 (Lagos, 2026-11-07):
testStart / ping / download / upload / result / log. Bandwidth is
bytes/sec; Mbps = bandwidth * 8 / 1e6.
"""

import json


def parse_ookla_line(line):
    line = (line or "").strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict) or "type" not in obj:
        return None
    return obj


def bandwidth_to_mbps(bandwidth_bps):
    if bandwidth_bps is None:
        return None
    return round(float(bandwidth_bps) * 8.0 / 1_000_000, 3)


def labels_from_test_start(event):
    import re

    def mask(text):
        return re.sub(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.)\d{1,3}\b", r"\1•••", str(text or ""))

    isp = event.get("isp") or "Unknown ISP"
    iface = event.get("interface") or {}
    server = event.get("server") or {}
    client = mask(f"{isp} · {iface.get('externalIp') or '?'}")
    name = server.get("name") or "Unknown host"
    location = server.get("location") or "?"
    country = server.get("country") or "?"
    return client, f"{name} ({location}, {country})"


def ookla_progress_event(event):
    kind = event.get("type")
    if kind == "ping":
        ping = event.get("ping") or {}
        return {"phase": "ping", "ping_ms": ping.get("latency"),
                "jitter_ms": ping.get("jitter")}
    payload = event.get(kind) or {}
    mbps = bandwidth_to_mbps(payload.get("bandwidth"))
    # Ookla reports loaded latency to the test server as latency.iqm.
    latency = payload.get("latency") or {}
    loaded_ms = latency.get("iqm")
    if kind == "download":
        return {"phase": "download", "download_mbps": mbps, "upload_mbps": None,
                "loaded_latency_ms": loaded_ms}
    return {"phase": "upload", "download_mbps": None, "upload_mbps": mbps,
            "loaded_latency_ms": loaded_ms}


def result_to_final(event, client_label, server_label, engine_name):
    download = event.get("download") or {}
    upload = event.get("upload") or {}
    ping = event.get("ping") or {}
    if client_label is None or server_label is None:
        test_event = {"isp": event.get("isp"),
                      "interface": event.get("interface"),
                      "server": event.get("server")}
        c2, s2 = labels_from_test_start(test_event)
        client_label = client_label or c2
        server_label = server_label or s2
    download_mbps = bandwidth_to_mbps(download.get("bandwidth"))
    upload_mbps = bandwidth_to_mbps(upload.get("bandwidth"))
    return {
        "download_mbps": round(download_mbps, 2) if download_mbps is not None else None,
        "upload_mbps": round(upload_mbps, 2) if upload_mbps is not None else None,
        "client": client_label,
        "server": server_label,
        "engine": engine_name,
        "ping_ms": ping.get("latency"),
        "jitter_ms": ping.get("jitter"),
    }
