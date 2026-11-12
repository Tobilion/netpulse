"""Cloudflare-edge fallback source.

Used when the primary engine is rate-limited and speedtest.net cannot
offer a server in the home country (it geolocates some Nigerian
connections to Europe and only serves UK/DE/NL servers).

Cloudflare's speed-test endpoints are a separate operator from Ookla, so
Ookla's usage limit does not apply, and the edge reached from Lagos is
Cloudflare's Lagos PoP -- a genuinely local path.

Nothing here is simulated: bytes are actually transferred and timed.
"""

import time
import urllib.request

from sources_base import home_country

TRACE_URL = "https://speed.cloudflare.com/cdn-cgi/trace"
DOWN_URL = "https://speed.cloudflare.com/__down?bytes={bytes}"
UP_URL = "https://speed.cloudflare.com/__up"

DEFAULT_DOWNLOAD_BYTES = 20_000_000
DEFAULT_UPLOAD_BYTES = 2_000_000
TIMEOUT_SECONDS = 120
RETRIES = 2


class CloudflareError(RuntimeError):
    """The Cloudflare fallback could not complete a measurement."""

# Cloudflare point-of-presence codes -> the city they sit in. Only the
# common ones are listed; anything else falls back to the code itself.
COLO_CITIES = {
    "LOS": "Lagos, Nigeria", "ABJ": "Abuja, Nigeria", "ACC": "Accra, Ghana",
    "CPT": "Cape Town, South Africa", "JNB": "Johannesburg, South Africa",
    "NBO": "Nairobi, Kenya", "DKR": "Dakar, Senegal",
    "LHR": "London, United Kingdom", "CDG": "Paris, France",
    "AMS": "Amsterdam, Netherlands", "FRA": "Frankfurt, Germany",
    "BER": "Berlin, Germany", "MUC": "Munich, Germany",
    "HAM": "Hamburg, Germany", "MAD": "Madrid, Spain",
    "BCN": "Barcelona, Spain", "LIS": "Lisbon, Portugal",
    "DUB": "Dublin, Ireland", "MXP": "Milan, Italy", "FCO": "Rome, Italy",
    "ZRH": "Zurich, Switzerland", "VIE": "Vienna, Austria",
    "WAW": "Warsaw, Poland", "PRG": "Prague, Czechia",
    "CPH": "Copenhagen, Denmark", "OSL": "Oslo, Norway",
    "HEL": "Helsinki, Finland", "ARN": "Stockholm, Sweden",
    "IST": "Istanbul, Turkey", "ATH": "Athens, Greece",
    "TLV": "Tel Aviv, Israel", "DXB": "Dubai, United Arab Emirates",
    "BOM": "Mumbai, India", "DEL": "Delhi, India",
    "BLR": "Bangalore, India", "MAA": "Chennai, India",
    "CCU": "Kolkata, India", "SIN": "Singapore",
    "KUL": "Kuala Lumpur, Malaysia", "BKK": "Bangkok, Thailand",
    "CGK": "Jakarta, Indonesia", "MNL": "Manila, Philippines",
    "HKG": "Hong Kong", "NRT": "Tokyo, Japan", "KIX": "Osaka, Japan",
    "ICN": "Seoul, South Korea", "SYD": "Sydney, Australia",
    "MEL": "Melbourne, Australia", "AKL": "Auckland, New Zealand",
    "GRU": "Sao Paulo, Brazil", "EZE": "Buenos Aires, Argentina",
    "SCL": "Santiago, Chile", "DFW": "Dallas, United States",
    "IAD": "Ashburn, United States", "JFK": "New York, United States",
    "ORD": "Chicago, United States", "LAX": "Los Angeles, United States",
    "SJC": "San Jose, United States", "SEA": "Seattle, United States",
    "YYZ": "Toronto, Canada",
}


def colo_place(colo):
    """Human-readable place for a Cloudflare PoP code."""
    return COLO_CITIES.get((colo or "").upper(), colo or "unknown")



