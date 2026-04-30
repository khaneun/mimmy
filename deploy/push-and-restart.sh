#!/usr/bin/env bash
# 로컬에서 원격 EC2로 배포하는 간결 파이프라인.
# 전제: EC2에서 이미 /opt/mimmy clone 완료, systemd unit 활성화됨.
set -euo pipefail

REMOTE_USER=${REMOTE_USER:-ubuntu}
REMOTE_HOST=${REMOTE_HOST:?set REMOTE_HOST=your-ec2-host}
APP_DIR=${APP_DIR:-/opt/mimmy}

echo "[+] pushing current branch to origin"
git push

echo "[+] pulling on ${REMOTE_HOST} and restarting services"
ssh "${REMOTE_USER}@${REMOTE_HOST}" bash -s <<EOF
set -euo pipefail
sudo -u mimmy git -C ${APP_DIR} fetch --all --prune
sudo -u mimmy git -C ${APP_DIR} reset --hard origin/main
sudo -u mimmy ${APP_DIR}/.venv/bin/pip install -e ${APP_DIR} >/dev/null
sudo systemctl restart mimmy mimmy-dashboard mimmy-bot
sudo systemctl status --no-pager mimmy mimmy-dashboard mimmy-bot | tail -n 30
EOF
