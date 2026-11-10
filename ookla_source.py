"""Ookla CLI live source (JSON-lines progress) + binary discovery.

Parses JSONL in ookla_parse.py; the Python fallback source lives in
live_sampler.py. Fallback happens only before a test starts.
"""

import os
import queue
import re
import shutil
import subprocess
import threading
import time

from ookla_parse import (
    labels_from_test_start,
    ookla_progress_event,
    parse_ookla_line,
    result_to_final,
)
from sources_base import LiveDataSource, PartialTestError, PreStartError, watchdog_seconds

WINGET_OOKLA_PATH = (
    r"C:\Users\tobil\AppData\Local\Microsoft\WinGet\Packages"
    r"\Ookla.Speedtest.CLI_Microsoft.Winget.Source_8wekyb3d8bbwe\speedtest.exe"
)


def mask_ip(text):
    """Mask an IPv4 address: 203.0.113.45 -> 203.0.113.•••."""
    if not text:
        return text
    return re.sub(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.)\d{1,3}\b", r"\1•••", str(text))


def find_ookla_binary():
    """Locate the Ookla CLI binary.

    Order: NETPULSE_OOKLA_PATH, shutil.which("speedtest"), then the
    known winget path. The Python speedtest-cli shim (venv speedtest.exe)
    and any non-Ookla "speedtest" are rejected via --version output.
    """
    candidates = []
    env_path = os.environ.get("NETPULSE_OOKLA_PATH")
    if env_path:
        candidates.append(env_path)
    found = shutil.which("speedtest")
    if found:
        candidates.append(found)
    if os.path.exists(WINGET_OOKLA_PATH):
        candidates.append(WINGET_OOKLA_PATH)
    for cand in candidates:
        if cand and os.path.exists(cand) and _is_ookla_binary(cand):
            return cand
    return None


def _is_ookla_binary(path):
    """True when ``path --version`` identifies itself as Ookla."""
    try:
        proc = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    out = (proc.stdout or "") + (proc.stderr or "")
    return "ookla" in out.lower()


def ookla_version(path):
    """Short version string like 'ookla-cli 1.2.0.84', or None."""
    try:
        proc = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = (proc.stdout or "") + (proc.stderr or "")
    match = re.search(r"(\d+\.\d+\.\d+(?:\.\d+)?)", out)
    return f"ookla-cli {match.group(1)}" if match else "ookla-cli"


def kill_process_tree(proc):
    """Best-effort kill of the child tree; never leave orphans."""
    if proc.poll() is not None:
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


