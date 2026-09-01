# The Flywheel

How this project compounds. Every contribution should push one wheel segment;
every release should complete at least one full turn.

```
        ┌────────────────────────────────────────────────┐
        ▼                                                │
  1. WATCH runs on open stations                         │
        │  candidates (true, false, ambiguous)           │
        ▼                                                │
  2. LEDGER records every one, publicly                  │
        │  human verdicts (`tpw ledger label`)           │
        ▼                                                │
  3. CALIBRATE: replay harness turns verdicts into       │
     better thresholds / classifiers (PRs)               │
        │  measured false-alarm rate improves            │
        ▼                                                │
  4. TRUST grows — published score, reproducible replays │
        │  scientists join, stations open, subscribers   │
        │  (hydropower, trekking ops) sign up            │
        ▼                                                │
  5. COVERAGE grows — more stations (incl. community     │
     Raspberry Shakes), denser corridors, lower latency ─┘
```

Trust is the flywheel's bearing. It is earned by publishing failures
(the ledger includes every false alarm, forever) and by making every claim
reproducible (`tpw replay` on public data). Nothing that spends trust —
overstating confidence, alert wording that reads as official, silent
threshold changes — is worth what it buys.

## Ship process

1. **Branch + PR for everything.** No direct pushes to `main`. Small PRs,
   one wheel segment each.
2. **Replays are the regression suite.** Any change to `detector.py` must
   include before/after output of `tpw replay trishuli2026` and
   `tpw replay chamoli2021` in the PR description. A change that improves
   one event and silently degrades the other is a rejection, not a tweak.
3. **Thresholds change in the open.** Every `DetectorConfig` change gets a
   PR explaining what evidence motivated it. The config is the scientific
   record.
4. **Tests must pass** (`pytest`); new detector behaviour gets a synthetic
   test alongside the replay evidence.
5. **The ledger is append-only.** Never edit or delete ledger entries —
   wrong verdicts get corrected by appending a new verdict, preserving
   history.
6. **Alert wording is load-bearing.** Any change to alert text or the
   disclaimer in `alerts.py` needs explicit review — this is the boundary
   between a research signal and impersonating an official warning.
7. **Site follows the code.** `docs/` deploys from `main` via GitHub Pages;
   `tpw ledger stats --write docs/status.json` publishes the live score.
   The status page must never show numbers the ledger can't back.

## Cadence

- **Weekly** while the watch runs: label the week's candidates, publish
  `status.json`, note anything anomalous in an issue.
- **Monthly**: a short public log entry — days up, candidates, verdicts,
  detector changes. This is the artifact funders and collaborators read.
- **Per event** (any real mass movement in the region, detected or missed):
  a replay post-mortem issue within a week. Misses are the most valuable
  data this project produces.
