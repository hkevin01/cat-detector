# cat-detector 🐱

> Detects when a cat walks on your keyboard and responds with a desktop notification — and optionally locks your screen.

## How it works

Monitors raw keyboard events via `evdev`. A **cat walk** produces a distinct signature:

- Many **unique keys** pressed in a short sliding time window (unlike typing, which follows normal linguistic distributions)
- Keys spread across **multiple spatial zones** of the keyboard simultaneously
- High key-press **rate** with low semantic structure
- Optional detection of kneading (rapid repeat of single key)

When the cat score exceeds the threshold, you get a snarky desktop notification — and optionally a screen lock so the cat cannot proceed with its inevitable `git push --force`.

## Requirements

- Linux (Wayland or X11)
- Python 3.11+
- `python-evdev` — `sudo pacman -S python-evdev` on Arch
- User in the `input` group — `sudo usermod -aG input $USER`, then re-login
- `libnotify` for desktop notifications — `sudo pacman -S libnotify`

## Quick start

```bash
# Clone
git clone https://github.com/YOURNAME/cat-detector.git
cd cat-detector

# One-command install (adds input group, installs service)
bash install.sh

# Run manually to test detection
python3 cat_detector.py --sensitivity high

# With screen lock on detection
python3 cat_detector.py --lock

# With meow sound (drop a meow.wav in assets/)
python3 cat_detector.py --sound

# All options
python3 cat_detector.py --lock --sound --sensitivity medium
```

## Sensitivity levels

| Level    | Min unique keys | Min rate | Keyboard spread |
|----------|----------------|----------|-----------------|
| `low`    | 22             | 9.0/s    | 60%             |
| `medium` | 15             | 6.5/s    | 50%             |
| `high`   | 10             | 4.5/s    | 35%             |

Use `high` if your cat is a dainty stepper. Use `low` to avoid false positives from fast human typing.

## Service management

```bash
# Check if it's running
systemctl --user status cat-detector

# Restart after changing settings in the service file
systemctl --user restart cat-detector

# Watch live detection logs
journalctl --user -u cat-detector -f

# Disable
systemctl --user disable --now cat-detector
```

## Adding a meow sound

Drop any `.wav` named `meow.wav` into `assets/` and run with `--sound`. Free samples available on freesound.org — search for "cat meow".

## Project structure

```
cat-detector/
├── cat_detector.py        # Core detection engine
├── install.sh             # One-command installer
├── cat-detector.service   # Systemd user service template
├── assets/
│   └── meow.wav           # (optional) sound effect
├── pyproject.toml
└── README.md
```

## License

MIT
