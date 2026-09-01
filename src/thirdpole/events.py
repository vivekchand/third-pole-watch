"""Reference events for replay and calibration.

Times/locations from public post-event reporting and USGS analysis; both are
approximate to the minute and good enough for waveform windows.
"""
from dataclasses import dataclass

from obspy import UTCDateTime


@dataclass(frozen=True)
class ReferenceEvent:
    key: str
    name: str
    origin_utc: UTCDateTime
    lat: float
    lon: float
    magnitude: float          # as cataloged (surface-wave based)
    notes: str


EVENTS = {
    "trishuli2026": ReferenceEvent(
        key="trishuli2026",
        name="Langtang Lirung ice-rock avalanche / Trishuli flood",
        origin_utc=UTCDateTime("2026-08-26T02:52:10"),
        lat=28.256, lon=85.517,
        magnitude=5.2,
        notes=(
            "Ms 5.2; USGS: waveform consistent with glacier collapse, not an "
            "earthquake. First SMS alert in Nepal at 03:30 UTC (09:15 NPT), "
            "38 minutes after origin. Gyirong Port destroyed at ~T+7 min."
        ),
    ),
    "chamoli2021": ReferenceEvent(
        key="chamoli2021",
        name="Chamoli (Ronti Peak) rock-ice avalanche / Dhauliganga flood",
        origin_utc=UTCDateTime("2021-02-07T04:51:00"),
        lat=30.373, lon=79.732,
        magnitude=5.0,
        notes=(
            "~27 Mm3 rock-ice avalanche. Cook et al. (Science 2021) showed "
            "regional seismic networks detected initiation and could have "
            "warned Tapovan (~T+15 min arrival) — the validation case for "
            "this whole approach."
        ),
    ),
}
