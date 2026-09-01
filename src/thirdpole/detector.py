"""v0 mass-movement detector.

Heuristic, deliberately simple, and written to be calibrated by `tpw replay`:

1. Trigger: classic STA/LTA on the smoothed broadband envelope (catches
   emergent, long-duration signals that impulsive-onset pickers miss).
2. Discriminate: mass movements (glacier collapses, rock-ice avalanches,
   debris flows) are long-period-rich and high-frequency-poor relative to
   tectonic earthquakes of similar amplitude, with emergent onsets and long
   durations (Ekström & Stark 2013; Cook et al. 2021).
3. Coincidence across stations is handled by the caller (daemon/replay).

Every threshold lives in DetectorConfig so replay calibration is one place.
This is a starting point for collaboration with actual seismologists — the
real discriminator should be a trained classifier on curated event sets.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from obspy import Trace
from obspy.signal.trigger import classic_sta_lta, trigger_onset


@dataclass
class DetectorConfig:
    # envelope STA/LTA
    sta_s: float = 30.0
    lta_s: float = 600.0
    trig_on: float = 3.0
    trig_off: float = 1.5
    # discriminator bands (Hz)
    lp_band: tuple[float, float] = (0.02, 0.10)
    hf_band: tuple[float, float] = (1.0, 5.0)
    # thresholds — CALIBRATE WITH `tpw replay`
    min_lp_hf_ratio: float = 2.0     # long-period / high-frequency energy
    min_duration_s: float = 60.0     # sustained source, not an impulse
    smooth_s: float = 10.0


@dataclass
class Candidate:
    station: str
    trigger_time: float          # epoch seconds
    duration_s: float
    lp_hf_ratio: float
    peak_stalta: float
    passed: bool
    reasons: list[str] = field(default_factory=list)


def _band_rms(tr: Trace, fmin: float, fmax: float,
              t0: float, t1: float) -> float:
    """RMS amplitude of a bandpassed copy over [t0, t1] (epoch seconds)."""
    c = tr.copy()
    c.detrend("demean")
    nyq = c.stats.sampling_rate / 2.0
    if fmax >= nyq:
        fmax = 0.9 * nyq
    if fmin >= fmax:
        return 0.0
    c.filter("bandpass", freqmin=fmin, freqmax=fmax, corners=4,
             zerophase=True)
    start = c.stats.starttime.timestamp
    i0 = max(0, int((t0 - start) * c.stats.sampling_rate))
    i1 = min(len(c.data), int((t1 - start) * c.stats.sampling_rate))
    if i1 <= i0:
        return 0.0
    seg = np.asarray(c.data[i0:i1], dtype=float)
    return float(np.sqrt(np.mean(seg * seg))) if len(seg) else 0.0


def _envelope(tr: Trace, smooth_s: float) -> np.ndarray:
    data = np.abs(np.asarray(tr.data, dtype=float))
    n = max(1, int(smooth_s * tr.stats.sampling_rate))
    kernel = np.ones(n) / n
    return np.convolve(data, kernel, mode="same")


def scan_trace(tr: Trace, cfg: DetectorConfig | None = None) -> list[Candidate]:
    """Scan one vertical-component trace for mass-movement candidates."""
    cfg = cfg or DetectorConfig()
    out: list[Candidate] = []

    work = tr.copy()
    work.detrend("demean")
    # broadband for the envelope trigger; keep LP content in
    nyq = work.stats.sampling_rate / 2.0
    work.filter("bandpass", freqmin=cfg.lp_band[0],
                freqmax=min(cfg.hf_band[1], 0.9 * nyq),
                corners=4, zerophase=True)

    env = _envelope(work, cfg.smooth_s)
    sr = work.stats.sampling_rate
    nsta, nlta = int(cfg.sta_s * sr), int(cfg.lta_s * sr)
    if len(env) <= nlta:
        return out
    ratio = classic_sta_lta(env, nsta, nlta)
    onsets = trigger_onset(ratio, cfg.trig_on, cfg.trig_off)

    start_ts = work.stats.starttime.timestamp
    for i0, i1 in onsets:
        t0, t1 = start_ts + i0 / sr, start_ts + i1 / sr
        duration = t1 - t0
        lp = _band_rms(tr, *cfg.lp_band, t0, t1)
        hf = _band_rms(tr, *cfg.hf_band, t0, t1)
        lp_hf = lp / hf if hf > 0 else float("inf")
        peak = float(np.max(ratio[i0:i1])) if i1 > i0 else float(ratio[i0])

        reasons = []
        if duration < cfg.min_duration_s:
            reasons.append(f"duration {duration:.0f}s < {cfg.min_duration_s:.0f}s")
        if lp_hf < cfg.min_lp_hf_ratio:
            reasons.append(f"LP/HF {lp_hf:.2f} < {cfg.min_lp_hf_ratio}")

        out.append(Candidate(
            station=f"{tr.stats.network}.{tr.stats.station}",
            trigger_time=t0,
            duration_s=duration,
            lp_hf_ratio=lp_hf,
            peak_stalta=peak,
            passed=not reasons,
            reasons=reasons,
        ))
    return out


def coincident(cands: list[Candidate], min_stations: int = 2,
               window_s: float = 600.0) -> list[list[Candidate]]:
    """Group passing candidates whose trigger times fall in one window.

    v0: fixed window, no travel-time move-out correction. Surface waves cross
    a 15-degree aperture in roughly 8 minutes, hence the default 600 s.
    """
    passing = sorted((c for c in cands if c.passed),
                     key=lambda c: c.trigger_time)
    groups: list[list[Candidate]] = []
    for c in passing:
        placed = False
        for g in groups:
            if abs(c.trigger_time - g[0].trigger_time) <= window_s and \
               all(x.station != c.station for x in g):
                g.append(c)
                placed = True
                break
        if not placed:
            groups.append([c])
    return [g for g in groups if len(g) >= min_stations]
