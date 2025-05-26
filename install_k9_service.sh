#!/bin/bash

VER="1.0.6"
echo "🐾 k9-polyvox service installer v$VER"

# Parse arguments
SYSTEM_SERVICE=false
PY_SCRIPT=""

# Process command line options
while [[ $# -gt 0 ]]; do
  case $1 in
    --system)
      SYSTEM_SERVICE=true
      shift
      ;;
    *)
      PY_SCRIPT="$1"
      shift
      ;;
  esac
done

# Check if we're installing as system or user service
if [ "$SYSTEM_SERVICE" = true ]; then
  echo "Installing as system-level service..."
  
  # Check if running as root (required for system service)
  if [ "$(id -u)" -ne 0 ]; then
    echo "❌ System-level service installation requires root. Please run with sudo."
    exit 1
  fi
else
  echo "Installing as user-level service..."
  
  # Prevent running as root for user service
  if [ "$(id -u)" -eq 0 ]; then
    echo "❌ Don't run user service installation with sudo. Run as your regular user."
    exit 1
  fi
fi

# Check for Python script path
if [ -z "$PY_SCRIPT" ]; then
  echo "Usage: bash install_k9_service.sh [--system] /full/path/to/main.py"
  exit 1
fi

if [ ! -f "$PY_SCRIPT" ]; then
  echo "❌ Error: file $PY_SCRIPT not found."
  exit 1
fi

SERVICE_NAME="k9_polyvox"
WORKING_DIR="$(dirname "$PY_SCRIPT")"

if [ "$SYSTEM_SERVICE" = true ]; then
  # System-level service configuration
  SERVICE_DIR="/etc/systemd/system"
  SERVICE_FILE="$SERVICE_DIR/$SERVICE_NAME.service"
  
  echo "📦 Using system service directory: $SERVICE_DIR"
  
  echo "📄 Writing service file to: $SERVICE_FILE"
  cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=K9 PolyVox System Service
After=network.target sound.target
Wants=sound.target

[Service]
ExecStart=/usr/bin/python3 $PY_SCRIPT
Restart=on-failure
WorkingDirectory=$WORKING_DIR
Environment=PYTHONUNBUFFERED=1
Environment=DISABLE_PIDOG_SPEAKER=0
Environment=DISABLE_PIDOG_DISPLAY=1
StandardOutput=journal
StandardError=journal
User=root

[Install]
WantedBy=multi-user.target
EOF

  echo "🔧 Reloading and restarting service..."
  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"

  echo "✅ System service installed and started successfully."
  echo "📄 View logs with: journalctl -u $SERVICE_NAME -f"
else
  # User-level service configuration
  SERVICE_DIR="$HOME/.config/systemd/user"
  SERVICE_FILE="$SERVICE_DIR/$SERVICE_NAME.service"
  
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
Environment=DISABLE_PIDOG_SPEAKER=0
Environment=DISABLE_PIDOG_DISPLAY=1
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

  echo "✅ User service installed and started successfully."
  echo "📄 View logs with: journalctl --user -u $SERVICE_NAME -f"
fi
