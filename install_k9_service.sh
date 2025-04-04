#!/bin/bash

VER="1.0.0"
echo "k9-polyvox service installer v$VER"

# Check for root
if [ $(id -u) -ne 0 ]; then
  echo "Run this script with sudo"
  exit 1
fi

# Check argument
if [ -z "$1" ]; then
  echo "Usage: sudo bash install_k9_service.sh /full/path/to/main.py"
  exit 1
fi

PY_SCRIPT="$1"

if [ ! -f "$PY_SCRIPT" ]; then
  echo "Error: file $PY_SCRIPT not found."
  exit 1
fi

# Get the user who invoked sudo
user=${SUDO_USER:-$(who -m | awk '{ print $1 }')}
user_home="$(eval echo ~$user)"

echo "Installing service to run: $PY_SCRIPT as user $user"

SERVICE_NAME="k9_polyvox"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=K9 PolyVox Service
After=network.target

[Service]
ExecStart=/bin/python3 $PY_SCRIPT
Restart=on-failure
User=$user
Group=$user
WorkingDirectory=$(dirname "$PY_SCRIPT")
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# Enable and start the service
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo "Service installed and started. Check status with: sudo systemctl status $SERVICE_NAME"
