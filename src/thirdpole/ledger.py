"""Append-only candidate ledger.

The measured false-alarm record is the product: nobody should wire a detector
to alerting without one. Every candidate — true, false, ambiguous — is kept.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

LEDGER_PATH = Path.home() / ".thirdpole" / "ledger.jsonl"


def append(record: dict) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {"recorded_at": time.time(), **record}
    with LEDGER_PATH.open("a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def load() -> list[dict]:
    if not LEDGER_PATH.exists():
        return []
    with LEDGER_PATH.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def label(index: int, verdict: str, note: str = "") -> None:
    """Append a human verdict ('real' | 'false' | 'ambiguous') for entry N."""
    append({"kind": "verdict", "candidate_index": index,
            "verdict": verdict, "note": note})


def stats() -> dict:
    rows = load()
    cands = [r for r in rows if r.get("kind") == "candidate"]
    verdicts = {r["candidate_index"]: r["verdict"]
                for r in rows if r.get("kind") == "verdict"}
    first = min((r["recorded_at"] for r in rows), default=time.time())
    return {
        "days_running": round((time.time() - first) / 86400, 1),
        "candidates": len(cands),
        "verified_real": sum(1 for v in verdicts.values() if v == "real"),
        "false_alarms": sum(1 for v in verdicts.values() if v == "false"),
        "unlabeled": len(cands) - len(verdicts),
    }
