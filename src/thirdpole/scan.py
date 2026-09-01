"""Backstop archive scan: the slow, independent second detection path.

Runs from GitHub Actions on a cron. Scans the trailing window from FDSN
archives with the same detector the live daemon uses. Purpose: catch what a
downed or deafened daemon missed, within the hour — never to replace the
daemon (archive latency + cron jitter make this path minutes-to-tens-of-
minutes slower by design).

Exit codes: 0 = quiet, 1 = candidate(s) found (workflow turns this into a
notification), 2 = scan could not run (no stations/data).
"""
from __future__ import annotations

import json

from obspy import UTCDateTime

from .detector import DetectorConfig, coincident, scan_trace
from .fetch import catalog_events_near, fetch_waveforms, find_open_stations

# Central Himalaya anchor; radius covers the arc from Karakoram to Bhutan.
REGION = {"lat": 28.3, "lon": 85.0, "radius_deg": 15.0}
LTA_WARMUP_S = 1800


def run(hours: float = 2.0) -> int:
    now = UTCDateTime()
    start = now - hours * 3600 - LTA_WARMUP_S
    stations = find_open_stations(REGION["lat"], REGION["lon"],
                                  REGION["radius_deg"], at_time=now - 3600)
    if not stations:
        print(json.dumps({"scan": "failed", "reason": "no stations"}))
        return 2
    st = fetch_waveforms(stations, start, now)
    if not len(st):
        print(json.dumps({"scan": "failed", "reason": "no waveforms"}))
        return 2

    cands = []
    cfg = DetectorConfig()
    for tr in st:
        cands.extend(scan_trace(tr, cfg))
    groups = coincident(cands)

    result = {
        "scan": "ok",
        "window_utc": [str(start), str(now)],
        "stations_with_data": sorted({f"{t.stats.network}.{t.stats.station}"
                                      for t in st}),
        "coincident_groups": [],
    }
    for g in groups:
        det = min(c.trigger_time for c in g)
        cat = catalog_events_near(REGION["lat"], REGION["lon"],
                                  UTCDateTime(det), radius_deg=10.0)
        result["coincident_groups"].append({
            "detected_utc": str(UTCDateTime(det)),
            "stations": [c.station for c in g],
            "mean_lp_hf": round(sum(c.lp_hf_ratio for c in g) / len(g), 2),
            "mean_duration_s": round(sum(c.duration_s for c in g) / len(g)),
            "catalog": f"{len(cat)} event(s) nearby" if cat else "no match",
        })
    print(json.dumps(result, indent=2))
    return 1 if result["coincident_groups"] else 0
