#!/usr/bin/env bash
# EC2 Ubuntu 22.04+ 초기 세팅 스크립트.
# 전제: 'ubuntu' 사용자로 SSH 접속해 실행. sudo는 NOPASSWD.
# 사용법:
#   ssh -i ~/kitty-key.pem ubuntu@<ec2> 'bash -s' < deploy/ec2-setup.sh
set -euo pipefail

APP_USER=${APP_USER:-ubuntu}
APP_DIR=${APP_DIR:-/opt/mimmy}
REPO_URL=${REPO_URL:-"https://github.com/khaneun/mimmy.git"}
BRANCH=${BRANCH:-main}

echo "[+] apt update"
sudo apt-get update -y
sudo apt-get install -y --no-install-recommends \
    git curl ca-certificates build-essential pkg-config gh

echo "[+] uv 설치 (이미 있으면 스킵)"
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
# uv는 ~/.local/bin 에 설치됨 — 이번 셸 + 이후 systemd ExecStart 모두에서 보이도록 처리
export PATH="${HOME}/.local/bin:${PATH}"
hash -r

echo "[+] ${APP_DIR} 준비"
sudo mkdir -p "${APP_DIR}"
sudo chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

if [ ! -d "${APP_DIR}/.git" ]; then
    git clone --branch "${BRANCH}" "${REPO_URL}" "${APP_DIR}"
else
    git -C "${APP_DIR}" fetch --all --prune
    git -C "${APP_DIR}" reset --hard "origin/${BRANCH}"
fi

echo "[+] uv sync (의존성 + .venv)"
cd "${APP_DIR}"
uv sync --frozen || uv sync

echo "[+] systemd units 설치"
sudo install -m 0644 "${APP_DIR}/deploy/systemd/mimmy.service"           /etc/systemd/system/mimmy.service
sudo install -m 0644 "${APP_DIR}/deploy/systemd/mimmy-dashboard.service" /etc/systemd/system/mimmy-dashboard.service
sudo install -m 0644 "${APP_DIR}/deploy/systemd/mimmy-bot.service"       /etc/systemd/system/mimmy-bot.service

# self-edit가 sudo 없이 systemctl restart 를 호출할 수 있게 sudoers 조각 추가
sudo tee /etc/sudoers.d/mimmy >/dev/null <<EOF
${APP_USER} ALL=(root) NOPASSWD: /bin/systemctl restart mimmy, /bin/systemctl restart mimmy-dashboard, /bin/systemctl restart mimmy-bot
EOF
sudo chmod 0440 /etc/sudoers.d/mimmy

sudo systemctl daemon-reload
echo "[+] done."
echo "    .env 작성 후 다음으로 활성화:"
echo "      sudo systemctl enable --now mimmy mimmy-dashboard mimmy-bot"
