"""live_payload sanity (no network, no git)."""
import numpy as np
import pytest

obspy = pytest.importorskip("obspy")
from obspy import Trace, UTCDateTime  # noqa: E402

from thirdpole.publisher import LIVE_POINTS, live_payload  # noqa: E402


def _trace(station: str, sr: float, age_s: float, now: float) -> Trace:
    tr = Trace(data=np.random.default_rng(1).normal(0, 1, int(700 * sr)))
    tr.stats.sampling_rate = sr
    tr.stats.network = "XX"
    tr.stats.station = station
    tr.stats.starttime = UTCDateTime(now - age_s) - 700
    return tr


def test_live_payload_shape():
    now = 1_700_000_000.0
    payload = live_payload([_trace("AAA", 20.0, 12, now),
                            _trace("BBB", 20.0, 40, now)], now=now)
    assert payload["window_s"] == 600
    assert len(payload["stations"]) == 2
    s = payload["stations"][0]           # freshest first
    assert s["id"] == "XX.AAA" and s["age_s"] == 12
    assert len(s["env"]) == LIVE_POINTS
    assert max(s["env"]) == 1.0 and min(s["env"]) >= 0.0


def test_live_payload_skips_tiny_traces():
    now = 1_700_000_000.0
    tiny = _trace("TIN", 0.1, 5, now)    # 70 samples < LIVE_POINTS
    payload = live_payload([tiny], now=now)
    assert payload["stations"] == []
