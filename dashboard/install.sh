#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/cloudmart-dashboard
ENV_FILE=/etc/cloudmart-dashboard.env

if command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3 python3-pip nginx
elif command -v yum >/dev/null 2>&1; then
    sudo yum install -y python3 python3-pip nginx
else
    echo "Unsupported Linux distribution: dnf/yum not found"
    exit 1
fi

sudo id -u cloudmart >/dev/null 2>&1 || sudo useradd --system --home-dir "$APP_DIR" --shell /sbin/nologin cloudmart
sudo mkdir -p "$APP_DIR"
sudo cp app.py requirements.txt nginx.conf cloudmart-dashboard.service "$APP_DIR/"
sudo python3 -m venv "$APP_DIR/venv"
sudo "$APP_DIR/venv/bin/pip" install --upgrade pip
sudo "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [ -z "${REPORT_BUCKET:-}" ]; then
    echo "REPORT_BUCKET environment variable is required."
    exit 1
fi

cat <<EOF | sudo tee "$ENV_FILE" >/dev/null
AWS_REGION=ap-south-1
ENVIRONMENT=dev
REPORT_BUCKET=$REPORT_BUCKET
REPORT_PREFIX=reports/
DB_HOST_PARAMETER=/cloudmart/dev/db/host
DB_PORT_PARAMETER=/cloudmart/dev/db/port
DB_NAME_PARAMETER=/cloudmart/dev/db/name
DB_USERNAME_PARAMETER=/cloudmart/dev/db/username
DB_PASSWORD_PARAMETER=/cloudmart/dev/db/password
EOF

sudo chown -R cloudmart:cloudmart "$APP_DIR"
sudo chmod 640 "$ENV_FILE"
sudo cp "$APP_DIR/cloudmart-dashboard.service" /etc/systemd/system/cloudmart-dashboard.service
sudo cp "$APP_DIR/nginx.conf" /etc/nginx/conf.d/cloudmart-dashboard.conf
sudo rm -f /etc/nginx/conf.d/default.conf
sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable --now cloudmart-dashboard
sudo systemctl enable --now nginx
sudo systemctl restart cloudmart-dashboard
sudo systemctl restart nginx

echo "CloudMart dashboard deployment completed."
