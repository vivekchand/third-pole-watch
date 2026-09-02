"""Publish watch status + ledger to the third-pole-watch-data repo.

Git is the transport on purpose: every published status is a commit, so the
public record of what the watch claimed, and when, is tamper-evident and
free to audit. The site reads status.json from the raw URL of this branch.

Configuration (env):
  TPW_DATA_REMOTE  push URL for the repo, with credentials, e.g.
                   git@github.com:vivekchand/third-pole-watch-data.git
                   (SSH deploy key with write access on the DATA repo only)
  TPW_DATA_DIR     local checkout dir (default ~/.thirdpole/data-repo)

If TPW_DATA_REMOTE is unset, publishing is a silent no-op — the watch and
its Telegram alerts work fine without it.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from . import ledger

log = logging.getLogger("thirdpole.publisher")

BRANCH = "data"


def _remote() -> str:
    return os.environ.get("TPW_DATA_REMOTE", "")


def _data_dir() -> Path:
    return Path(os.environ.get("TPW_DATA_DIR",
                               Path.home() / ".thirdpole" / "data-repo"))


def enabled() -> bool:
    return bool(_remote())


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True, timeout=120)


def _ensure_checkout() -> Path:
    p = _data_dir()
    if not (p / ".git").exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--branch", BRANCH, "--single-branch",
             "--depth", "1", _remote(), str(p)],
            check=True, capture_output=True, text=True, timeout=300)
    return p


LIVE_WINDOW_S = 600     # waveform snapshot length
LIVE_POINTS = 300       # envelope bins per station (2 s/bin)


def live_payload(traces, now: float | None = None) -> dict:
    """Downsampled absolute-envelope snapshot of the freshest traces.

    Small enough to commit every publish (~a few KB), detailed enough that
    the site can draw real seismograms — the ground actually moving.
    """
    import numpy as np
    now = now or time.time()
    stations = []
    for tr in sorted(traces, key=lambda t: -t.stats.endtime.timestamp)[:8]:
        sr = tr.stats.sampling_rate
        n = int(LIVE_WINDOW_S * sr)
        data = np.abs(np.asarray(tr.data[-n:], dtype=float))
        if len(data) < LIVE_POINTS:
            continue
        bins = np.array_split(data, LIVE_POINTS)
        env = np.array([b.max() for b in bins])
        peak = float(env.max()) or 1.0
        stations.append({
            "id": f"{tr.stats.network}.{tr.stats.station}",
            "age_s": round(now - tr.stats.endtime.timestamp),
            "bin_s": round(LIVE_WINDOW_S / LIVE_POINTS, 1),
            "peak": peak,
            "env": [round(float(v) / peak, 3) for v in env],
        })
    return {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now)),
            "window_s": LIVE_WINDOW_S, "stations": stations}


def publish(traces=None) -> bool:
    """Write status.json (+ live.json + ledger) and push. True on push."""
    if not enabled():
        return False
    try:
        p = _ensure_checkout()
        # sync before writing: tolerate external commits to the data repo
        # (e.g. README edits) that would otherwise reject our next push
        try:
            _git(["fetch", "-q", "origin", BRANCH], p)
            _git(["reset", "--hard", f"origin/{BRANCH}"], p)
        except Exception:  # noqa: BLE001 - wedged checkout gets a fresh clone
            shutil.rmtree(p)
            p = _ensure_checkout()
        stats = ledger.stats()
        stats["generated_at"] = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
        # data freshness, distinct from publish freshness: a daemon that
        # heartbeats with hours-old buffers is deaf, not healthy
        stats["data_age_s"] = (
            round(time.time() - max(tr.stats.endtime.timestamp
                                    for tr in traces)) if traces else None)
        (p / "status.json").write_text(json.dumps(stats, indent=2) + "\n")
        if traces:
            (p / "live.json").write_text(
                json.dumps(live_payload(traces)) + "\n")
        if ledger.LEDGER_PATH.exists():
            shutil.copy(ledger.LEDGER_PATH, p / "ledger.jsonl")

        _git(["add", "-A"], p)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=p)
        if diff.returncode == 0:
            return False  # nothing changed
        _git(["-c", "user.name=tpw-watch",
              "-c", "user.email=watch@thirdpole.watch",
              "commit", "-m", f"status {stats['generated_at']}"], p)
        _git(["push", "origin", BRANCH], p)
        log.info("published status (%s candidates)", stats["candidates"])
        return True
    except Exception as exc:  # noqa: BLE001 - publishing must never kill the watch
        log.error("publish failed: %s", exc)
        return False
