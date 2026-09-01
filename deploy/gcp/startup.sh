#!/usr/bin/env bash
# GCE startup script: installs and starts the Third Pole Watch daemon.
# Idempotent — safe on every boot.
set -euo pipefail

REPO="https://github.com/vivekchand/third-pole-watch.git"
APP=/opt/thirdpole-watch

apt-get update -qq
apt-get install -y -qq git python3-venv python3-pip

id -u tpw &>/dev/null || useradd -r -m -s /usr/sbin/nologin tpw

if [ ! -d "$APP/.git" ]; then
  git clone "$REPO" "$APP"
else
  git -C "$APP" pull --ff-only || true
fi

if [ ! -x "$APP/.venv/bin/tpw" ]; then
  python3 -m venv "$APP/.venv"
fi
"$APP/.venv/bin/pip" install -q -e "$APP"
chown -R tpw:tpw "$APP"

# Secrets live in /etc/thirdpole-watch.env (created once by hand — see
# deploy/README.md). Ship an empty file so systemd starts either way.
touch /etc/thirdpole-watch.env
chmod 600 /etc/thirdpole-watch.env

cp "$APP/deploy/thirdpole-watch.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now thirdpole-watch
