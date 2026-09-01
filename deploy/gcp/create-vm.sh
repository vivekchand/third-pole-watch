#!/usr/bin/env bash
# Create the always-free GCE VM for the watch daemon.
# Free tier: one e2-micro in us-west1 / us-central1 / us-east1, 30 GB
# standard disk. obspy + the daemon fit comfortably in 1 GB RAM.
set -euo pipefail

ZONE="${ZONE:-us-central1-a}"
NAME="${NAME:-thirdpole-watch}"

gcloud compute instances create "$NAME" \
  --zone="$ZONE" \
  --machine-type=e2-micro \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --boot-disk-size=30GB \
  --boot-disk-type=pd-standard \
  --metadata-from-file=startup-script="$(dirname "$0")/startup.sh" \
  --labels=app=thirdpole-watch

echo
echo "VM created. Next (see deploy/README.md):"
echo "  1. gcloud compute ssh $NAME --zone=$ZONE"
echo "  2. sudo nano /etc/thirdpole-watch.env   # add secrets"
echo "  3. sudo systemctl restart thirdpole-watch"
echo "  4. journalctl -u thirdpole-watch -f     # watch it watch"
