#!/usr/bin/env bash
set -euo pipefail

echo "=== cat-detector installer ==="
echo

# 1. Check system dependency
if ! python3 -c "import evdev" 2>/dev/null; then
    echo "Installing python-evdev..."
    sudo pacman -S --needed --noconfirm python-evdev
fi
echo "[ok] python-evdev"

# 2. Ensure user is in input group
if ! id -nG "$USER" | grep -qw input; then
    echo "Adding $USER to the input group..."
    sudo usermod -aG input "$USER"
    echo "NOTE: Log out and back in for the group change to take effect."
else
    echo "[ok] $USER is in the input group"
fi

# 3. Install systemd user service
SERVICE_DIR="${HOME}/.config/systemd/user"
mkdir -p "$SERVICE_DIR"
cp "$(dirname "$0")/cat-detector.service" "$SERVICE_DIR/"
systemctl --user daemon-reload
systemctl --user enable --now cat-detector.service
echo "[ok] Service enabled: cat-detector.service"

# 4. Remind about optional meow sound
MEOW="$(dirname "$0")/assets/meow.wav"
if [[ ! -f "$MEOW" ]]; then
    echo
    echo "Tip: Drop a meow.wav into assets/ for audio alerts when a cat is detected."
fi

echo
echo "=== Installation complete! ==="
echo "  Test:   python3 cat_detector.py --sensitivity high"
echo "  Status: systemctl --user status cat-detector"
echo "  Logs:   journalctl --user -u cat-detector -f"
