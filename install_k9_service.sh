#!/bin/bash

VER="1.0.5"
echo "🐾 k9-polyvox user service installer v$VER"

# Prevent running as root
if [ "$(id -u)" -eq 0 ]; then
  echo "❌ Don't run this script with sudo. Run as your regular user."
  exit 1
fi

# Check for Python script path
if [ -z "$1" ]; then
  echo "Usage: bash install_k9_user_service.sh /full/path/to/main.py"
  exit 1
fi

PY_SCRIPT="$1"

if [ ! -f "$PY_SCRIPT" ]; then
  echo "❌ Error: file $PY_SCRIPT not found."
  exit 1
fi

SERVICE_NAME="k9_polyvox"
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SERVICE_DIR/$SERVICE_NAME.service"
WORKING_DIR="$(dirname "$PY_SCRIPT")"

echo "📦 Creating systemd user directory..."
mkdir -p "$SERVICE_DIR"

echo "📄 Writing service file to: $SERVICE_FILE"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=K9 PolyVox User Service
After=default.target pipewire.service pipewire.socket
Requires=pipewire.service

[Service]
ExecStart=/usr/bin/python3 $PY_SCRIPT
Restart=on-failure
WorkingDirectory=$WORKING_DIR
Environment=PYTHONUNBUFFERED=1
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOF

# Remove bad legacy lines if they ever existed
sed -i '/^Group=/d' "$SERVICE_FILE"

echo "🔄 Enabling linger for $USER so service runs at boot..."
sudo loginctl enable-linger "$USER"

echo "🔧 Reloading and restarting service..."
systemctl --user daemon-reexec || true
systemctl --user daemon-reload
systemctl --user enable "$SERVICE_NAME"
systemctl --user restart "$SERVICE_NAME"

echo "✅ Service installed and started successfully."
echo "📄 View logs with: journalctl --user -u $SERVICE_NAME -f"
