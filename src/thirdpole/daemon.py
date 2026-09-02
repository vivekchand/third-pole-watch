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

# Open SeedLink servers. GEOFON carries GE + partners; EarthScope rtserve
# carries the global IU/II/IC networks (incl. IC.LSA Lhasa). Raspberry Shake
# community stations are the v1 densification step.
SEEDLINK_SERVERS = [
    "geofon.gfz-potsdam.de:18000",
    "rtserve.iris.washington.edu:18000",
]

# Region of interest: central Himalaya, radius covering the arc.
REGION = {"lat": 28.3, "lon": 85.0, "radius_deg": 15.0}

# Fallback if the FDSN inventory is unreachable at startup. SeedLink servers
# skip selectors they don't carry ("station not accepted"), so every server
# gets the full list and keeps its own subset — no wildcards (the classic
# SeedLink STATION negotiation doesn't accept them).
FALLBACK_SELECTORS = [
    ("IC", "LSA", "BHZ"),    # Lhasa — closest open broadband to Langtang
    ("II", "NIL", "BHZ"),    # Nilore, Pakistan
    ("IU", "CHTO", "BHZ"),   # Chiang Mai
    ("GE", "NPW", "BHZ"),    # Naypyidaw — delivered data for the 2026 replay
]


def _regional_selectors() -> list[tuple[str, str, str]]:
    """Resolve open broadband stations in-region from the FDSN inventory."""
    try:
        from .fetch import find_open_stations
        picks = find_open_stations(REGION["lat"], REGION["lon"],
                                   REGION["radius_deg"], max_stations=20)
        selectors = [(p.net, p.sta, "BHZ") for p in picks]
        if selectors:
            log.info("resolved %d in-region stations from FDSN inventory: %s",
                     len(selectors),
                     ", ".join(f"{n}.{s}" for n, s, _ in selectors))
            return selectors
    except Exception as exc:  # noqa: BLE001
        log.warning("FDSN station resolution failed: %s", exc)
    log.info("using fallback selector list")
    return FALLBACK_SELECTORS

BUFFER_S = 3600 * 2          # keep 2 h per station
SCAN_INTERVAL_S = 60
ALERT_COOLDOWN_S = 1800      # don't re-alert the same window
PUBLISH_INTERVAL_S = 300     # push status.json to the data branch
STALE_TRACE_S = 1800         # ignore traces with no data for 30 min
STALE_RECONNECT_S = 600      # force-reconnect if NO station is fresher
RESPAWN_BACKOFF_S = 120      # min seconds between reconnects per server
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

    def snapshot(self, max_age_s: float | None = None) -> list[Trace]:
        cutoff = UTCDateTime() - max_age_s if max_age_s else None
        with self._lock:
            out = []
            for st in self._streams.values():
                if len(st) and (cutoff is None or st[0].stats.endtime > cutoff):
                    out.append(st[0].copy())
            return out


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
                        format="%(asctime)s %(name)s %(message)s",
                        force=True)  # win over the CLI's WARNING config
    buffers = _Buffers()
    selectors = _regional_selectors()
    workers: dict[str, tuple[_Client | None, threading.Thread | None]] = {}
    last_spawn: dict[str, float] = {}

    def _stream(client: _Client, server: str) -> None:
        try:
            client.run()
        except Exception as exc:  # noqa: BLE001 - e.g. zero stations accepted
            log.error("stream from %s ended: %s", server, exc)

    def _close(server: str) -> None:
        client, _ = workers.get(server, (None, None))
        if client is not None:
            try:
                client.conn.terminate()
                client.close()
            except Exception:  # noqa: BLE001 - closing a dead socket
                pass

    def _spawn(server: str) -> None:
        if time.time() - last_spawn.get(server, 0.0) < RESPAWN_BACKOFF_S:
            return
        last_spawn[server] = time.time()
        _close(server)
        try:
            client = _Client(server, buffers)
            for net, sta, chan in selectors:
                try:
                    client.select_stream(net, sta, chan)
                except Exception as exc:  # noqa: BLE001
                    log.warning("select %s.%s failed on %s: %s",
                                net, sta, server, exc)
            t = threading.Thread(target=_stream, args=(client, server),
                                 daemon=True, name=f"seedlink:{server}")
            t.start()
            workers[server] = (client, t)
            log.info("streaming from %s", server)
        except Exception as exc:  # noqa: BLE001
            workers[server] = (None, None)
            log.error("SeedLink connect failed %s: %s", server, exc)

    for server in SEEDLINK_SERVERS:
        _spawn(server)
    if not any(t for _, t in workers.values()):
        log.error("no SeedLink server reachable; will keep retrying")

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
            # supervise the stream threads: respawn the dead, and if EVERY
            # station has gone quiet, assume half-open sockets (the failure
            # observed 2 Sep 2026: threads alive, servers silent for hours)
            # and force a full reconnect.
            for server in SEEDLINK_SERVERS:
                _, t = workers.get(server, (None, None))
                if t is None or not t.is_alive():
                    log.warning("stream thread for %s is down; reconnecting",
                                server)
                    _spawn(server)
            traces = buffers.snapshot(max_age_s=STALE_TRACE_S)
            newest = max((tr.stats.endtime.timestamp for tr in traces),
                         default=0.0)
            age = time.time() - newest if newest else float("inf")
            log.info("scan: %d fresh stations, newest sample %.0fs old",
                     len(traces), age if age != float("inf") else -1)
            if age > STALE_RECONNECT_S:
                log.warning("no fresh data from ANY station for %.0fs; "
                            "forcing reconnect of all streams", age)
                for server in SEEDLINK_SERVERS:
                    _spawn(server)
            cands = []
            for tr in traces:
                cands.extend(scan_trace(tr, cfg))
            groups = coincident(cands)
            scan_info = {
                "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S",
                                            time.gmtime()),
                "stations": len(traces),
                "station_triggers": sum(1 for c in cands if c.passed),
                "coincident_groups": len(groups),
                "state": "candidate" if groups else "normal",
            }
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
                publisher.publish(traces, scan_info)  # candidates publish now
                last_publish_ts = time.time()
            if time.time() - last_publish_ts >= PUBLISH_INTERVAL_S:
                publisher.publish(traces, scan_info)  # watchdog heartbeat
                last_publish_ts = time.time()
        except Exception as exc:  # noqa: BLE001 - the watch must not die
            log.exception("scan cycle failed: %s", exc)
