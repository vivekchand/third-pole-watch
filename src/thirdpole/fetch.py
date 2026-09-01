"""Waveform and station access over open FDSN services.

Station strategy: we do NOT hardcode station lists. We query the FDSN station
service for open broadband channels within a radius of the source region and
use whatever actually returns data. Robust to stations coming and going, and
honest about what "open" gives us.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from obspy import Stream, UTCDateTime
from obspy.clients.fdsn import Client

log = logging.getLogger("thirdpole.fetch")

# Open data centres worth asking, in order. IRIS/EarthScope federates most
# global open networks; GEOFON adds GE and partner stations. Explicit base
# URLs: obspy's short-name mappings currently resolve to hosts that fail
# service discovery (earthscope redirect, geofon.gfz.de).
DATA_CENTRES = ["https://service.iris.edu", "https://geofon.gfz-potsdam.de"]

# Broadband vertical channels; LH (1 Hz) is enough for long-period detection
# and far lighter than BH/HH — we request both and prefer BH when present.
CHANNELS = "BHZ,LHZ,HHZ"
NETWORKS = "IU,II,IC,GE,G,MN"  # global open broadband networks


@dataclass
class StationPick:
    net: str
    sta: str
    lat: float
    lon: float
    dist_deg: float


def find_open_stations(lat: float, lon: float, max_radius_deg: float = 15.0,
                       at_time: UTCDateTime | None = None,
                       max_stations: int = 12) -> list[StationPick]:
    """Open broadband stations within a radius of (lat, lon), nearest first."""
    picks: dict[str, StationPick] = {}
    for centre in DATA_CENTRES:
        try:
            client = Client(centre)
            inv = client.get_stations(
                latitude=lat, longitude=lon, maxradius=max_radius_deg,
                network=NETWORKS, channel=CHANNELS, level="station",
                starttime=at_time, endtime=at_time + 60 if at_time else None,
            )
        except Exception as exc:  # noqa: BLE001 - any centre may be down
            log.warning("station query failed at %s: %s", centre, exc)
            continue
        for net in inv:
            for sta in net:
                key = f"{net.code}.{sta.code}"
                if key in picks:
                    continue
                from obspy.geodetics import locations2degrees
                d = locations2degrees(lat, lon, sta.latitude, sta.longitude)
                picks[key] = StationPick(net.code, sta.code,
                                         sta.latitude, sta.longitude, d)
    ordered = sorted(picks.values(), key=lambda p: p.dist_deg)
    return ordered[:max_stations]


def fetch_waveforms(stations: list[StationPick], start: UTCDateTime,
                    end: UTCDateTime) -> Stream:
    """Fetch vertical-component waveforms; skip stations with no data."""
    out = Stream()
    for centre in DATA_CENTRES:
        try:
            client = Client(centre)
        except Exception:  # noqa: BLE001
            continue
        for p in stations:
            if any(tr.stats.station == p.sta for tr in out):
                continue
            for chan in ("BHZ", "HHZ", "LHZ"):
                try:
                    st = client.get_waveforms(p.net, p.sta, "*", chan,
                                              start, end)
                    if len(st):
                        st.merge(method=1, fill_value="interpolate")
                        out += st
                        log.info("got %s.%s %s (%.1f deg)",
                                 p.net, p.sta, chan, p.dist_deg)
                        break
                except Exception:  # noqa: BLE001 - no data is normal
                    continue
    return out


def catalog_events_near(lat: float, lon: float, t0: UTCDateTime,
                        window_s: float = 600, radius_deg: float = 3.0):
    """Cross-check the FDSN event service around a detection.

    NOTE: a catalog match does NOT mean 'tectonic earthquake, stand down' —
    the 2026 Langtang collapse was initially cataloged as an M4.4 earthquake.
    A match near a glacierized source region is context, never a veto.
    """
    try:
        client = Client("https://service.iris.edu")
        cat = client.get_events(
            latitude=lat, longitude=lon, maxradius=radius_deg,
            starttime=t0 - window_s, endtime=t0 + window_s, minmagnitude=3.5,
        )
        return cat
    except Exception:  # noqa: BLE001
        return None
