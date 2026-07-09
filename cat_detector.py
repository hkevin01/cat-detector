#!/usr/bin/env python3
"""
cat-detector: Watches keyboard events for cat-on-keyboard AND toddler signatures.

Runs on Linux (evdev) and Windows (pynput) with identical detection logic.

Detection modes:
  WALK/BURST     — sliding window of unique keys × rate × spatial spread
  HOLD/SIT       — kernel autorepeat flood (Linux) / rapid same-key repeat (Windows)
  PAW PRESS      — 3–5+ non-modifier keys physically held at the same moment
  STREAK         — same key tapped 6+ times within 1 second ("ffffff")

Toddler mode (--toddler):
  Dramatically lowers every threshold so that the frantic, palm-slapping style
  a toddler uses (2–3 simultaneous keys, fast rate, little spread) is caught
  before any damage is done.

Screen lock is OFF by default.  Use --lock to enable it.

Usage:
  python cat_detector.py [--lock] [--sound] [--toddler]
                                                 [--sensitivity medium]
"""

import argparse
import collections
import json
import logging
import os
import platform
import queue
import random
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_PLATFORM = platform.system()   # "Linux" | "Windows" | "Darwin"

# ── platform-specific imports ─────────────────────────────────────────────────
if _PLATFORM == "Linux":
    try:
        import evdev
        from evdev import InputDevice, categorize, ecodes
    except ImportError:
        print(
            "Error: python-evdev not installed.\n"
            "  Arch/Manjaro : sudo pacman -S python-evdev\n"
            "  Debian/Ubuntu: sudo apt install python3-evdev\n"
            "  Fedora/RHEL  : sudo dnf install python3-evdev\n"
            "  pip          : pip install evdev"
        )
        sys.exit(1)
elif _PLATFORM == "Windows":
    try:
        from pynput import keyboard as _pynput_kb
    except ImportError:
        print(
            "Error: pynput not installed.\n"
            "  Run: pip install pynput winotify"
        )
        sys.exit(1)
    try:
        import ctypes
        _user32 = ctypes.windll.user32
    except Exception:
        _user32 = None

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

WALK_SCORE_WEIGHTS = {
    "unique": 0.45,
    "rate": 0.35,
    "spread": 0.20,
}

WALK_SCORE_MIN = {
    "low": 1.02,
    "medium": 1.03,
    "high": 1.05,
    "toddler": 1.00,
}

BASELINE_WARMUP_SAMPLES = 80
BASELINE_MARGIN = 0.04
BASELINE_MAX_SHIFT = 0.20
BASELINE_SAMPLE_CAP = 600

# Toddler mode: much looser thresholds.
# A toddler palm-slams keys in rapid bursts with minimal spread — 2–3 keys held
# simultaneously, fast rate, chaotic zone spread starting around 33%.
# Streak window shrinks to 0.6 s because toddlers repeat keys very rapidly.
TODDLER_SENSITIVITY = {"min_keys": 8, "min_rate": 5.0, "spread": 0.22, "min_paw": 2}
TODDLER_STREAK_WINDOW = 0.6   # seconds
TODDLER_STREAK_MIN    = 3     # 3 hits of same key in 0.6 s → toddler
TODDLER_LOCK_DELAY    = 0     # lock immediately — no 2-second grace period

TODDLER_MESSAGES = [
    "👶 TODDLER ALERT: Tiny hands detected on keyboard!",
    "🍼 Little one found the keyboard. Lockdown initiated.",
    "👶 Baby mode triggered — stepping away from the laptop?",
    "🧸 Toddler-initiated keypress storm detected. Screen locked.",
    "👶 Small human detected! Protecting your work.",
    "🍼 Someone very small wants to help you type. Screen locked.",
]

WINDOW_SECS   = 2.0   # sliding time window — shorter = less key accumulation from fast typing
COOLDOWN_SECS = 45    # silence after a detection
# Legacy compatibility constant; freeze/grab behavior has been removed.
GRAB_SECS_DEFAULT = 30

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
    """Return all evdev devices that look like keyboards (Linux only)."""
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