def _fetch_trace(timeout=15):
    """Return the edge info (colo, country) from Cloudflare's trace."""
    req = urllib.request.Request(TRACE_URL, headers={"User-Agent": "netpulse/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", "ignore")
    info = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            info[key.strip()] = value.strip()
    return info


def measure_download(target_bytes=DEFAULT_DOWNLOAD_BYTES, timeout=TIMEOUT_SECONDS):
    """Download bytes and return (mbps, seconds, bytes).

    Retried once: the edge occasionally resets a connection mid-transfer.
    """
    url = DOWN_URL.format(bytes=target_bytes)
    last_error = None
    for attempt in range(RETRIES):
        req = urllib.request.Request(url, headers={"User-Agent": "netpulse/1.0"})
        start = time.monotonic()
        total = 0
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                while total < target_bytes:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
        except Exception as exc:
            last_error = exc
            if attempt + 1 < RETRIES:
                time.sleep(1)
                continue
            raise CloudflareError(f"download failed: {exc}") from exc
        elapsed = time.monotonic() - start
        if elapsed <= 0 or total <= 0:
            last_error = "no data returned"
            continue
        mbps = total * 8.0 / elapsed / 1_000_000
        return round(mbps, 2), round(elapsed, 3), total
    raise CloudflareError(f"download failed: {last_error}")


def measure_upload(target_bytes=DEFAULT_UPLOAD_BYTES, timeout=TIMEOUT_SECONDS):
    """Upload bytes and return (mbps, seconds, bytes).

    The endpoint is markedly faster when the body is sent as
    application/octet-stream, and it occasionally resets the connection,
    so this retries once.
    """
    payload = b"0" * target_bytes
    last_error = None
    for attempt in range(RETRIES):
        req = urllib.request.Request(
            UP_URL, data=payload, method="POST",
            headers={"User-Agent": "netpulse/1.0",
                     "Content-Type": "application/octet-stream"},
        )
        start = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp.read(1024)
        except Exception as exc:
            last_error = exc
            if attempt + 1 < RETRIES:
                time.sleep(1)
                continue
            raise CloudflareError(f"upload failed: {exc}") from exc
        elapsed = time.monotonic() - start
        if elapsed <= 0:
            last_error = "upload timing failed"
            continue
        mbps = target_bytes * 8.0 / elapsed / 1_000_000
        return round(mbps, 2), round(elapsed, 3), target_bytes
    raise CloudflareError(f"upload failed: {last_error}")


def measure_latency(timeout=15):
    """Time to the first byte of a small request (ms)."""
    req = urllib.request.Request(
        DOWN_URL.format(bytes=0), headers={"User-Agent": "netpulse/1.0"}
    )
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(1)
    except Exception as exc:
        raise CloudflareError(f"latency probe failed: {exc}") from exc
    return round((time.monotonic() - start) * 1000, 1)


class CloudflareLiveSource:
    """Live source that measures against the nearest Cloudflare edge."""

    def __init__(self, download_bytes=DEFAULT_DOWNLOAD_BYTES,
                 upload_bytes=DEFAULT_UPLOAD_BYTES):
        self.download_bytes = download_bytes
        self.upload_bytes = upload_bytes
        self.name = "cloudflare-edge"

    def run(self, on_progress=None, should_cancel=None):
        def emit(event):
            if on_progress:
                on_progress(event)

        def cancelled():
            return bool(should_cancel and should_cancel())

        try:
            info = _fetch_trace()
        except Exception as exc:
            raise CloudflareError(f"edge lookup failed: {exc}") from exc

        colo = (info.get("colo") or "?").upper()
        loc = (info.get("loc") or "").strip()
        # Name where the measurement actually happened: the edge PoP, not
        # the client's country (they differ when the path leaves Nigeria).
        place = colo_place(colo)
        server_label = f"Cloudflare {colo} ({place})"
        engine_label = f"cloudflare-edge {colo}"

        emit({"phase": "ping", "ping_ms": None})
        try:
            latency_ms = measure_latency()
        except CloudflareError:
            latency_ms = None
        emit({"phase": "ping", "ping_ms": latency_ms})

        if cancelled():
            return None

        emit({"phase": "download"})
        download_mbps, download_s, _bytes = measure_download(self.download_bytes)
        emit({"phase": "download", "download_mbps": download_mbps})

        if cancelled():
            return None

        emit({"phase": "upload"})
        upload_mbps, upload_s, _bytes = measure_upload(self.upload_bytes)
        emit({"phase": "upload", "upload_mbps": upload_mbps})

        return {
            "download_mbps": download_mbps,
            "upload_mbps": upload_mbps,
            "client": None,
            "server": server_label,
            "engine": engine_label,
            "ping_ms": latency_ms,
            "jitter_ms": None,
            "detail": (f"Cloudflare edge {colo} ({loc}); "
                       f"download {download_s}s, upload {upload_s}s"),
        }
