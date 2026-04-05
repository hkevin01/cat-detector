#!/usr/bin/env python3
"""
cat-detector: Watches keyboard events for cat-on-keyboard signatures.

Detection algorithm — three independent modes:
  WALK/BURST (key-down events):
    Sliding 2.5-second window; triggers when unique key count, rate, and
    spatial spread across the keyboard all exceed sensitivity thresholds.
    Humans type rhythmically on the home row; cats scatter keys everywhere.
    VETO: if backspace, delete, or navigation keys appear in the window,
    the event is classified as human (cats never press backspace).

  HOLD/SIT (autorepeat events, EV_KEY value=2):
    When a cat stands or sits on keys, those keys auto-repeat at kernel
    rate (~20-30/sec). Triggers when 2+ non-navigation keys repeat
    simultaneously OR one non-navigation key floods 15+ repeats in 2s.
    Backspace, delete, arrows, and other human navigation/editing keys
    are excluded — humans hold those all the time; cats never do.

  PAW PRESS (simultaneous key-down events):
    A cat's paw is wider than a key and lands on several at once. Tracks
    keys physically held right now; triggers when 3–5+ non-modifier,
    non-navigation keys are depressed simultaneously. Catches the exact
    moment a paw touches down, which the other two modes may miss.

  STREAK (same-key repeated rapidly without autorepeat):
    No English word has the same letter 4+ times in a row (e.g. "ffff").
    If one non-navigation key appears 4+ key-down events within 1 second,
    it's classified as a cat pawing at the same spot repeatedly.
    Backspace and space are excluded (humans use those repetitively).

  After any trigger: desktop notification, optional sound/lock, 45-second
  cooldown to prevent double-firing.

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
    # Walk/burst thresholds: high enough that fast home-row typing won't fire.
    # min_paw: simultaneous non-modifier/non-nav keys needed for paw detection.
    "low":    {"min_keys": 25, "min_rate": 10.0, "spread": 0.65, "min_paw": 5},
    "medium": {"min_keys": 18, "min_rate":  7.5, "spread": 0.55, "min_paw": 4},
    "high":   {"min_keys": 12, "min_rate":  5.0, "spread": 0.40, "min_paw": 3},
}

WINDOW_SECS   = 2.5   # sliding time window for walk/burst detection
COOLDOWN_SECS = 45    # silence after a detection

# Same-key streak detection — "ffff" is a cat, not a word
STREAK_WINDOW_SECS = 1.0  # look-back for rapid repeated taps of the same key
STREAK_MIN_COUNT   = 4    # ≥ this many key-down events for same key in window

# Hold / sit detection — cat standing or sitting on key(s) causes autorepeat
HOLD_WINDOW_SECS = 2.0   # look-back window for repeat floods
HOLD_MIN_REPEATS = 15    # single key: ≥ this many repeats in window → cat paw
HOLD_MULTI_KEYS  = 2     # ≥ this many different keys simultaneously repeating…
HOLD_MULTI_MIN   = 5     # …each with at least this many repeats → cat sitting

# Keys humans legitimately hold — excluded from hold/sit and walk detection.
# PawSense insight: "cats have a general disregard for the existence of the
# Backspace key."  Backspace/delete/arrows in the event stream = human.
HUMAN_HOLD_KEYS = {
    14,   # KEY_BACKSPACE  ← strongest human signal; cats never delete
    15,   # KEY_TAB        (alt+tab window cycling)
    57,   # KEY_SPACE      (gaming dash/jump, document scroll)
    102,  # KEY_HOME
    103,  # KEY_UP
    104,  # KEY_PAGEUP
    105,  # KEY_LEFT
    106,  # KEY_RIGHT
    107,  # KEY_END
    108,  # KEY_DOWN
    109,  # KEY_PAGEDOWN
    110,  # KEY_INSERT
    111,  # KEY_DELETE     ← same logic as backspace
}

# Modifier keys: excluded from simultaneous-paw count.
# Ctrl+Shift+Alt combos are human; a cat's paw lands on regular character keys.
MODIFIER_KEYS = {
    29,   # KEY_LEFTCTRL
    42,   # KEY_LEFTSHIFT
    54,   # KEY_RIGHTSHIFT
    56,   # KEY_LEFTALT
    58,   # KEY_CAPSLOCK
    97,   # KEY_RIGHTCTRL
    100,  # KEY_RIGHTALT
    125,  # KEY_LEFTMETA
    126,  # KEY_RIGHTMETA
}

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

    # key_times[keycode]      -> deque of key-DOWN timestamps  (walk detection)
    # key_hold_times[keycode] -> deque of autorepeat timestamps (hold/sit detection)
    # keys_currently_held     -> set of keycodes physically down right now (paw detection)
    key_times:           dict[int, deque] = collections.defaultdict(lambda: deque(maxlen=200))
    key_hold_times:      dict[int, deque] = collections.defaultdict(lambda: deque(maxlen=200))
    keys_currently_held: set[int]         = set()
    last_detection = 0.0

    log.info(
        "Cat detector running | sensitivity=%s "
        "(walk: keys≥%d rate≥%.1f/s spread≥%.0f%%) "
        "(paw: simultaneous≥%d) (hold: repeats≥%d)",
        args.sensitivity,
        thresh["min_keys"], thresh["min_rate"], thresh["spread"] * 100,
        thresh["min_paw"], HOLD_MIN_REPEATS,
    )

    async def watch(dev):
        nonlocal last_detection
        async for event in dev.async_read_loop():
            if event.type != ecodes.EV_KEY:
                continue
            ke = categorize(event)
            now  = time.monotonic()
            code = event.code

            # ── Track physical key state (needed for paw detection) ──────────
            if ke.keystate == ke.key_up:
                keys_currently_held.discard(code)
                continue  # key-up feeds no detector

            # ── Hold / sit detection (autorepeat = cat standing on key) ──────
            if ke.keystate == ke.key_hold:
                # Humans hold backspace, arrows, space constantly — skip those.
                if code not in HUMAN_HOLD_KEYS:
                    key_hold_times[code].append(now)

                    hold_cutoff = now - HOLD_WINDOW_SECS
                    active_held = 0
                    max_repeats = 0
                    for htimes in key_hold_times.values():
                        while htimes and htimes[0] < hold_cutoff:
                            htimes.popleft()
                        n = len(htimes)
                        if n >= HOLD_MULTI_MIN:
                            active_held += 1
                        if n > max_repeats:
                            max_repeats = n

                    if (
                        (active_held >= HOLD_MULTI_KEYS or max_repeats >= HOLD_MIN_REPEATS)
                        and (now - last_detection) > COOLDOWN_SECS
                    ):
                        last_detection = now
                        msg = random.choice(CAT_MESSAGES)
                        log.warning(
                            "CAT DETECTED (sitting/standing)! "
                            "held_keys=%d max_repeats=%d",
                            active_held, max_repeats,
                        )
                        notify(msg)
                        if args.sound:
                            play_meow()
                        if args.lock:
                            time.sleep(2)
                            lock_screen()
                        key_times.clear()
                        key_hold_times.clear()
                        keys_currently_held.clear()
                continue  # autoreps don't feed walk/paw/streak detectors

            # key_down from here ─────────────────────────────────────────────
            keys_currently_held.add(code)

            # ── Paw-press detection (simultaneous keys = cat paw landing) ────
            # A cat's paw is ~3–5 cm wide and depresses several keys at once.
            # Humans almost never hold 4+ non-modifier character keys simultaneously.
            paw_keys = keys_currently_held - MODIFIER_KEYS - HUMAN_HOLD_KEYS
            if (
                len(paw_keys) >= thresh["min_paw"]
                and (now - last_detection) > COOLDOWN_SECS
            ):
                last_detection = now
                msg = random.choice(CAT_MESSAGES)
                log.warning(
                    "CAT DETECTED (paw press)! simultaneous=%d keys=%s",
                    len(paw_keys), sorted(paw_keys),
                )
                notify(msg)
                if args.sound:
                    play_meow()
                if args.lock:
                    time.sleep(2)
                    lock_screen()
                key_times.clear()
                key_hold_times.clear()
                keys_currently_held.clear()
                continue

            # ── Streak detection (same key repeated rapidly = "fffffff") ─────
            # No English word has the same letter 4+ times consecutively.
            # Exclude backspace/space (humans repeat those legitimately).
            if code not in HUMAN_HOLD_KEYS and code not in MODIFIER_KEYS:
                key_times[code].append(now)  # also feeds walk detector below
                streak_cutoff = now - STREAK_WINDOW_SECS
                recent = [t for t in key_times[code] if t >= streak_cutoff]
                if (
                    len(recent) >= STREAK_MIN_COUNT
                    and (now - last_detection) > COOLDOWN_SECS
                ):
                    last_detection = now
                    msg = random.choice(CAT_MESSAGES)
                    log.warning(
                        "CAT DETECTED (key streak)! key=%d count=%d in %.1fs",
                        code, len(recent), STREAK_WINDOW_SECS,
                    )
                    notify(msg)
                    if args.sound:
                        play_meow()
                    if args.lock:
                        time.sleep(2)
                        lock_screen()
                    key_times.clear()
                    key_hold_times.clear()
                    keys_currently_held.clear()
                    continue
            else:
                key_times[code].append(now)

            # ── Walk / burst detection (key-down events) ─────────────────────
            # Prune old timestamps across all keys
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
                # PawSense insight: cats have zero regard for backspace.
                # If backspace/nav keys appear in the burst, it's a human.
                and not (active_keys & HUMAN_HOLD_KEYS)
                and (now - last_detection) > COOLDOWN_SECS
            ):
                last_detection = now
                msg = random.choice(CAT_MESSAGES)
                log.warning(
                    "CAT DETECTED (walking)! keys=%d rate=%.1f/s spread=%.0f%%",
                    unique_keys, rate, spread * 100,
                )
                notify(msg)
                if args.sound:
                    play_meow()
                if args.lock:
                    time.sleep(2)
                    lock_screen()

                key_times.clear()
                key_hold_times.clear()
                keys_currently_held.clear()

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
