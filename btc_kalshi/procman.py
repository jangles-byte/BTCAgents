"""btc_kalshi.procman — start/stop the agent loop as a child process so the
dashboard's 'Run System' button can control it. Tracks a pidfile + log so state
survives across dashboard restarts."""
from __future__ import annotations

import os
import signal
import subprocess
import sys

from . import config as cfg

ROOT = cfg.PROJECT_ROOT
_DATA = ROOT / "btc_kalshi" / "data"
PIDFILE = _DATA / "runner.pid"
LOG = _DATA / "runner.log"


def _read_pid():
    try:
        return int(PIDFILE.read_text().strip())
    except Exception:
        return None


def is_running() -> bool:
    pid = _read_pid()
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def start_runner(interval: int = 60) -> dict:
    if is_running():
        return {"ok": True, "running": True, "pid": _read_pid(), "note": "already running"}
    _DATA.mkdir(parents=True, exist_ok=True)
    logf = open(LOG, "a")
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    p = subprocess.Popen(
        [sys.executable, "-m", "btc_kalshi.runner", "--interval", str(interval)],
        cwd=str(ROOT), stdout=logf, stderr=subprocess.STDOUT, start_new_session=True, env=env)
    PIDFILE.write_text(str(p.pid))
    return {"ok": True, "running": True, "pid": p.pid}


def stop_runner() -> dict:
    pid = _read_pid()
    if pid:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except Exception:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
    try:
        PIDFILE.unlink()
    except Exception:
        pass
    return {"ok": True, "running": False}


def status() -> dict:
    return {"running": is_running(), "pid": _read_pid()}


def tail_log(n: int = 50) -> list:
    try:
        return LOG.read_text().splitlines()[-n:]
    except Exception:
        return []
