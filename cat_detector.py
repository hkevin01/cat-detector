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

  INPUT PAUSE (after any detection):
    After a cat is detected, all keyboards are grabbed exclusively for
    --pause-secs seconds (default: 10). During this window the OS sees
    NO further keystrokes — Enter cannot send a message, submit a form,
    or confirm a dialog.  A second desktop notification counts down.
    Re-detection during a grab is silently suppressed via the cooldown.

  After any trigger: desktop notification, optional sound/lock, +input
  pause, then 45-second cooldown to prevent double-firing.

Usage:
  python cat_detector.py [--lock] [--sound] [--sensitivity medium] [--pause-secs 10]
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
    # Walk/burst: thresholds are deliberately set ABOVE what a fast human
    # typist (120+ WPM) can produce, even with varied text and no corrections.
    # A running/walking cat produces bursts of random keys at 15–25 events/sec
    # across the whole keyboard — these thresholds only those bursts trigger.
    # min_paw: simultaneous non-modifier/non-nav keys for paw detection.
    "low":    {"min_keys": 28, "min_rate": 13.0, "spread": 0.72, "min_paw": 5},
    "medium": {"min_keys": 24, "min_rate": 11.0, "spread": 0.66, "min_paw": 4},
    "high":   {"min_keys": 18, "min_rate":  9.0, "spread": 0.55, "min_paw": 3},
}

WINDOW_SECS   = 2.0   # sliding time window — shorter = less key accumulation from fast typing
COOLDOWN_SECS = 45    # silence after a detection

# Same-key streak detection — "ffffff" is a cat, not a word
STREAK_WINDOW_SECS = 1.0  # look-back for rapid repeated taps of the same key
STREAK_MIN_COUNT   = 6    # ≥ this many key-down events for same key in window
                          # (raised from 4 — fast typists hit 4 of 't'/'e' normally)

# Enter key protection — only trigger via simultaneous paw detection, NOT the
# rolling window (rolling window always contains recently typed letters → false positives).
# If Enter + ≥ ENTER_PAW_MIN other char keys are physically held simultaneously,
# that is unambiguously a cat paw (humans never hold Enter + 2 chars at once).
KEY_ENTER       = 28   # KEY_ENTER
ENTER_PAW_MIN   = 2    # Enter + ≥ this many simultaneously held char keys → fire

# Input pause / keyboard grab — after detection, grab all keyboards exclusively
# so the OS sees NO further keystrokes until the grab is released.
GRAB_SECS_DEFAULT = 10   # default seconds; overridable via --pause-secs

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
    grab_active    = False   # prevents stacking multiple grab tasks

    # ── Input pause (keyboard grab) ──────────────────────────────────────────
    async def pause_input() -> None:
        """Grab all keyboards for args.pause_secs seconds so no events escape."""
        nonlocal grab_active
        if grab_active or args.pause_secs <= 0:
            return
        grab_active = True
        grabbed = []
        for kb in keyboards:
            try:
                kb.grab()
                grabbed.append(kb)
            except OSError:
                pass
        if grabbed:
            log.info("⌨️  Input paused — keyboard grabbed for %ds", args.pause_secs)
            if shutil.which("notify-send"):
                subprocess.run(
                    ["notify-send", "-u", "normal",
                     "-t", str(args.pause_secs * 1000),
                     "-i", "input-keyboard",
                     "⌨️  Keyboard paused",
                     f"Cat input blocked for {args.pause_secs}s — removing paw…"],
                    check=False,
                )
        await asyncio.sleep(args.pause_secs)
        for kb in grabbed:
            try:
                kb.ungrab()
            except OSError:
                pass
        grab_active = False
        if grabbed:
            log.info("⌨️  Input resumed")

    log.info(
        "Cat detector running | sensitivity=%s "
        "(walk: keys≥%d rate≥%.1f/s spread≥%.0f%%) "
        "(paw: simultaneous≥%d) (hold: repeats≥%d) "
        "(pause: %ds after detection)",
        args.sensitivity,
        thresh["min_keys"], thresh["min_rate"], thresh["spread"] * 100,
        thresh["min_paw"], HOLD_MIN_REPEATS,
        args.pause_secs,
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
                        asyncio.create_task(pause_input())
                continue  # autoreps don't feed walk/paw/streak detectors

            # key_down from here ─────────────────────────────────────────────
            keys_currently_held.add(code)

            # ── Paw-press detection (simultaneous keys = cat paw landing) ────
            # A cat's paw is ~3–5 cm wide and depresses several keys at once.
            # Humans almost never hold 4+ non-modifier character keys simultaneously.
            paw_keys = keys_currently_held - MODIFIER_KEYS - HUMAN_HOLD_KEYS

            # Enter special case: Enter + ≥ ENTER_PAW_MIN simultaneous char keys
            # is unambiguously dangerous (sends messages / runs commands).
            # Checked at a lower threshold than general paw detection.
            enter_paw = (
                KEY_ENTER in paw_keys
                and len(paw_keys - {KEY_ENTER}) >= ENTER_PAW_MIN
            )

            if (
                (enter_paw or len(paw_keys) >= thresh["min_paw"])
                and (now - last_detection) > COOLDOWN_SECS
            ):
                reason = "enter+simultaneous" if enter_paw else "paw press"
                last_detection = now
                msg = random.choice(CAT_MESSAGES)
                log.warning(
                    "CAT DETECTED (%s)! simultaneous=%d keys=%s",
                    reason, len(paw_keys), sorted(paw_keys),
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
                asyncio.create_task(pause_input())
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
                    asyncio.create_task(pause_input())
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

            # Walk trigger only — Enter is handled by paw detection above.
            # Requires rate > 11/s (> 132 WPM total event rate) AND 24+ unique
            # keys AND 66%+ zone spread — genuinely unreachable by normal typing.
            if (
                unique_keys >= thresh["min_keys"]
                and rate     >= thresh["min_rate"]
                and spread   >= thresh["spread"]
                # Backspace / nav keys anywhere in the burst = human, not cat.
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
                asyncio.create_task(pause_input())

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
    parser.add_argument(
        "--pause-secs", type=int, default=GRAB_SECS_DEFAULT, metavar="N",
        help=(
            "Seconds to block keyboard input after cat detected (default: "
            f"{GRAB_SECS_DEFAULT}; 0 = disabled). Grabs keyboard exclusively so "
            "Enter and all other keys cannot reach any application."
        ),
    )
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
