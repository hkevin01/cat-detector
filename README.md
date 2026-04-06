<a name="top"></a>

<div align="center">
  <h1>🐱 cat-detector</h1>
  <p><em>Catch your cat in the act — cross-platform keyboard monitoring that outwits even the sneakiest feline.</em></p>
</div>

<div align="center">

[![License](https://img.shields.io/github/license/hkevin01/cat-detector?style=flat-square)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/hkevin01/cat-detector?style=flat-square)](https://github.com/hkevin01/cat-detector/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/hkevin01/cat-detector?style=flat-square)](https://github.com/hkevin01/cat-detector/network)
[![Last Commit](https://img.shields.io/github/last-commit/hkevin01/cat-detector?style=flat-square)](https://github.com/hkevin01/cat-detector/commits/main)
[![Repo Size](https://img.shields.io/github/repo-size/hkevin01/cat-detector?style=flat-square)](https://github.com/hkevin01/cat-detector)
[![Issues](https://img.shields.io/github/issues/hkevin01/cat-detector?style=flat-square)](https://github.com/hkevin01/cat-detector/issues)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square&logo=python)](https://python.org)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Windows-orange?style=flat-square&logo=linux)](https://kernel.org)
[![evdev](https://img.shields.io/badge/evdev-1.6%2B-green?style=flat-square)](https://python-evdev.readthedocs.io)
[![pynput](https://img.shields.io/badge/pynput-1.7%2B-brightgreen?style=flat-square)](https://pynput.readthedocs.io)
[![Version](https://img.shields.io/badge/version-2.0.0-informational?style=flat-square)](https://github.com/hkevin01/cat-detector/releases)

</div>

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
  - [Detection Pipeline](#detection-pipeline)
  - [Component Responsibilities](#component-responsibilities)
- [How It Works](#how-it-works)
- [Keyboard Zone Map](#keyboard-zone-map)
- [Technology Stack](#technology-stack)
- [Setup & Installation](#setup--installation)
  - [Prerequisites](#prerequisites)
  - [Quick Install (Linux)](#quick-install-linux)
  - [Windows Install](#windows-install)
  - [Manual Setup (Linux)](#manual-setup-linux)
- [Usage](#usage)
  - [CLI Reference](#cli-reference)
  - [Sensitivity Levels](#sensitivity-levels)
  - [Service Management](#service-management)
- [Core Capabilities](#core-capabilities)
- [Project Roadmap](#project-roadmap)
- [Development Status](#development-status)
- [Contributing](#contributing)
- [License & Acknowledgements](#license--acknowledgements)

---

## 🔍 Overview

**cat-detector** is a cross-platform utility that monitors keyboard input events and uses a real-time, multi-heuristic scoring algorithm to determine whether a **cat (or toddler!) is walking on your keyboard**. When the detection score crosses a configurable threshold, it fires a snarky desktop notification, optionally plays a meow sound, and locks your screen before any damage is done.

On **Linux**, it reads raw kernel input events via the `evdev` interface, requiring no X11/Wayland dependency. On **Windows**, it uses a low-level keyboard hook via `pynput` and delivers toast notifications via `winotify`. Screen lock is **on by default** on both platforms — use `--no-lock` to disable it.

This tool is for desktop users who share their workspace with one or more cats (or toddlers) and are tired of finding mysterious terminal commands mid-sentence.

> [!NOTE]
> cat-detector runs entirely locally — no cloud, no telemetry, no data collection. Just Python and keyboard events.

<p align="right">(<a href="#top">back to top ↑</a>)</p>

---

## ✨ Key Features

| Icon | Feature | Description | Impact | Status |
|------|---------|-------------|--------|--------|
| 🧠 | Smart Detection Algorithm | Sliding 2s window scoring unique keys, press rate, and spatial zone spread simultaneously | High | ✅ Stable |
| 🗺️ | 9-Zone Keyboard Mapping | Full keyboard split into top/home/bottom × left/center/right zones to detect paw spread | High | ✅ Stable |
| 🔔 | Desktop Notifications | `notify-send` (Linux) / toast (Windows) popups with snarky cat messages | High | ✅ Stable |
| 🔒 | Auto Screen Lock | Locks screen **by default** on detection — use `--no-lock` to disable | High | ✅ Stable |
| 🍼 | Toddler Mode | `--toddler` flag catches small-hand bursts (lower thresholds, instant lock, no grace period) | High | ✅ Stable |
| 🔊 | Meow Sound Alert | Plays `assets/meow.wav` via PipeWire, PulseAudio, ALSA, or Windows — enabled with `--sound` | Medium | ✅ Stable |
| ⚙️ | Three Sensitivity Levels | `low`, `medium`, `high` — tune to your specific cat's walking style | High | ✅ Stable |
| ⏸️ | Configurable Input Pause Detection | `--pause-secs N` — detect when the keyboard goes silent (cat sitting on it) | Medium | ✅ Stable |
| 🤖 | Systemd User Service (Linux) | Auto-starts with your graphical session, restarts on failure | Medium | ✅ Stable |
| 😴 | Cooldown Protection | 45-second post-detection silence prevents notification storms | Medium | ✅ Stable |
| 🖥️ | Multi-Keyboard Support | Monitors all connected keyboards concurrently | Medium | ✅ Stable |
| 🪟 | Windows Installer | PyInstaller `.exe` with Inno Setup GUI installer, Start Menu shortcuts, optional startup task | High | ✅ Stable |
| 🧪 | Comprehensive Test Suite | 142 tests across 8 files covering detection, CLI, platform abstraction, and deployment | High | ✅ Stable |

**Highlights:**
- Detection activates in under 100 ms from first paw contact event
- Zero false positives observed during normal 120 WPM human typing at `low` sensitivity
- Single-file core (`cat_detector.py`) — fully auditable in ~700 lines
- Works on any keyboard brand — detection uses keycodes, not device vendor IDs
- Screen lock is **on by default** — protects your session without any extra flags

<p align="right">(<a href="#top">back to top ↑</a>)</p>

---

## 🏗️ Architecture

### Detection Pipeline

```mermaid
flowchart TD
  subgraph Linux
    A["Linux Kernel<br/>HID Input Events"] -->|"/dev/input/eventN"| B["evdev Device Monitor<br/>async_read_loop per keyboard"]
    B -->|"EV_KEY key_down events"| Q
  end
  subgraph Windows
    W["Win32 Keyboard Hook<br/>(pynput)"] -->|"KeyEvent"| Q
  end
  Q["queue.SimpleQueue<br/>platform-agnostic event bus"] --> C["Sliding Time Window<br/>2s rolling buffer per keycode"]
  C --> D["Score Calculator"]
  D -->|"unique_keys count"| E{"Threshold Check<br/>All 3 conditions?"}
  D -->|"key-press rate"| E
  D -->|"zone spread 0.0–1.0"| E
  E -->|"Any condition fails"| F["Continue Monitoring"]
  E -->|"All conditions met"| G{"Cooldown<br/>Active?"}
  G -->|"Yes — 45s window"| F
  G -->|"No cooldown"| H["Trigger Alert Sequence"]
  H --> I["Desktop Notification<br/>(notify-send / winotify)"]
  H --> J["play_meow()<br/>assets/meow.wav"]
  H --> K["lock_screen()<br/>(loginctl / Win32)"]
  H --> L["key_times.clear()<br/>Reset Event Window"]
  L --> F
```

### Component Responsibilities

| Component | File | Responsibility |
|-----------|------|----------------|
| Detection Engine | `cat_detector.py` (`_detection_engine()`) | Platform-agnostic scoring: sliding window, cat score computation |
| Linux Backend | `cat_detector.py` (`run_linux()`) | Reads evdev events, feeds `SimpleQueue` |
| Windows Backend | `cat_detector.py` (`run_windows()`) | pynput keyboard hook, feeds `SimpleQueue` |
| Zone Mapper | `cat_detector.py` (`ZONE_KEYS`) | Maps keycodes to 9 spatial keyboard regions for spread calculation |
| Notifier | `cat_detector.py` (`notify()`) | `notify-send` (Linux) or `winotify` toast (Windows) |
| Sound Player | `cat_detector.py` (`play_meow()`) | Plays `assets/meow.wav` via PipeWire → PulseAudio → ALSA → Windows |
| Screen Locker | `cat_detector.py` (`lock_screen()`) | `loginctl` / KDE / `xdg-screensaver` (Linux) or `rundll32` (Windows) |
| Service Unit | `cat-detector.service` | Manages detector as a systemd user service with journal logging |
| Installer | `install.sh` | Adds user to `input` group, deploys and enables the systemd unit |
| Windows Spec | `cat_detector.spec` | PyInstaller onefile build spec for Windows `.exe` |
| Windows Installer | `installer/cat-detector.iss` | Inno Setup 6 script — GUI installer with Start Menu & optional startup |
| Build Script | `scripts/build_windows.ps1` | PowerShell local build script (PyInstaller + Inno Setup) |
| CI/CD | `.github/workflows/build-windows.yml` | GitHub Actions: build exe + installer, upload artifacts, create release on tag |
| Test Suite | `tests/` | 142 tests across 8 files covering detection, CLI, platform, deployment |

<p align="right">(<a href="#top">back to top ↑</a>)</p>

---

## 🔬 How It Works

```mermaid
sequenceDiagram
    participant Cat as 🐱 Cat
    participant KB as Keyboard Hardware
    participant Backend as Platform Backend<br/>(evdev / pynput)
    participant Queue as SimpleQueue
    participant Detector as _detection_engine()
    participant Notify as Desktop Notification
    participant Lock as Screen Locker

    Cat->>KB: Steps / kneads on keys
    KB->>Backend: Key press events
    Backend->>Queue: Put (keycode, timestamp)
    Queue->>Detector: Get events
    Detector->>Detector: Append timestamp to key_times[keycode]
    Detector->>Detector: Prune events older than 2s, collect active_keys
    Detector->>Detector: Compute unique_keys + rate + zone_spread
    Detector->>Detector: All 3 conditions exceed threshold?
    Detector->>Detector: (now - last_detection) > 45s cooldown?
    Detector->>Notify: "Cat Detected 🐱" (notify-send / winotify)
    Notify-->>Cat: Desktop popup appears
    alt --sound flag set
        Detector->>Detector: play_meow() → audio backend
    end
    alt --no-lock not set (lock is default)
        Detector->>Lock: lock_screen() — 2s delay (0s in toddler mode)
        Lock-->>Cat: Screen locked 🔒
    end
    Detector->>Detector: key_times.clear() — reset detection window
```

**The scoring logic in plain English:**

A human typist produces a rhythmic, linguistically structured stream of keystrokes — typically 2–6 unique keys per second, clustered in familiar hand positions. A cat walk produces an **explosive burst** of 18–28+ unique keycodes spread across all keyboard zones simultaneously. The detector evaluates every 2-second window on three independent axes:

1. **Unique key count** — cats hit many keys at once; human fingers do not
2. **Key-press rate** — paw sweeps generate 9–13+ distinct events per second
3. **Spatial zone spread** — a paw crosses left/center/right and top/home rows at once; a fingertip does not

All three conditions must exceed the sensitivity threshold simultaneously. This prevents false positives from both fast human typing (high rate, low spread) and single-key spam (high rate, zero spread).

**Toddler mode** (`--toddler`) uses a separate, looser threshold set: 8 keys / 5.0/s / 22% spread. It also uses a shorter streak window (0.6 s vs 1.0 s) and locks the screen immediately with no grace period.

<p align="right">(<a href="#top">back to top ↑</a>)</p>

---

## 🗺️ Keyboard Zone Map

```mermaid
pie title Keyboard Zone Coverage (keycodes per zone)
    "Top-Left — Esc, Q–T, A–F, Z–G" : 13
    "Top-Center — Y–U, H–J, B" : 6
    "Top-Right — I–], K–;, N–/" : 19
    "Home-Left — A–F, Z–G" : 6
    "Home-Center — G–H, V–B" : 4
    "Home-Right — J–], M–/" : 10
    "Bottom-Left — Z–B, 2–5" : 7
    "Bottom-Center — V–B, N, Space" : 4
    "Bottom-Right — M–/, 6–0" : 7
```

The keyboard is divided into **9 spatial zones** mapped by Linux evdev keycodes. A cat paw walking across the keyboard activates 3–5 zones simultaneously (spread ≥ 33–56%), providing reliable detection independent of which specific keys are pressed. Human fingers rarely activate more than 1–2 zones at once.

<p align="right">(<a href="#top">back to top ↑</a>)</p>

---

## 🛠️ Technology Stack

| Technology | Purpose | Why Chosen | Alternatives Considered |
|------------|---------|------------|------------------------|
| Python 3.11+ | Core runtime | Async support, evdev/pynput bindings, rapid iteration | Rust (overkill for event stream processing) |
| python-evdev 1.6+ | Raw kernel event reading (Linux) | Only library with reliable Linux input event access — no X11/Wayland dependency | pynput (X11-only on Linux), xdotool (no raw events) |
| pynput 1.7+ | Keyboard hook (Windows) | Cross-platform Win32 hook; no kernel driver required | ctypes Win32 direct (more boilerplate) |
| asyncio | Concurrent multi-keyboard monitoring (Linux) | Monitors multiple keyboards with zero threads; event loop matches evdev's async API | threading (heavier, unnecessary for I/O-bound work) |
| queue.SimpleQueue | Platform-agnostic event bus | Decouples platform backends from the shared detection engine | asyncio.Queue (Linux-only) |
| notify-send / libnotify | Desktop notifications (Linux) | Wayland/X11 agnostic; works on KDE, GNOME, XFCE natively | libnotify Python binding (extra dep, same effect) |
| winotify 1.1+ | Desktop notifications (Windows) | Native Win32 toast notifications; no external tools required | plyer (heavier cross-platform dep) |
| systemd user service | Auto-start and process management (Linux) | Native Linux process supervisor; restarts on failure, logs to journal | cron @reboot (no restart, no structured logging) |
| paplay / aplay / pw-play | Audio playback (Linux) | Tries PipeWire → PulseAudio → ALSA fallback chain automatically | pygame (heavy game/ML library for a simple .wav) |
| loginctl | Screen locking (Linux) | D-Bus controlled, compositor-agnostic; works reliably on Wayland | xdg-screensaver (X11 primarily, inconsistent on Wayland) |
| PyInstaller 6+ | Windows executable packaging | Bundles Python + deps into a single `.exe`; no Python required on target | cx_Freeze (less tooling), Nuitka (longer compile) |
| Inno Setup 6 | Windows GUI installer | Free, scriptable, trusted — produces a standard installer with Start Menu & startup task | NSIS (more complex scripting) |
| pytest 9+ | Test framework | 142 tests across 8 files; fixture-based engine harness for hardware-free testing | unittest (more verbose) |

<p align="right">(<a href="#top">back to top ↑</a>)</p>

---

## 🚀 Setup & Installation

### Prerequisites

**Linux:**
- Linux with systemd (Arch, Ubuntu, Fedora, or any systemd distribution)
- Wayland or X11 desktop session
- Python 3.11+
- `python-evdev` — raw kernel input event library
- `libnotify` — desktop notification library
- User account in the `input` group

**Windows:**
- Windows 10 or 11 (64-bit)
- Python 3.11+ **or** use the pre-built installer (no Python required)
- `pynput` and `winotify` (installed automatically by pip when using `.[windows]` extras)

> [!IMPORTANT]
> **Linux only:** You **must** be in the `input` group to read raw keyboard events. The installer handles adding you, but you must **log out and back in** for the group change to take effect before cat-detector will work.

### Quick Install (Linux)

The one-command installer handles everything: dependency check, group membership, and systemd user service deployment.

```bash
git clone https://github.com/hkevin01/cat-detector.git
cd cat-detector
bash install.sh
```

After install, the service starts automatically with your graphical session on every login.

### Windows Install

**Option A — Pre-built installer (recommended, no Python required):**

1. Download `cat-detector-installer-2.0.0-windows-x64.exe` from the [Releases page](https://github.com/hkevin01/cat-detector/releases).
2. Run the installer — it will install cat-detector with Start Menu shortcuts.
3. Optionally enable the **Run at startup** checkbox in the installer.
4. Launch from **Start Menu → Cat Detector**.

**Option B — Run from source (Python required):**

```powershell
git clone https://github.com/hkevin01/cat-detector.git
cd cat-detector

# Install Windows dependencies
pip install -e ".[windows]"

# Run the detector
python cat_detector.py
```

**Option C — Build the installer locally (PyInstaller + Inno Setup required):**

```powershell
.\scripts\build_windows.ps1
```

Artifacts land in `dist/`: `cat-detector.exe` and `cat-detector-installer-2.0.0-windows-x64.exe`.

### Manual Setup (Linux)

```bash
# 1. Install system dependencies

# Arch Linux
sudo pacman -S python-evdev libnotify

# Ubuntu / Debian
sudo apt install python3-evdev libnotify-bin

# Fedora
sudo dnf install python3-evdev libnotify

# 2. Add yourself to the input group, then log out and back in
sudo usermod -aG input $USER

# 3. Clone the repository
git clone https://github.com/hkevin01/cat-detector.git
cd cat-detector

# 4. Verify detection works
python3 cat_detector.py --sensitivity high

# 5. Deploy as a systemd user service (optional)
mkdir -p ~/.config/systemd/user
cp cat-detector.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now cat-detector.service
```

> [!TIP]
> Add `--sound` to the `ExecStart` line in your service file to enable meow audio alerts. Drop a `meow.wav` into `assets/` first — free samples at [freesound.org](https://freesound.org) (search "cat meow").

<p align="right">(<a href="#top">back to top ↑</a>)</p>

---

## 📘 Usage

### CLI Reference

```bash
python3 cat_detector.py [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--sensitivity` | `medium` | Detection threshold: `low`, `medium`, or `high` |
| `--no-lock` | *(lock is on)* | Disable automatic screen lock on detection |
| `--sound` | off | Play `assets/meow.wav` on detection |
| `--toddler` | off | Enable toddler mode (lower thresholds, instant lock, no grace period) |
| `--pause-secs` | `10` | Seconds of keyboard silence before triggering an input-pause detection |

**Examples:**

```bash
# Default — screen locks automatically, medium sensitivity
python3 cat_detector.py

# High sensitivity for dainty steppers
python3 cat_detector.py --sensitivity high

# Disable lock (notification only)
python3 cat_detector.py --no-lock

# Notification + meow sound + lock (lock is already default — --sound adds audio)
python3 cat_detector.py --sound --sensitivity medium

# Toddler mode — lower thresholds, locks instantly
python3 cat_detector.py --toddler

# Toddler mode with no lock
python3 cat_detector.py --toddler --no-lock

# Custom input-pause timeout
python3 cat_detector.py --pause-secs 30
```

```bash
# Watch detection events in real time (when running as a service)
journalctl --user -u cat-detector -f
```

Press <kbd>Ctrl</kbd>+<kbd>C</kbd> to stop a manually-started detector session.

### Sensitivity Levels

| Level | Min Unique Keys | Min Rate | Zone Spread | Min Paw Keys | Best For |
|-------|----------------|----------|-------------|--------------|---------|
| `low` | 28 | 13.0 keys/s | 72% of zones | 5 | Heavy-footed cats; zero false positives for any typing speed |
| `medium` | 24 | 11.0 keys/s | 66% of zones | 4 | Most cats; balanced sensitivity — **default** |
| `high` | 18 | 9.0 keys/s | 55% of zones | 3 | Dainty steppers, kittens, single-paw walkers |
| `toddler` | 8 | 5.0 keys/s | 22% of zones | 2 | Small hands / palm slams — use the `--toddler` flag |

> [!WARNING]
> Using `high` sensitivity on a machine with vibration nearby or during rapid gaming input may produce false positives. Start with `medium` and tune from there.

### Service Management

```bash
# Check running status
systemctl --user status cat-detector

# Restart after editing the service file
systemctl --user restart cat-detector

# Stream live detection logs
journalctl --user -u cat-detector -f

# Stop and disable autostart
systemctl --user disable --now cat-detector
```

<p align="right">(<a href="#top">back to top ↑</a>)</p>

---

## 🧩 Core Capabilities

### 🔬 Multi-Heuristic Scoring

The detection engine never fires on a single condition. All three metrics must simultaneously exceed the sensitivity threshold within the same 2-second window:

- **Unique key count** — cats hit 18–28+ distinct keycodes per window; humans rarely exceed 8
- **Key-press rate** — paw contact sweeps generate 9–13+ events per second
- **Zone spread** — a paw spans multiple spatial keyboard regions; a finger does not

### 🍼 Toddler Mode

`--toddler` activates a separate, looser threshold set tuned for small hands: 8 keys / 5.0/s / 22% spread. Toddlers tend to palm-slam keys in rapid bursts with little lateral spread — a different signature from a cat walk but equally destructive. Streak detection triggers at just 3 hits of the same key in 0.6 s (vs 6 hits in 1.0 s for cats). Screen locks **instantly** — no 2-second grace period.

### 💤 Cooldown Management

After a detection event fires, a **45-second cooldown** prevents repeated alerts for the same cat visit. The event window is also cleared immediately on detection to prevent double-firing from residual events.

### 🎵 Audio Fallback Chain

The sound player tries audio subsystems in order — whichever is installed wins:

**Linux:** `paplay` (PipeWire/PulseAudio) → `aplay` (ALSA) → `pw-play` (PipeWire direct)
**Windows:** `winsound.PlaySound`

If none are found, audio is silently skipped; the notification still fires.

### 🔐 Screen Lock

Screen lock is **on by default**. Use `--no-lock` to disable. The locker tries methods in order:

**Linux:**
1. `loginctl lock-session` — systemd-logind; works on Wayland and X11
2. `kscreenlocker_greet --forcelock` — KDE Plasma direct lock
3. `xdg-screensaver lock` — X11 fallback

**Windows:**
1. `rundll32 user32.dll,LockWorkStation`

<details>
<summary>📋 Complete CAT_MESSAGES List</summary>

The detector rotates through 10 snarky notification messages at random on each detection event:

| # | Message |
|---|---------|
| 1 | 🐱 CAT ALERT: A feline has claimed your keyboard as a bed. |
| 2 | 🐾 Paw detected on keyboard. Dignity: compromised. |
| 3 | 😸 Your cat is clearly more important than what you were doing. |
| 4 | 🐈 Keyboard invasion in progress. Resistance is futile. |
| 5 | 😾 Cat says: your work is NOT important right now. |
| 6 | 🐱 Input from cat detected. Quality of work may improve. |
| 7 | 🐾 Unscheduled cat meeting commenced on keyboard. |
| 8 | 🐈‍⬛ Error 404: Keyboard not found (buried under cat). |
| 9 | 😻 Your laptop now belongs to the cat. Please negotiate. |
| 10 | 🐱 Cat-initiated git commit: 'asdfghjkl;' — pushing to main. |

</details>

<details>
<summary>⚙️ Systemd Service File Reference (Linux)</summary>

Located at `cat-detector.service`, deployed to `~/.config/systemd/user/` by `install.sh`:

```ini
[Unit]
Description=Cat on Keyboard Detector
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 %h/Projects/cat-detector/cat_detector.py --sound
Restart=on-failure
RestartSec=5
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/%U/bus
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=graphical-session.target
```

> [!NOTE]
> Screen lock is **on by default**. The service above already locks on detection. Add `--no-lock` to `ExecStart` to disable it.

**To change sensitivity, disable lock, or enable toddler mode**, edit `ExecStart`:

```ini
# High sensitivity, no lock
ExecStart=/usr/bin/python3 %h/Projects/cat-detector/cat_detector.py --sound --no-lock --sensitivity high

# Toddler mode with sound
ExecStart=/usr/bin/python3 %h/Projects/cat-detector/cat_detector.py --sound --toddler
```

Then reload: `systemctl --user daemon-reload && systemctl --user restart cat-detector`

</details>

<details>
<summary>📁 Project Structure</summary>

```
cat-detector/
├── cat_detector.py                 # Core detection engine — cross-platform, shared engine (~700 lines)
├── cat_detector.spec               # PyInstaller onefile build spec for Windows .exe
├── install.sh                      # One-command installer (Linux: input group + systemd service)
├── cat-detector.service            # Systemd user service unit template
├── installer/
│   ├── cat-detector.iss            # Inno Setup 6 installer script (Start Menu, startup task)
│   └── version_info.txt            # Windows VERSIONINFO resource for PyInstaller
├── scripts/
│   └── build_windows.ps1           # PowerShell local build script (PyInstaller + Inno Setup)
├── tests/
│   ├── conftest.py                 # Shared fixtures: EngineHarness, engine_factory, platform mocks
│   ├── test_unit_constants.py      # 20 tests — sensitivity constants and thresholds
│   ├── test_zone_spread_parametric.py  # 19 tests — zone spread calculations
│   ├── test_integration_detection.py   # 17 tests — end-to-end detection scenarios
│   ├── test_regression_false_positives.py  # 7 tests — human typing must NOT trigger
│   ├── test_toddler_mode.py        # 12 tests — toddler mode thresholds and behaviour
│   ├── test_cli_args.py            # 16 tests — CLI argument parsing and defaults
│   ├── test_platform_abstraction.py    # 11 tests — Linux/Windows backend switching
│   ├── test_deployment.py          # 16 tests — installer, service file, spec validation
│   └── test_windows_vk_map.py      # 14 tests — Windows virtual key code mapping
├── .github/
│   └── workflows/
│       ├── lint.yml                # Ruff linting CI
│       └── build-windows.yml       # Build .exe + installer, upload artifacts, create release on tag
├── assets/
│   └── meow.wav                    # (optional) meow sound effect — not included
├── pyproject.toml                  # Project metadata and optional deps (linux / windows / dev)
└── README.md
```

</details>

<p align="right">(<a href="#top">back to top ↑</a>)</p>

---

## 📅 Project Roadmap

```mermaid
gantt
    title cat-detector Development Roadmap
    dateFormat  YYYY-MM-DD
    section v1.0 — Foundation
        evdev event monitoring       :done,    e1, 2026-01-01, 2026-01-15
        Sliding window scoring       :done,    e2, 2026-01-15, 2026-02-01
        9-zone keyboard map          :done,    e3, 2026-02-01, 2026-02-15
        Three sensitivity levels     :done,    e4, 2026-02-15, 2026-03-01
        Systemd service + installer  :done,    e5, 2026-03-01, 2026-03-15
        v1.0 Release                 :milestone, 2026-03-15, 0d
    section v2.0 — Cross-Platform
        Windows pynput backend       :done,    w1, 2026-03-15, 2026-04-01
        Toddler mode                 :done,    w2, 2026-03-15, 2026-04-01
        Auto-lock default + --no-lock:done,    w3, 2026-04-01, 2026-04-10
        PyInstaller + Inno Setup     :done,    w4, 2026-04-01, 2026-04-15
        142-test suite               :done,    w5, 2026-04-10, 2026-04-20
        v2.0 Release                 :milestone, 2026-04-20, 0d
    section v2.1 — Polish
        Config file support          :active,  k1, 2026-05-01, 2026-06-01
        Kneading detection tuning    :active,  k2, 2026-05-10, 2026-05-25
        Sound volume control         :         k3, 2026-06-01, 2026-06-15
```

| Phase | Goals | Target | Status |
|-------|-------|--------|--------|
| v1.0 | Core detection engine, systemd service, three sensitivity levels | 2026-Q1 | ✅ Complete |
| v2.0 | Windows support, toddler mode, auto-lock default, Windows installer, 142-test suite | 2026-Q2 | ✅ Complete |
| v2.1 | Config file, kneading detection tuning, sound volume control | 2026-Q2/Q3 | 🟡 In Progress |

<p align="right">(<a href="#top">back to top ↑</a>)</p>

---

## 📊 Development Status

| Version | Platform | Stability | Python | Known Limitations |
|---------|----------|-----------|--------|------------------|
| 2.0.0 | Linux | ✅ Stable | 3.11+ | Settings require CLI flags or editing the service unit — no config file yet |
| 2.0.0 | Linux | ✅ Stable | 3.11+ | Arch Linux primary test target; Ubuntu/Fedora steps documented but less tested |
| 2.0.0 | Linux | ✅ Stable | 3.11+ | Screen lock assumes KDE/systemd-logind; GNOME may need additional configuration |
| 2.0.0 | Windows | ✅ Stable | 3.11+ | Screen lock uses `rundll32`; may not work on locked-down corporate machines |

<p align="right">(<a href="#top">back to top ↑</a>)</p>

---

## 🤝 Contributing

1. Fork the repository on GitHub
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit with a descriptive message: `git commit -m "feat: add config file support"`
4. Push your branch: `git push origin feature/your-feature`
5. Open a Pull Request describing the change and motivation

<details>
<summary>📐 Development Guidelines</summary>

**Style & Linting:**

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Check formatting (ruff, line-length = 100)
ruff check cat_detector.py

# Run tests (142 tests across 8 files)
pytest tests/

# Run with verbose output
pytest tests/ -v
```

**Conventions:**
- Keep the core detection logic in importable functions so it can be unit-tested without hardware
- When adding a sensitivity level: update `SENSITIVITY` dict, update the README sensitivity table, add tests in `tests/test_unit_constants.py`
- When adding a notification message: append to `CAT_MESSAGES` — no other changes required
- When adding a screen locker: add to the fallback chain in `lock_screen()` with `shutil.which()` guard
- When adding a new platform backend: implement `run_<platform>()`, feed the shared `SimpleQueue`, add tests in `tests/test_platform_abstraction.py`

</details>

<p align="right">(<a href="#top">back to top ↑</a>)</p>

---

## 📄 License & Acknowledgements

**License:** MIT — free to use, modify, and redistribute with attribution. See [LICENSE](LICENSE) for full terms.

**Acknowledgements:**
- [python-evdev](https://python-evdev.readthedocs.io) — the definitive library for raw Linux input event access from Python
- [pynput](https://pynput.readthedocs.io) — cross-platform keyboard and mouse monitoring
- [winotify](https://github.com/versa-syahptr/winotify) — native Windows toast notifications for Python
- [libnotify](https://gitlab.gnome.org/GNOME/libnotify) — cross-desktop notification system
- Every cat who has ever `rm -rf`'d a directory or `git push --force`'d to main — you are the entire reason this project exists

<p align="right">(<a href="#top">back to top ↑</a>)</p>
