#!/bin/bash
# Run this once on the Pi to install and configure the smart-garage service.
# Usage: bash deploy/setup.sh

set -e

REPO_DIR="$HOME/projects/smart-garage"
VENV_DIR="$REPO_DIR/venv"
SERVICE_NAME="smart-garage"

echo "==> Creating virtual environment..."
python3 -m venv "$VENV_DIR"
PYTHON="$VENV_DIR/bin/python"

echo "==> Installing Python dependencies..."
"$VENV_DIR/bin/pip" install -r "$REPO_DIR/requirements.txt"

echo "==> Checking .env file..."
if [ ! -f "$REPO_DIR/.env" ]; then
  echo ""
  echo "  .env not found. Creating from .env.example..."
  cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
  echo ""
  echo "  !! Edit $REPO_DIR/.env and set:"
  echo "       API_TOKEN=<your secret token>"
  echo "       MOCK=false"
  echo ""
  echo "  Then re-run this script."
  exit 1
fi

echo "==> Writing systemd service..."
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<EOF
[Unit]
Description=Smart Garage API
After=network.target

[Service]
User=$USER
WorkingDirectory=$REPO_DIR
ExecStart=$PYTHON -m uvicorn src.api:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5
EnvironmentFile=$REPO_DIR/.env

[Install]
WantedBy=multi-user.target
EOF

echo "==> Enabling and starting service..."
sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}
sudo systemctl restart ${SERVICE_NAME}

echo ""
echo "Done! Service status:"
sudo systemctl status ${SERVICE_NAME} --no-pager
echo ""
echo "Access at: http://$(hostname).local:8000"
