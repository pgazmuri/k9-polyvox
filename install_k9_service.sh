#!/bin/bash

VER="1.0.7"
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

# Function to check and remove existing services
cleanup_existing_services() {
  local found_existing=false
  
  # Check for existing system service
  if systemctl list-unit-files | grep -q "^$SERVICE_NAME.service"; then
    echo "⚠️  Found existing system service: $SERVICE_NAME"
    if [ "$SYSTEM_SERVICE" = false ]; then
      echo "🔄 Removing conflicting system service..."
      if [ "$(id -u)" -eq 0 ]; then
        systemctl stop "$SERVICE_NAME" 2>/dev/null || true
        systemctl disable "$SERVICE_NAME" 2>/dev/null || true
        rm -f "/etc/systemd/system/$SERVICE_NAME.service"
        systemctl daemon-reload
        echo "✅ System service removed"
      else
        echo "❌ Need sudo privileges to remove system service. Please run:"
        echo "   sudo systemctl stop $SERVICE_NAME"
        echo "   sudo systemctl disable $SERVICE_NAME"
        echo "   sudo rm /etc/systemd/system/$SERVICE_NAME.service"
        echo "   sudo systemctl daemon-reload"
        echo "Then run this installer again."
        exit 1
      fi
    fi
    found_existing=true
  fi
  
  # Check for existing user service
  if [ "$(id -u)" -ne 0 ]; then  # Only check if not root
    if systemctl --user list-unit-files 2>/dev/null | grep -q "^$SERVICE_NAME.service"; then
      echo "⚠️  Found existing user service: $SERVICE_NAME"
      if [ "$SYSTEM_SERVICE" = true ]; then
        echo "🔄 You have a user service that needs to be removed first."
        echo "   Run the following commands as your regular user (not root):"
        echo "   systemctl --user stop $SERVICE_NAME"
        echo "   systemctl --user disable $SERVICE_NAME"
        echo "   rm ~/.config/systemd/user/$SERVICE_NAME.service"
        echo "   systemctl --user daemon-reload"
        echo "Then run this installer again with sudo and --system."
        exit 1
      else
        echo "🔄 Stopping existing user service..."
        systemctl --user stop "$SERVICE_NAME" 2>/dev/null || true
        systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true
      fi
      found_existing=true
    fi
  else
    # Running as root, check for user services in common user directories
    for user_home in /home/*; do
      if [ -f "$user_home/.config/systemd/user/$SERVICE_NAME.service" ]; then
        local username=$(basename "$user_home")
        echo "⚠️  Found user service for user: $username"
        echo "   User $username needs to remove their service first by running:"
        echo "   systemctl --user stop $SERVICE_NAME"
        echo "   systemctl --user disable $SERVICE_NAME"
        echo "   rm ~/.config/systemd/user/$SERVICE_NAME.service"
        echo "   systemctl --user daemon-reload"
        found_existing=true
      fi
    done
    if [ "$found_existing" = true ] && [ "$SYSTEM_SERVICE" = true ]; then
      echo "❌ Please remove all user services before installing system service."
      exit 1
    fi
  fi
  
  if [ "$found_existing" = true ]; then
    echo "🔄 Proceeding with new installation..."
    sleep 2
  fi
}

# Check for and handle existing services
cleanup_existing_services

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
RestartSec=5
WorkingDirectory=$WORKING_DIR
Environment=PYTHONUNBUFFERED=1
Environment=DISABLE_PIDOG_SPEAKER=0
Environment=DISABLE_PIDOG_DISPLAY=1
StandardOutput=journal
StandardError=journal
User=root
Type=simple

[Install]
WantedBy=multi-user.target
EOF

  echo "🔧 Reloading and restarting service..."
  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"
  
  # Check if service started successfully
  sleep 2
  if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "✅ System service installed and started successfully."
  else
    echo "⚠️  System service installed but may not be running properly."
  fi
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
RestartSec=5
WorkingDirectory=$WORKING_DIR
Environment=PYTHONUNBUFFERED=1
Environment=DISABLE_PIDOG_SPEAKER=0
Environment=DISABLE_PIDOG_DISPLAY=1
StandardOutput=journal
StandardError=journal
Type=simple

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

  # Check if service started successfully
  sleep 2
  if systemctl --user is-active --quiet "$SERVICE_NAME"; then
    echo "✅ User service installed and started successfully."
  else
    echo "⚠️  User service installed but may not be running properly."
  fi
  echo "📄 View logs with: journalctl --user -u $SERVICE_NAME -f"
fi