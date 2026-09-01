"""Publish watch status + ledger to the repo's `data` branch.

Git is the transport on purpose: every published status is a commit, so the
public record of what the watch claimed, and when, is tamper-evident and
free to audit. The site reads status.json from the raw URL of this branch.

Configuration (env):
  TPW_DATA_REMOTE  push URL for the repo, with credentials, e.g.
                   https://x-access-token:<fine-grained-PAT>@github.com/vivekchand/third-pole-watch.git
                   (PAT needs contents:read/write on this repo only)
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


def publish() -> bool:
    """Write status.json + ledger snapshot and push. Returns True on push."""
    if not enabled():
        return False
    try:
        p = _ensure_checkout()
        stats = ledger.stats()
        stats["generated_at"] = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
        (p / "status.json").write_text(json.dumps(stats, indent=2) + "\n")
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
