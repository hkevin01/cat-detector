#!/usr/bin/env python3
"""
cat-detector: Watches keyboard events for cat-on-keyboard signatures.

Detection algorithm:
  - Sliding 2-second window of key-down events
  - "Cat score" = unique keys pressed / time window (keys/sec)
  - A cat walk produces many unique keys fast, spread across the full layout
  - Additional heuristics: consecutive same-key repeats (kneading), sudden burst
  - When cat_score > THRESHOLD, trigger alert, optional lock, then cooldown

Usage:
  python cat_detector.py [--lock] [--sound] [--sensitivity medium]
"""

import argparse
import collections
import logging
import os
import shutil
import subprocess
import sys
import time
from collections import deque

try:
    import evdev
    from evdev import InputDevice, categorize, ecodes
except ImportError:
    print("Error: python-evdev not installed. Run: sudo pacman -S python-evdev")
    sys.exit(1)

# ── tunables ──────────────────────────────────────────────────────────────────

SENSITIVITY = {
    "low":    {"min_keys": 22, "min_rate": 9.0,  "spread": 0.60},
    "medium": {"min_keys": 15, "min_rate": 6.5,  "spread": 0.50},
    "high":   {"min_keys": 10, "min_rate": 4.5,  "spread": 0.35},
}

WINDOW_SECS   = 2.5   # sliding time window
COOLDOWN_SECS = 45    # silence after a detection

# Full keyboard spread buckets: left/center/right × top/home/bottom
# Key codes grouped into 9 spatial zones
ZONE_KEYS = {
    "top-left":     {1,2,3,4,5,16,17,18,19,20,30,31,32},
    "top-center":   {6,7,21,22,33,34},
    "top-right":    {8,9,10,11,12,13,14,15,23,24,25,26,27,35,36,37,38,39,40},
    "home-left":    {30,31,32,44,45,46},
    "home-center":  {33,34,47,48},
    "home-right":   {35,36,37,38,39,40,49,50,51,52},
    "bottom-left":  {44,45,46,2,3,4,5},
    "bottom-center":{47,48,49,57},    # includes space
    "bottom-right": {50,51,52,53,54,55,56},
}

CAT_MESSAGES = [
    "🐱 CAT ALERT: A feline has claimed your keyboard as a bed.",
    "🐾 Paw detected on keyboard. Dignity: compromised.",
    "😸 Your cat is clearly more important than what you were doing.",
    "🐈 Keyboard invasion in progress. Resistance is futile.",
    "😾 Cat says: your work is NOT important right now.",
    "🐱 Input from cat detected. Quality of work may improve.",
    "🐾 Unscheduled cat meeting commenced on keyboard.",
    "🐈‍⬛ Error 404: Keyboard not found (buried under cat).",
    "😻 Your laptop now belongs to the cat. Please negotiate.",
    "🐱 Cat-initiated git commit: 'asdfghjkl;' - pushing to main.",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [cat-detector] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("cat-detector")


def find_keyboards():
    """Return all evdev devices that look like keyboards."""
    keyboards = []
    for path in evdev.list_devices():
        try:
            dev = InputDevice(path)
            cap = dev.capabilities()
            # Must have EV_KEY and a reasonable number of keys
            if ecodes.EV_KEY in cap and len(cap[ecodes.EV_KEY]) > 20:
                keyboards.append(dev)
                log.info("Found keyboard: %s (%s)", dev.name, path)
        except (PermissionError, OSError):
            pass
    return keyboards


def zone_spread(keys: set) -> float:
    """How many of the 9 spatial zones are touched? Returns 0.0–1.0."""
    touched = sum(1 for zone_set in ZONE_KEYS.values() if keys & zone_set)
    return touched / len(ZONE_KEYS)


def notify(message: str, urgency: str = "critical"):
    """Send a desktop notification."""
    if shutil.which("notify-send"):
        subprocess.run(
            ["notify-send", "-u", urgency, "-t", "8000",
             "-i", "input-keyboard", "Cat Detected! 🐱", message],
            check=False,
        )
    else:
        log.warning("notify-send not found — printing to console only")
    print(f"\n{'='*60}\n{message}\n{'='*60}\n")


def play_meow():
    """Play a meow sound if a sample is available."""
    sample = os.path.join(os.path.dirname(__file__), "assets", "meow.wav")
    if not os.path.exists(sample):
        return
    for player in ("paplay", "aplay", "pw-play"):
        if shutil.which(player):
            subprocess.Popen([player, sample],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return


def lock_screen():
    """Lock the KDE/Wayland session."""
    for cmd in (["loginctl", "lock-session"],
                ["kscreenlocker_greet", "--forcelock"],
                ["xdg-screensaver", "lock"]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, check=False)
            return
    log.warning("No screen locker found — skipping lock")


import random

def run(args):
    import asyncio

    thresh = SENSITIVITY[args.sensitivity]
    keyboards = find_keyboards()
    if not keyboards:
        log.error(
            "No accessible keyboards found. "
            "Make sure you are in the 'input' group: sudo usermod -aG input $USER"
        )
        sys.exit(1)

    # key_times[keycode] -> deque of event timestamps
    key_times: dict[int, deque] = collections.defaultdict(lambda: deque(maxlen=200))
    last_detection = 0.0

    log.info(
        "Cat detector running | sensitivity=%s (keys≥%d, rate≥%.1f/s, spread≥%.0f%%)",
        args.sensitivity,
        thresh["min_keys"],
        thresh["min_rate"],
        thresh["spread"] * 100,
    )

    async def watch(dev):
        nonlocal last_detection
        async for event in dev.async_read_loop():
            if event.type != ecodes.EV_KEY:
                continue
            ke = categorize(event)
            if ke.keystate != ke.key_down:
                continue

            now = time.monotonic()
            code = event.code
            key_times[code].append(now)

            # Prune all old timestamps across all keys
            cutoff = now - WINDOW_SECS
            active_keys = set()
            for c, times in key_times.items():
                while times and times[0] < cutoff:
                    times.popleft()
                if times:
                    active_keys.add(c)

            total_events = sum(len(q) for q in key_times.values() if q)
            unique_keys  = len(active_keys)
            rate         = total_events / WINDOW_SECS
            spread       = zone_spread(active_keys)

            if (
                unique_keys >= thresh["min_keys"]
                and rate     >= thresh["min_rate"]
                and spread   >= thresh["spread"]
                and (now - last_detection) > COOLDOWN_SECS
            ):
                last_detection = now
                msg = random.choice(CAT_MESSAGES)
                log.warning(
                    "CAT DETECTED! keys=%d rate=%.1f/s spread=%.0f%%",
                    unique_keys, rate, spread * 100,
                )
                notify(msg)
                if args.sound:
                    play_meow()
                if args.lock:
                    time.sleep(2)
                    lock_screen()

                # Clear the window so we don't double-fire
                key_times.clear()

    async def main():
        await asyncio.gather(*[watch(kb) for kb in keyboards])

    asyncio.run(main())


def main():
    parser = argparse.ArgumentParser(
        description="Detect when a cat walks on your keyboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--lock", action="store_true",
        help="Lock the screen when a cat is detected",
    )
    parser.add_argument(
        "--sound", action="store_true",
        help="Play a meow sound on detection (needs assets/meow.wav)",
    )
    parser.add_argument(
        "--sensitivity", choices=["low", "medium", "high"], default="medium",
        help="Detection sensitivity (default: medium)",
    )
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
