"""Shared base classes for live speed-test sources."""

import os


class PreStartError(RuntimeError):
    """Source failed before any test progress was emitted."""


class ForeignServerError(PreStartError):
    """The only available server is outside the home country.

    Measuring to another country measures that country, not this link, so
    the cycle is skipped instead of storing a misleading row.
    """


class RateLimitedError(PreStartError):
    """The engine refused to run because a usage limit was reached."""

    def __init__(self, message, retry_after_seconds=None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class SkippedRun(Exception):
    """The cycle was deliberately skipped (not a measurement, not an outage)."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class PartialTestError(RuntimeError):
    """Test failed after some progress; carries partial results."""

    def __init__(self, message, partial):
        super().__init__(message)
        self.partial = partial


def watchdog_seconds(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def home_country():
    """The country this connection is in; fallbacks must stay inside it."""
    return (os.environ.get("NETPULSE_HOME_COUNTRY") or "Nigeria").strip().lower()


# ISO 3166-1 alpha-2 codes for the countries we can name directly.
COUNTRY_CODES = {
    "nigeria": "NG", "ghana": "GH", "kenya": "KE", "south africa": "ZA",
    "united kingdom": "GB", "united states": "US", "india": "IN",
    "canada": "CA", "germany": "DE", "netherlands": "NL", "spain": "ES",
    "israel": "IL", "france": "FR", "brazil": "BR", "nigeria ": "NG",
}


def home_country_code():
    """ISO code for the home country (e.g. Nigeria -> NG)."""
    return COUNTRY_CODES.get(home_country(), home_country()[:2].upper())


def country_name(code):
    """Country name for an ISO code, falling back to the code itself."""
    code = (code or "").strip()
    if not code:
        return code
    for name, iso in COUNTRY_CODES.items():
        if iso == code.upper():
            return name.title()
    return code


def server_country(label):
    """Country from a server label like 'Melbicom (Lagos, Nigeria)'."""
    if not label or "(" not in label:
        return None
    inner = label[label.rfind("(") + 1: label.rfind(")")] if ")" in label else ""
    parts = [p.strip() for p in inner.split(",")]
    return parts[-1].lower() if parts and parts[-1] else None


def server_is_local(label):
    """True when a server is in the home country (so the path is realistic)."""
    country = server_country(label)
    if country is None:
        return False
    return country == home_country()


class LiveDataSource:
    """Interface for a live speed-test source.

    run() blocks until the test finishes and returns:
        {"download_mbps": float, "upload_mbps": float,
         "client": str|None, "server": str|None, "engine": str}
    It calls on_progress(dict) as real samples become available and
    returns None when should_cancel() becomes true.
    """

    name = "unknown"

    def run(self, on_progress=None, should_cancel=None):
        raise NotImplementedError