def walk_confidence(unique_keys: int, rate: float, spread: float, thresh: dict) -> float:
    """
    Weighted normalized score for walk/burst confidence.

    Each component is measured as ratio-to-threshold and blended with
    deterministic weights. A score near 1.0 means "barely at threshold".
    Values > 1.0 indicate stronger evidence of paw-walking behavior.
    """
    unique_ratio = unique_keys / max(1, thresh["min_keys"])
    rate_ratio = rate / max(0.001, thresh["min_rate"])
    spread_ratio = spread / max(0.001, thresh["spread"])
    return (
        WALK_SCORE_WEIGHTS["unique"] * unique_ratio
        + WALK_SCORE_WEIGHTS["rate"] * rate_ratio
        + WALK_SCORE_WEIGHTS["spread"] * spread_ratio
    )


def cooldown_allows(now: float, last_detection: float, cooldown_secs: float = COOLDOWN_SECS) -> bool:
    """Return True when enough time has passed since the previous detection."""
    return (now - last_detection) > cooldown_secs


@dataclass(frozen=True)
class WalkMetrics:
    unique_keys: int
    rate: float
    spread: float


@dataclass(frozen=True)
class DetectionRecord:
    timestamp_utc: str
    entity: str
    reason: str
    sensitivity: str
    toddler_mode: bool
    metrics: dict
    walk_score: float | None = None
    walk_threshold: float | None = None


@dataclass
class AdaptiveBaselineCalibrator:
    static_min: float
    warmup: int = BASELINE_WARMUP_SAMPLES
    margin: float = BASELINE_MARGIN
    max_shift: float = BASELINE_MAX_SHIFT
    sample_cap: int = BASELINE_SAMPLE_CAP
    samples: deque = field(default_factory=lambda: deque(maxlen=BASELINE_SAMPLE_CAP))
    _cached_threshold: float | None = None
    _dirty_count: int = 0
    _recompute_every: int = 20

    def observe(self, score: float) -> None:
        self.samples.append(float(score))
        self._dirty_count += 1

    def threshold(self) -> float:
        if self._cached_threshold is not None and self._dirty_count < self._recompute_every:
            return self._cached_threshold
        if len(self.samples) < self.warmup:
            self._cached_threshold = self.static_min
            self._dirty_count = 0
            return self._cached_threshold
        ordered = sorted(self.samples)
        idx = int(0.95 * (len(ordered) - 1))
        p95 = ordered[idx]
        adaptive = p95 + self.margin
        upper = self.static_min + self.max_shift
        self._cached_threshold = max(self.static_min, min(adaptive, upper))
        self._dirty_count = 0
        return self._cached_threshold


def _event_log_path() -> Path:
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return state_home / "cat-detector" / "detections.jsonl"


def record_detection_event(record: DetectionRecord) -> None:
    """Append a structured detection event record for longitudinal analysis."""
    try:
        path = _event_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record.__dict__, sort_keys=True) + "\n")
    except Exception as exc:
        log.warning("Failed to write detection event record: %s", exc)


def dispatch_detection_actions(args, message: str) -> None:
    """Execute side effects for a detection event."""
    notify(message)
    if args.sound:
        play_meow()
    if args.lock:
        lock_screen()


def compute_walk_metrics(key_times: dict, now: float) -> tuple[set[int], WalkMetrics]:
    """Pure walk metric computation from timestamp buffers."""
    cutoff = now - WINDOW_SECS
    active_keys: set[int] = set()
    for code, times in key_times.items():
        while times and times[0] < cutoff:
            times.popleft()
        if times:
            active_keys.add(code)
    total_events = sum(len(q) for q in key_times.values() if q)
    unique_keys = len(active_keys)
    rate = total_events / WINDOW_SECS
    spread = zone_spread(active_keys)
    return active_keys, WalkMetrics(unique_keys=unique_keys, rate=rate, spread=spread)


def hold_detection_signal(key_hold_times: dict, code: int, now: float, last_detection: float) -> dict | None:
    """Pure hold/sit detector over repeat timestamps."""
    if code in HUMAN_HOLD_KEYS:
        return None
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
        and cooldown_allows(now, last_detection)
    ):
        return {"held_keys": active_held, "max_repeats": max_repeats}
    return None