class OoklaLiveSource(LiveDataSource):
    """Ookla CLI source: `speedtest --format=jsonl --progress=yes`.

    --accept-license is passed so a fresh machine accepts on first run;
    acceptance persists after that. --accept-gdpr is deliberately not
    passed (no GDPR prompt was observed for this connection).

    Real shapes seen on 2026-11-07 (speedtest 1.2.0.84, Lagos):
      testStart / ping / download / upload / result / log (see ookla_parse.py).
    ``bandwidth`` is bytes/sec; Mbps = bandwidth * 8 / 1e6.
    """

    def __init__(self, binary=None):
        self._binary = binary or find_ookla_binary()
        self.name = "ookla-cli (version unknown)"
        if self._binary:
            ver = ookla_version(self._binary)
            if ver:
                self.name = ver

    @property
    def STALL_SECONDS(self):
        return watchdog_seconds("NETPULSE_STALL_SECONDS", 30)

    @property
    def MAX_RUNTIME_SECONDS(self):
        return watchdog_seconds("NETPULSE_MAX_JOB_SECONDS", 150)

    def run(self, on_progress=None, should_cancel=None):
        binary = self._binary or find_ookla_binary()
        if not binary:
            raise PreStartError("Ookla CLI binary not found")

        def emit(event):
            if on_progress:
                on_progress(event)

        def cancelled():
            return bool(should_cancel and should_cancel())

        cmd = [binary, "--format=jsonl", "--progress=yes", "--accept-license"]
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
            )
        except OSError as exc:
            raise PreStartError(f"Cannot start Ookla CLI: {exc}") from exc

        lines = queue.Queue()
        stderr_lines = []

        def reader():
            assert proc.stdout is not None
            try:
                for line in proc.stdout:
                    lines.put(line)
            except Exception:
                pass
            lines.put(None)

        def err_reader():
            assert proc.stderr is not None
            try:
                for line in proc.stderr:
                    stderr_lines.append(line)
            except Exception:
                pass

        threading.Thread(target=reader, daemon=True).start()
        threading.Thread(target=err_reader, daemon=True).start()

        client_label = server_label = None
        final = None
        seen_progress = False
        last_download_mbps = None
        last_upload_mbps = None
        last_loaded_latency_ms = None
        log_events = []
        started = time.monotonic()
        last_line_at = started
        cancelled_result = False
        stall_reason = None
        try:
            while True:
                if cancelled():
                    kill_process_tree(proc)
                    cancelled_result = True
                    break
                now = time.monotonic()
                if now - started > self.MAX_RUNTIME_SECONDS:
                    kill_process_tree(proc)
                    stall_reason = f"Watchdog: test exceeded {self.MAX_RUNTIME_SECONDS}s max runtime"
                    break
                if now - last_line_at > self.STALL_SECONDS:
                    kill_process_tree(proc)
                    stall_reason = f"Watchdog: no progress for {self.STALL_SECONDS}s"
                    break
                try:
                    line = lines.get(timeout=0.25)
                except queue.Empty:
                    continue
                if line is None:
                    break
                last_line_at = time.monotonic()
                event = parse_ookla_line(line)
                if event is None:
                    continue
                kind = event.get("type")
                if kind == "testStart":
                    client_label, server_label = labels_from_test_start(event)
                elif kind == "log":
                    msg = event.get("message")
                    if msg:
                        log_events.append(str(msg))
                elif kind in ("ping", "download", "upload"):
                    seen_progress = True
                    prog = ookla_progress_event(event)
                    if kind == "download":
                        last_download_mbps = prog.get("download_mbps")
                    elif kind == "upload":
                        last_upload_mbps = prog.get("upload_mbps")
                    if prog.get("loaded_latency_ms") is not None:
                        last_loaded_latency_ms = prog["loaded_latency_ms"]
                    emit(prog)
                elif kind == "result":
                    final = result_to_final(event, client_label, server_label, self.name)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                kill_process_tree(proc)
        finally:
            kill_process_tree(proc)
            try:
                proc.wait(timeout=2)
            except Exception:
                pass

        if cancelled_result:
            return None
        detail_bits = []
        if log_events:
            detail_bits.append(" | ".join(log_events[-3:]))
        err_text = "".join(stderr_lines).strip()
        if err_text:
            detail_bits.append(err_text[-500:])
        detail = " ".join(detail_bits).strip()

        def _partial():
            return {
                "download_mbps": round(last_download_mbps, 2)
                if last_download_mbps is not None else None,
                "upload_mbps": round(last_upload_mbps, 2)
                if last_upload_mbps is not None else None,
                "client": client_label,
                "server": server_label,
                "engine": self.name,
                "detail": detail or None,
                "server_loaded_ms": last_loaded_latency_ms,
                "server_target": server_label,
            }

        if stall_reason:
            if seen_progress:
                raise PartialTestError(stall_reason, _partial())
            raise RuntimeError(stall_reason)
        if proc.returncode not in (0, None):
            if not seen_progress and final is None:
                raise PreStartError(
                    f"Ookla CLI failed before start (rc={proc.returncode})"
                    + (f": {detail}" if detail else "")
                )
            if final is None:
                msg = f"Ookla CLI failed mid-test (rc={proc.returncode})"
                if detail:
                    msg += f": {detail}"
                raise PartialTestError(msg, _partial())
        if final is None:
            if not seen_progress:
                raise PreStartError("Ookla CLI produced no progress events")
            msg = "Ookla CLI finished without a result event"
            if detail:
                msg += f": {detail}"
            raise PartialTestError(msg, _partial())
        return final
