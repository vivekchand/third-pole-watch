"""Subscriber notifications. v0: Telegram (plus stdout, always).

Alerts are deliberately worded as UNCONFIRMED research signals. This system
must never present itself as an official warning service.
"""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger("thirdpole.alerts")

DISCLAIMER = ("Unconfirmed automated research signal — NOT an official "
              "warning. Verify against local sources. Official alerts: "
              "national authorities (Nepal: DHM/NDRRMA).")


def format_alert(when_utc: str, stations: list[str], region_hint: str,
                 lp_hf: float, duration_s: float, catalog_note: str) -> str:
    return (
        f"⚠️ THIRD POLE WATCH — mass-movement candidate\n"
        f"Time (UTC): {when_utc}\n"
        f"Region: {region_hint}\n"
        f"Stations: {', '.join(stations)}\n"
        f"Signal: LP/HF {lp_hf:.1f}, duration {duration_s:.0f}s\n"
        f"Catalog: {catalog_note}\n"
        f"{DISCLAIMER}"
    )


def send(text: str) -> None:
    print(text, flush=True)
    token = os.environ.get("TPW_TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TPW_TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.info("Telegram not configured (TPW_TELEGRAM_BOT_TOKEN / "
                 "TPW_TELEGRAM_CHAT_ID); printed only.")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - alerting must never crash watch
        log.error("Telegram send failed: %s", exc)
