"""Replay a reference event from public archives and score the detector.

Output: per-station detection times vs. the actual human warning chain, and a
summary plot — the credibility artifact ("detection at T+X min vs SMS at
T+38") for conversations with GFZ / ICIMOD / funders.
"""
from __future__ import annotations

import logging
from pathlib import Path

from obspy import UTCDateTime

from .detector import DetectorConfig, coincident, scan_trace
from .events import EVENTS, ReferenceEvent
from .fetch import catalog_events_near, fetch_waveforms, find_open_stations

log = logging.getLogger("thirdpole.replay")

PRE_S = 1800     # window: 30 min before origin (for LTA warm-up)
POST_S = 3600    # to 60 min after


def run(event_key: str, out_dir: str = "out") -> int:
    ev: ReferenceEvent | None = EVENTS.get(event_key)
    if ev is None:
        print(f"unknown event '{event_key}'; choices: {sorted(EVENTS)}")
        return 2

    print(f"== Replay: {ev.name}")
    print(f"   origin {ev.origin_utc} UTC  ({ev.lat:.3f}, {ev.lon:.3f})  "
          f"M{ev.magnitude}")

    stations = find_open_stations(ev.lat, ev.lon, at_time=ev.origin_utc)
    if not stations:
        print("No open stations found — check network access / FDSN status.")
        return 1
    print(f"   {len(stations)} open stations within 15°: "
          + ", ".join(f"{p.net}.{p.sta}({p.dist_deg:.1f}°)" for p in stations))

    st = fetch_waveforms(stations, ev.origin_utc - PRE_S, ev.origin_utc + POST_S)
    if not len(st):
        print("No waveforms returned. Archives may embargo recent data; "
              "try again later or widen the radius.")
        return 1

    all_cands = []
    cfg = DetectorConfig()
    for tr in st:
        for c in scan_trace(tr, cfg):
            all_cands.append(c)
            t_rel = c.trigger_time - ev.origin_utc.timestamp
            mark = "PASS" if c.passed else f"reject ({'; '.join(c.reasons)})"
            print(f"   {c.station:12s} trigger T{t_rel:+7.0f}s  "
                  f"dur {c.duration_s:5.0f}s  LP/HF {c.lp_hf_ratio:6.2f}  "
                  f"{mark}")

    groups = coincident(all_cands)
    if groups:
        g = groups[0]
        det_t = min(c.trigger_time for c in g)
        t_rel = det_t - ev.origin_utc.timestamp
        print(f"\n== COINCIDENT DETECTION at T{t_rel:+.0f}s "
              f"({len(g)} stations: {', '.join(c.station for c in g)})")
        if event_key == "trishuli2026":
            print(f"   Actual first SMS alert: T+2280s (+38 min). "
                  f"Margin recovered: {(2280 - t_rel)/60:.0f} minutes.")
    else:
        print("\n== No coincident detection with current thresholds — "
              "this is the calibration signal: inspect per-station rows "
              "above and adjust DetectorConfig.")

    cat = catalog_events_near(ev.lat, ev.lon, ev.origin_utc)
    if cat:
        print(f"   FDSN catalog near origin: {len(cat)} event(s) "
              f"(remember: the 2026 collapse WAS cataloged as an earthquake).")

    _plot(st, ev, all_cands, Path(out_dir))
    return 0


def _plot(st, ev, cands, out_dir: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # noqa: BLE001
        log.warning("matplotlib unavailable; skipping plot")
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    n = len(st)
    fig, axes = plt.subplots(n, 1, figsize=(12, 1.6 * n), sharex=True,
                             squeeze=False)
    for ax, tr in zip(axes[:, 0], st):
        t = tr.times(reftime=UTCDateTime(ev.origin_utc))
        ax.plot(t / 60.0, tr.data, lw=0.4, color="#2C6E9E")
        ax.axvline(0, color="#B5442A", lw=1)
        for c in cands:
            if c.station == f"{tr.stats.network}.{tr.stats.station}" and c.passed:
                ax.axvline((c.trigger_time - ev.origin_utc.timestamp) / 60.0,
                           color="#2E7D5B", lw=1, ls="--")
        ax.set_ylabel(f"{tr.stats.network}.{tr.stats.station}", fontsize=7,
                      rotation=0, ha="right", va="center")
        ax.set_yticks([])
    axes[-1, 0].set_xlabel("minutes after origin (red = collapse, "
                           "green = detector trigger)")
    fig.suptitle(ev.name)
    fig.tight_layout()
    path = out_dir / f"replay_{ev.key}.png"
    fig.savefig(path, dpi=150)
    print(f"   plot written: {path}")
