"""Live watch: SeedLink real-time streams -> detector -> ledger -> alert.

v0 design: per-station rolling buffers; every SCAN_INTERVAL_S we scan the
buffers, apply multi-station coincidence, cross-check the event catalog, and
alert. Deliberately simple and restartable; state that matters (candidates)
goes to the append-only ledger, not memory.
"""
from __future__ import annotations

import logging
import threading
import time

from obspy import Stream, Trace, UTCDateTime
from obspy.clients.seedlink.easyseedlink import EasySeedLinkClient

from . import alerts, ledger, publisher
from .detector import DetectorConfig, coincident, scan_trace
from .fetch import catalog_events_near

log = logging.getLogger("thirdpole.daemon")

# Open SeedLink servers. GEOFON is the workhorse; Raspberry Shake adds the
# community network (dense, noisy — used only for coincidence, v1).
SEEDLINK_SERVERS = [
    "geofon.gfz-potsdam.de:18000",
    # "rtserve.iris.washington.edu:18000",   # EarthScope real-time
    # "rs.local... "                          # Raspberry Shake: via FDSN/SL
]

# Station selectors (net, sta, channel-pattern) around the Himalayan arc.
# TASK #1 of this project is replacing this short list with a proper
# inventory of every openly-streamed station ringing the HKH region.
SELECTORS = [
    ("IC", "LSA", "BHZ"),    # Lhasa — closest open broadband to Langtang
    ("II", "NIL", "BHZ"),    # Nilore, Pakistan
    ("IU", "CHTO", "BHZ"),   # Chiang Mai
    ("GE", "*", "BHZ"),      # any GEOFON station the server offers in-region
]

BUFFER_S = 3600 * 2          # keep 2 h per station
SCAN_INTERVAL_S = 60
ALERT_COOLDOWN_S = 1800      # don't re-alert the same window
PUBLISH_INTERVAL_S = 300     # push status.json to the data branch
REGION_HINT = "Himalayan arc (v0 station set — coarse localization only)"


class _Buffers:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._streams: dict[str, Stream] = {}

    def add(self, tr: Trace) -> None:
        key = f"{tr.stats.network}.{tr.stats.station}"
        with self._lock:
            st = self._streams.setdefault(key, Stream())
            st += tr
            st.merge(method=1, fill_value="interpolate")
            st.trim(starttime=UTCDateTime() - BUFFER_S)

    def snapshot(self) -> list[Trace]:
        with self._lock:
            return [st[0].copy() for st in self._streams.values() if len(st)]


class _Client(EasySeedLinkClient):
    def __init__(self, server: str, buffers: _Buffers) -> None:
        # autoconnect=False so we can set a real socket timeout first:
        # obspy's SeedLinkConnection defaults timeout to None and then
        # compares `elapsed < timeout` in is_connected_impl -> TypeError.
        super().__init__(server, autoconnect=False)
        self.conn.timeout = 30.0
        self.connect()
        self._buffers = buffers

    def on_data(self, tr: Trace) -> None:  # SeedLink callback
        self._buffers.add(tr)


def run() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(message)s")
    buffers = _Buffers()
    threads = []
    for server in SEEDLINK_SERVERS:
        try:
            client = _Client(server, buffers)
            for net, sta, chan in SELECTORS:
                try:
                    client.select_stream(net, sta, chan)
                except Exception as exc:  # noqa: BLE001
                    log.warning("select %s.%s failed on %s: %s",
                                net, sta, server, exc)
            t = threading.Thread(target=client.run, daemon=True,
                                 name=f"seedlink:{server}")
            t.start()
            threads.append(t)
            log.info("streaming from %s", server)
        except Exception as exc:  # noqa: BLE001
            log.error("SeedLink connect failed %s: %s", server, exc)
    if not threads:
        log.error("no SeedLink server reachable; exiting")
        return 1

    cfg = DetectorConfig()
    last_alert_ts = 0.0
    last_publish_ts = 0.0
    if publisher.enabled():
        log.info("data-branch publishing enabled")
        ledger.append({"kind": "lifecycle", "event": "watch_started"})
        publisher.publish()
    log.info("watch running; scanning every %ss", SCAN_INTERVAL_S)
    while True:
        time.sleep(SCAN_INTERVAL_S)
        try:
            cands = []
            for tr in buffers.snapshot():
                cands.extend(scan_trace(tr, cfg))
            groups = coincident(cands)
            for g in groups:
                det_ts = min(c.trigger_time for c in g)
                if det_ts <= last_alert_ts + ALERT_COOLDOWN_S:
                    continue
                last_alert_ts = det_ts
                when = UTCDateTime(det_ts)
                cat = catalog_events_near(28.0, 85.0, when, radius_deg=10.0)
                cat_note = (f"{len(cat)} cataloged event(s) nearby"
                            if cat else "no catalog match yet")
                stations = [c.station for c in g]
                mean_lp_hf = sum(c.lp_hf_ratio for c in g) / len(g)
                mean_dur = sum(c.duration_s for c in g) / len(g)
                ledger.append({
                    "kind": "candidate", "detected_utc": str(when),
                    "stations": stations, "lp_hf": mean_lp_hf,
                    "duration_s": mean_dur, "catalog": cat_note,
                })
                alerts.send(alerts.format_alert(
                    str(when), stations, REGION_HINT,
                    mean_lp_hf, mean_dur, cat_note))
                publisher.publish()          # candidates publish immediately
                last_publish_ts = time.time()
            if time.time() - last_publish_ts >= PUBLISH_INTERVAL_S:
                publisher.publish()          # heartbeat for the watchdog
                last_publish_ts = time.time()
        except Exception as exc:  # noqa: BLE001 - the watch must not die
            log.exception("scan cycle failed: %s", exc)
