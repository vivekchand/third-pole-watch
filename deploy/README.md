# Deploying the live watch

The alert path needs a process that never stops — a persistent SeedLink
connection with warm detector state. GitHub Actions cannot be that process
(5-min cron floor, 10–60 min scheduling jitter, occasional dropped runs,
6-hour job cap, auto-disable after 60 days of repo inactivity). Actions
instead runs the **watchdog** (alerts if the daemon stops publishing) and the
**backstop scan** (independent slow second path) — see `.github/workflows/`.

## Architecture

```
GCE e2-micro (always-free) ── tpw watch ──► Telegram alerts (seconds path)
        │ every 5 min / on candidates
        ▼
  git push status.json + ledger.jsonl ──► `data` branch
        │                                      │ raw URL
        ▼                                      ▼
  tamper-evident audit history          thirdpole.watch live status
        ▲
GitHub Actions: watchdog (*/15, staleness alert) + backstop scan (2×/hr)
```

## One-time setup

### 1. Create the VM (free tier)

```bash
./deploy/gcp/create-vm.sh          # e2-micro, us-central1, Debian 12
```

The startup script installs the daemon under systemd; it runs on every boot
and is idempotent, so `gcloud compute instances reset` is always safe.

### 2. Secrets on the VM

Create a **fine-grained GitHub PAT** (Settings → Developer settings →
fine-grained tokens) scoped to ONLY this repo with **Contents: read/write**.
Then:

```bash
gcloud compute ssh thirdpole-watch --zone=us-central1-a
sudo tee /etc/thirdpole-watch.env > /dev/null <<'EOF'
TPW_TELEGRAM_BOT_TOKEN=123456:ABC...
TPW_TELEGRAM_CHAT_ID=-100...
TPW_DATA_REMOTE=https://x-access-token:github_pat_XXX@github.com/vivekchand/third-pole-watch.git
EOF
sudo chmod 600 /etc/thirdpole-watch.env
sudo systemctl restart thirdpole-watch
journalctl -u thirdpole-watch -f
```

Without secrets the daemon still runs: alerts print to the journal and
publishing is a no-op.

### 3. Repo secrets (for the Actions workflows)

Add `TPW_TELEGRAM_BOT_TOKEN` and `TPW_TELEGRAM_CHAT_ID` under repo
Settings → Secrets and variables → Actions, so the watchdog and backstop
can notify. Without them, both workflows still run and log.

### 4. The `data` branch

Created once as an orphan branch holding only `status.json` + `ledger.jsonl`.
The site reads
`https://raw.githubusercontent.com/vivekchand/third-pole-watch/data/status.json`
(raw CDN caches ~5 min — fine for a status page).

## Operations

- **Update the daemon:** push to `main`, then
  `gcloud compute ssh thirdpole-watch --zone=us-central1-a --command="sudo /var/lib/google/startup 2>/dev/null || sudo google_metadata_script_runner startup"`
  — or simply `sudo systemctl restart thirdpole-watch` after
  `sudo git -C /opt/thirdpole-watch pull`.
- **Health:** the site's status tiles + the watchdog Telegram alert. Silence
  from the watchdog + fresh `generated_at` on the site = healthy.
- **Cost:** $0 on the always-free e2-micro (egress from SeedLink/Telegram is
  well under the free allowance). If the free tier ever changes, a Hetzner
  CAX11 (~€4/mo) is the fallback.