def paw_detection_signal(
    keys_currently_held: set[int], thresh: dict, now: float, last_detection: float
) -> tuple[str, dict] | None:
    """Pure simultaneous-key detector for paw/toddler slams."""
    paw_keys = keys_currently_held - MODIFIER_KEYS - HUMAN_HOLD_KEYS
    enter_paw = KEY_ENTER in paw_keys and len(paw_keys - {KEY_ENTER}) >= ENTER_PAW_MIN
    if (enter_paw or len(paw_keys) >= thresh["min_paw"]) and cooldown_allows(now, last_detection):
        reason = "enter+simultaneous" if enter_paw else "paw press"
        return reason, {"simultaneous": len(paw_keys), "keys": sorted(paw_keys)}
    return None


def streak_detection_signal(
    key_times: dict,
    code: int,
    now: float,
    streak_window: float,
    streak_min: int,
    last_detection: float,
) -> dict | None:
    """Pure same-key streak detector."""
    recent = [t for t in key_times[code] if t >= now - streak_window]
    if len(recent) >= streak_min and cooldown_allows(now, last_detection):
        return {"key": code, "count": len(recent), "window": f"{streak_window:.1f}s"}
    return None


# ── Platform-agnostic notification ────────────────────────────────────────────

def notify(message: str, urgency: str = "critical"):
    """Send a desktop notification (Linux + Windows)."""
    print(f"\n{'='*60}\n{message}\n{'='*60}\n")
    if _PLATFORM == "Linux":
        if shutil.which("notify-send"):
            subprocess.run(
                ["notify-send", "-u", urgency, "-t", "8000",
                 "-i", "input-keyboard", "Cat Detected! 🐱", message],
                check=False,
            )
        else:
            log.warning("notify-send not found — printed to console")
    elif _PLATFORM == "Windows":
        try:
            from winotify import Notification
            toast = Notification(
                app_id="cat-detector",
                title="Cat Detected! 🐱",
                msg=message,
            )
            toast.show()
        except Exception:
            log.warning("winotify unavailable — printed to console")


# ── Platform-agnostic sound ───────────────────────────────────────────────────

