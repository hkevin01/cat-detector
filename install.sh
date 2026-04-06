#!/usr/bin/env bash
# install.sh — cat-detector Linux installer
# Supports: Arch/Manjaro, Debian/Ubuntu, Fedora/RHEL, openSUSE, and pip fallback
set -euo pipefail

echo "=== cat-detector installer (Linux) ==="
echo

# ── 1. Install python-evdev ───────────────────────────────────────────────────
if ! python3 -c "import evdev" 2>/dev/null; then
    echo "Installing python-evdev..."
    if   command -v pacman  &>/dev/null; then sudo pacman  -S --needed --noconfirm python-evdev
    elif command -v apt-get &>/dev/null; then sudo apt-get install -y python3-evdev
    elif command -v dnf     &>/dev/null; then sudo dnf     install -y python3-evdev
    elif command -v zypper  &>/dev/null; then sudo zypper  install -y python3-evdev
    else
        echo "  Package manager not detected — falling back to pip"
        pip install --user evdev
    fi
fi
echo "[ok] python-evdev"

# ── 2. Add user to input group ────────────────────────────────────────────────
if ! id -nG "$USER" | grep -qw input; then
    echo "Adding $USER to the input group..."
    sudo usermod -aG input "$USER"
    echo "NOTE: Log out and back in for the group change to take effect."
else
    echo "[ok] $USER is in the input group"
fi

# ── 3. Install systemd user service ──────────────────────────────────────────
SERVICE_DIR="${HOME}/.config/systemd/user"
mkdir -p "$SERVICE_DIR"
cp "$(dirname "$0")/cat-detector.service" "$SERVICE_DIR/"
systemctl --user daemon-reload
systemctl --user enable --now cat-detector.service
echo "[ok] Service enabled: cat-detector.service"

# ── 4. Remind about optional meow sound ──────────────────────────────────────
MEOW="$(dirname "$0")/assets/meow.wav"
if [[ ! -f "$MEOW" ]]; then
    echo
    echo "Tip: Drop a meow.wav into assets/ for audio alerts when a cat is detected."
fi

echo
echo "=== Installation complete! ==="
echo "  Test (cat mode) :  python3 cat_detector.py --sensitivity high"
echo "  Test (toddler)  :  python3 cat_detector.py --toddler"
echo "  No auto-lock    :  python3 cat_detector.py --no-lock"
echo "  Status          :  systemctl --user status cat-detector"
echo "  Logs            :  journalctl --user -u cat-detector -f"
