"""Shared base classes for live speed-test sources."""

import os


class PreStartError(RuntimeError):
    """Source failed before any test progress was emitted."""


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