def play_meow():
    """Play a meow sound if a sample is available."""
    sample = os.path.join(os.path.dirname(__file__), "assets", "meow.wav")
    if not os.path.exists(sample):
        return
    if _PLATFORM == "Linux":
        for player in ("paplay", "aplay", "pw-play"):
            if shutil.which(player):
                subprocess.Popen([player, sample],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                return
    elif _PLATFORM == "Windows":
        try:
            import winsound
            winsound.PlaySound(sample, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception:
            pass


# ── Platform-agnostic screen lock ────────────────────────────────────────────

def lock_screen():
    """Lock the screen (Linux: loginctl/KDE/xdg; Windows: LockWorkStation)."""
    if _PLATFORM == "Linux":
        for cmd in (
            ["loginctl", "lock-session"],
            ["kscreenlocker_greet", "--forcelock"],
            ["xdg-screensaver", "lock"],
            ["gnome-screensaver-command", "--lock"],
        ):
            if shutil.which(cmd[0]):
                subprocess.run(cmd, check=False)
                return
        log.warning("No screen locker found — skipping lock")
    elif _PLATFORM == "Windows":
        try:
            if _user32:
                _user32.LockWorkStation()
            else:
                subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=False)
        except Exception as exc:
            log.warning("Windows lock failed: %s", exc)


# ── Shared detection engine ───────────────────────────────────────────────────
# Both the Linux (evdev) and Windows (pynput) backends feed events into this
# engine via a thread-safe queue.  Events are 2-tuples:
#   ("down", keycode: int)   — key pressed
#   ("up",   keycode: int)   — key released
#   ("hold", keycode: int)   — key auto-repeated (Linux only; synthesised on Windows)


def _detection_engine(event_queue: queue.SimpleQueue, args) -> None:
    """
    Consume keyboard events from event_queue and apply all detection algorithms.
    Runs in the thread that calls it (blocks until the programme exits).

    The same logic runs on both Linux and Windows; only the event source differs.
    """
    thresh = TODDLER_SENSITIVITY if args.toddler else SENSITIVITY[args.sensitivity]
    streak_window = TODDLER_STREAK_WINDOW if args.toddler else STREAK_WINDOW_SECS
    streak_min    = TODDLER_STREAK_MIN    if args.toddler else STREAK_MIN_COUNT
    messages      = TODDLER_MESSAGES      if args.toddler else CAT_MESSAGES
    entity        = "toddler" if args.toddler else "cat"
    walk_score_min = WALK_SCORE_MIN["toddler"] if args.toddler else WALK_SCORE_MIN[args.sensitivity]
    baseline = AdaptiveBaselineCalibrator(static_min=walk_score_min)

    key_times:           dict[int, deque] = collections.defaultdict(lambda: deque(maxlen=200))
    key_hold_times:      dict[int, deque] = collections.defaultdict(lambda: deque(maxlen=200))
    keys_currently_held: set[int]         = set()
    last_detection = 0.0

    def _fire(reason: str, walk_score: float | None = None, walk_threshold: float | None = None, **log_kw):
        nonlocal last_detection
        last_detection = time.monotonic()
        msg = random.choice(messages)
        log.warning("%s DETECTED (%s)! %s",
                    entity.upper(), reason,
                    " ".join(f"{k}={v}" for k, v in log_kw.items()))
        record = DetectionRecord(
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            entity=entity,
            reason=reason,
            sensitivity=args.sensitivity,
            toddler_mode=bool(args.toddler),
            metrics=log_kw,
            walk_score=walk_score,
            walk_threshold=walk_threshold,
        )
        record_detection_event(record)

        dispatch_detection_actions(args, msg)

        key_times.clear()
        key_hold_times.clear()
        keys_currently_held.clear()

    log.info(
        "%s detector running | sensitivity=%s%s "
        "(walk: keys≥%d rate≥%.1f/s spread≥%.0f%%) "
        "(paw: simultaneous≥%d) (hold: repeats≥%d) "
        "(lock: %s)",
        entity.capitalize(),
        args.sensitivity,
        " +toddler" if args.toddler else "",
        thresh["min_keys"], thresh["min_rate"], thresh["spread"] * 100,
        thresh["min_paw"], HOLD_MIN_REPEATS,
        "enabled" if args.lock else "disabled",
    )

    while True:
        try:
            kind, code = event_queue.get(timeout=1.0)
        except queue.Empty:
            continue

        now = time.monotonic()

        # ── Key up ──────────────────────────────────────────────────────────
        if kind == "up":
            keys_currently_held.discard(code)
            continue

        # ── Hold / sit (autorepeat flood) ────────────────────────────────────
        if kind == "hold":
            hold_metrics = hold_detection_signal(key_hold_times, code, now, last_detection)
            if hold_metrics is not None:
                _fire("sitting/standing", **hold_metrics)
            continue

        # key_down from here ──────────────────────────────────────────────────
        keys_currently_held.add(code)

        # ── Paw-press / toddler-slam detection ───────────────────────────────
        paw_signal = paw_detection_signal(keys_currently_held, thresh, now, last_detection)
        if paw_signal is not None:
            reason, paw_metrics = paw_signal
            _fire(reason, **paw_metrics)
            continue

        # ── Streak detection ─────────────────────────────────────────────────
        if code not in HUMAN_HOLD_KEYS and code not in MODIFIER_KEYS:
            key_times[code].append(now)
            streak_metrics = streak_detection_signal(
                key_times, code, now, streak_window, streak_min, last_detection
            )
            if streak_metrics is not None:
                _fire("key streak", **streak_metrics)
                continue
        else:
            key_times[code].append(now)

        # ── Walk / burst detection ────────────────────────────────────────────
        active_keys, metrics = compute_walk_metrics(key_times, now)
        score = walk_confidence(metrics.unique_keys, metrics.rate, metrics.spread, thresh)
        adaptive_min = baseline.threshold()

        if (
            metrics.unique_keys >= thresh["min_keys"]
            and metrics.rate    >= thresh["min_rate"]
            and metrics.spread  >= thresh["spread"]
            and not (active_keys & HUMAN_HOLD_KEYS)
            and cooldown_allows(now, last_detection)
        ):
            threshold = max(walk_score_min, adaptive_min)
            if score < threshold:
                continue
            _fire("walking",
                  walk_score=score,
                  walk_threshold=threshold,
                  keys=metrics.unique_keys,
                  rate=f"{metrics.rate:.1f}/s",
                  spread=f"{metrics.spread*100:.0f}%",
                  score=f"{score:.2f}",
                  threshold=f"{threshold:.2f}")
            continue

        # Calibrate against likely-human windows conservatively.
        if not (active_keys & HUMAN_HOLD_KEYS) and score < walk_score_min:
            baseline.observe(score)


# ── Linux backend ─────────────────────────────────────────────────────────────

_linux_keyboards: list = []   # populated by run_linux()


def run_linux(args) -> None:
    import asyncio

    global _linux_keyboards
    _linux_keyboards = find_keyboards()
    if not _linux_keyboards:
        log.error(
            "No accessible keyboards found. "
            "Make sure you are in the 'input' group: sudo usermod -aG input $USER"
        )
        sys.exit(1)

    eq: queue.SimpleQueue = queue.SimpleQueue()

    # Start the detection engine in a background thread so the asyncio loop
    # can keep reading evdev events without blocking.
    threading.Thread(target=_detection_engine, args=(eq, args), daemon=True).start()

    async def watch(dev):
        async for event in dev.async_read_loop():
            if event.type != ecodes.EV_KEY:
                continue
            ke = categorize(event)
            if ke.keystate == ke.key_up:
                eq.put(("up",   event.code))
            elif ke.keystate == ke.key_hold:
                eq.put(("hold", event.code))
            else:
                eq.put(("down", event.code))

    async def _gather():
        await asyncio.gather(*[watch(kb) for kb in _linux_keyboards])

    asyncio.run(_gather())


# ── Windows backend ───────────────────────────────────────────────────────────

def run_windows(args) -> None:
    """
    Use pynput to monitor keyboard events on Windows.

    pynput does not have a native autorepeat event, so we synthesise hold
    events: a per-key timer fires every HOLD_REPEAT_INTERVAL seconds while a
    key remains physically held.
    """
    HOLD_REPEAT_INTERVAL = 0.05   # 20 Hz — similar to kernel repeat rate

    eq: queue.SimpleQueue = queue.SimpleQueue()

    # Map pynput Key / KeyCode → integer token so the engine never sees pynput types
    def _vk(key) -> int:
        try:
            return key.value.vk          # pynput.keyboard.Key (e.g. Key.enter)
        except AttributeError:
            pass
        try:
            return key.vk                # pynput.keyboard.KeyCode with .vk set
        except AttributeError:
            pass
        # Last resort: map via char
        c = getattr(key, "char", None)
        if c:
            return ord(c.upper()) if c.isascii() else hash(c) & 0x7FFF
        return hash(key) & 0x7FFF

    # Translate pynput virtual-key codes → evdev-style codes used by the engine.
    # We only need the keys that appear in HUMAN_HOLD_KEYS, MODIFIER_KEYS and
    # KEY_ENTER; everything else uses the raw vk value (different but unique).
    VK_MAP = {
        0x08: 14,   # Backspace  → KEY_BACKSPACE
        0x09: 15,   # Tab        → KEY_TAB
        0x20: 57,   # Space      → KEY_SPACE
        0x24: 102,  # Home       → KEY_HOME
        0x26: 103,  # Up         → KEY_UP
        0x21: 104,  # Page Up    → KEY_PAGEUP
        0x25: 105,  # Left       → KEY_LEFT
        0x27: 106,  # Right      → KEY_RIGHT
        0x23: 107,  # End        → KEY_END
        0x28: 108,  # Down       → KEY_DOWN
        0x22: 109,  # Page Down  → KEY_PAGEDOWN
        0x2D: 110,  # Insert     → KEY_INSERT
        0x2E: 111,  # Delete     → KEY_DELETE
        0x11: 29,   # Ctrl (L)   → KEY_LEFTCTRL
        0x10: 42,   # Shift (L)  → KEY_LEFTSHIFT
        0x12: 56,   # Alt        → KEY_LEFTALT
        0x14: 58,   # CapsLock   → KEY_CAPSLOCK
        0xA2: 29,   # LCtrl
        0xA3: 97,   # RCtrl      → KEY_RIGHTCTRL
        0xA0: 42,   # LShift
        0xA1: 54,   # RShift     → KEY_RIGHTSHIFT
        0xA4: 56,   # LAlt
        0xA5: 100,  # RAlt       → KEY_RIGHTALT
        0x5B: 125,  # LWin       → KEY_LEFTMETA
        0x5C: 126,  # RWin       → KEY_RIGHTMETA
        0x0D: 28,   # Enter      → KEY_ENTER
        # Letter keys: Windows VK 0x41–0x5A → evdev 30–55 (a–z)
        **{0x41 + i: 30 + i for i in range(26)},
        # Digit row top: Windows VK 0x30–0x39 → evdev 11–2
        0x30: 11, 0x31: 2, 0x32: 3, 0x33: 4, 0x34: 5,
        0x35: 6,  0x36: 7, 0x37: 8, 0x38: 9, 0x39: 10,
    }

    # Per-key hold-repeat timer handles
    _hold_timers: dict[int, threading.Timer] = {}
    _hold_lock = threading.Lock()

    def _schedule_hold(mapped: int):
        def _repeat():
            eq.put(("hold", mapped))
            with _hold_lock:
                if mapped in _hold_timers:
                    t = threading.Timer(HOLD_REPEAT_INTERVAL, _repeat)
                    t.daemon = True
                    _hold_timers[mapped] = t
                    t.start()
        with _hold_lock:
            if mapped not in _hold_timers:
                t = threading.Timer(HOLD_REPEAT_INTERVAL, _repeat)
                t.daemon = True
                _hold_timers[mapped] = t
                t.start()

    def _cancel_hold(mapped: int):
        with _hold_lock:
            t = _hold_timers.pop(mapped, None)
        if t:
            t.cancel()

    def on_press(key):
        mapped = VK_MAP.get(_vk(key), _vk(key))
        eq.put(("down", mapped))
        _schedule_hold(mapped)

    def on_release(key):
        mapped = VK_MAP.get(_vk(key), _vk(key))
        _cancel_hold(mapped)
        eq.put(("up", mapped))

    # Start detection engine in a background thread
    threading.Thread(target=_detection_engine, args=(eq, args), daemon=True).start()

    log.info("Listening for keyboard events via pynput (Windows)…")
    # suppress=False so normal keyboard behaviour is unchanged.
    with _pynput_kb.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()


# ── Entry point ───────────────────────────────────────────────────────────────

def run(args) -> None:
    if _PLATFORM == "Linux":
        run_linux(args)
    elif _PLATFORM == "Windows":
        run_windows(args)
    else:
        log.error("Unsupported platform: %s", _PLATFORM)
        sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    """Build the canonical argument parser used by main() and tests."""
    parser = argparse.ArgumentParser(
        description="Detect when a cat (or toddler) walks on your keyboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    # --no-lock is the DEFAULT; use --lock to enable screen locking
    parser.add_argument(
        "--lock", dest="lock", action="store_true",
        default=False,
        help="Lock the screen on detection (off by default)",
    )
    parser.add_argument(
        "--no-lock", dest="lock", action="store_false",
        help="Disable screen lock (already the default; provided for compatibility)",
    )
    parser.add_argument(
        "--sound", action="store_true",
        help="Play a meow sound on detection (needs assets/meow.wav)",
    )
    parser.add_argument(
        "--toddler", action="store_true",
        help=(
            "Toddler mode: drastically lower all detection thresholds so that "
            "rapid palm-slapping and mashing by a small child is caught "
            "immediately and the screen is locked without delay."
        ),
    )
    parser.add_argument(
        "--sensitivity", choices=["low", "medium", "high"], default="medium",
        help="Detection sensitivity for cat mode (default: medium; ignored in --toddler)",
    )
    parser.add_argument(
        "--pause-secs", type=int, default=GRAB_SECS_DEFAULT, metavar="N",
        help="Deprecated compatibility option (no-op). Input grabbing is disabled.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
