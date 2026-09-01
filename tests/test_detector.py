"""Detector sanity tests on synthetic signals (no network needed)."""
import numpy as np
import pytest

obspy = pytest.importorskip("obspy")
from obspy import Trace  # noqa: E402

from thirdpole.detector import DetectorConfig, coincident, scan_trace  # noqa: E402


SR = 20.0  # Hz


def _trace(data: np.ndarray, station: str = "TST1") -> Trace:
    tr = Trace(data=data.astype(np.float64))
    tr.stats.sampling_rate = SR
    tr.stats.network = "XX"
    tr.stats.station = station
    return tr


def _noise(n: int, amp: float = 1.0, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).normal(0, amp, n)


def test_mass_movement_like_signal_passes():
    """Emergent, long-duration, long-period-rich signal must PASS."""
    n = int(3600 * SR)
    data = _noise(n, amp=0.5)
    t = np.arange(n) / SR
    onset, dur = 2400.0, 240.0
    ramp = np.clip((t - onset) / 60.0, 0, 1) * np.clip((onset + dur - t) / 60.0, 0, 1)
    data += 60.0 * ramp * np.sin(2 * np.pi * 0.05 * t)  # 20 s period
    cands = scan_trace(_trace(data), DetectorConfig())
    assert any(c.passed for c in cands), [c.reasons for c in cands]


def test_impulsive_hf_earthquake_rejected():
    """Short, high-frequency, impulsive burst must NOT pass the discriminator."""
    n = int(3600 * SR)
    data = _noise(n, amp=0.5)
    t = np.arange(n) / SR
    burst = (t > 2400) & (t < 2415)  # 15 s impulse
    data += 80.0 * burst * np.sin(2 * np.pi * 3.0 * t)  # 3 Hz
    cands = scan_trace(_trace(data), DetectorConfig())
    assert not any(c.passed for c in cands)


def test_coincidence_requires_two_stations():
    n = int(3600 * SR)
    t = np.arange(n) / SR
    ramp = np.clip((t - 2400) / 60.0, 0, 1) * np.clip((2640 - t) / 60.0, 0, 1)
    sig = 60.0 * ramp * np.sin(2 * np.pi * 0.05 * t)
    c1 = scan_trace(_trace(_noise(n, 0.5, 1) + sig, "STA1"))
    c2 = scan_trace(_trace(_noise(n, 0.5, 2) + sig, "STA2"))
    assert coincident(c1) == []                     # one station: no group
    groups = coincident(c1 + c2)
    assert len(groups) == 1 and len(groups[0]) == 2
