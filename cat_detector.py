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
import math
import os
import platform
import queue
import random
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
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

# Temporal walk gate: borderline windows must be sustained across consecutive
# evaluations, while very strong bursts still trigger immediately.
WALK_CONFIRMATION_REQUIRED = 2
WALK_STRONG_MARGIN = 0.12
EARLY_WALK_POSTERIOR_THRESHOLD = 0.88

FUSION_REASONS = ("walking", "zone hopping", "sitting/standing")
REASON_BAYES_PRIORS = {
    "walking": 0.12,
    "zone hopping": 0.10,
    "sitting/standing": 0.16,
}
GLOBAL_FUSION_PRIOR = 0.05
SIGNAL_DECAY_HALF_LIFE_SECS = 4.0
SIGNAL_DECAY_MIN_STRENGTH = 0.03

CADENCE_WARMUP_EVENTS = 40
CADENCE_MIN_STD_INTERVAL = 0.010
CADENCE_RATE_Z_WEIGHT = 0.10

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

LOCK_PROFILE_DEFAULT = "all"
LOCK_PROFILE_ALL = "all"
LOCK_PROFILE_HIGH_RISK = "high-risk"
LOCK_PROFILE_ADAPTIVE = "adaptive"
LOCK_PROFILE_ENV = "CAT_DETECTOR_LOCK_PROFILE"
HIGH_RISK_REASONS = {"sitting/standing", "enter+simultaneous"}
LOCK_HARD_DISABLE_ENV = "CAT_DETECTOR_DISABLE_LOCK"
LOCK_CIRCUIT_MIN_INTERVAL_SECS = 180.0
LOCK_CIRCUIT_MAX_PER_SESSION = 2
ACTION_MIN_INTERVAL_SECS = 1.0
ACTION_NOTIFY_TIMEOUT_SECS = 0.75
ACTION_NEUTRALIZE_TIMEOUT_SECS = 0.75
ACTION_SOUND_TIMEOUT_SECS = 0.75
ACTION_LOCK_TIMEOUT_SECS = 1.50
ACTION_FAILURE_MAX_CONSECUTIVE = 3
ACTION_LOCK_DISABLE_WINDOW_SECS = 900.0
ACTION_LOCK_STARTUP_GRACE_SECS = 8.0
HEARTBEAT_INTERVAL_SECS = 30.0
HEARTBEAT_SCHEMA_VERSION = 1

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

# Rapid non-adjacent zone hopping strongly indicates paw movement across the
# keyboard surface rather than normal finger travel.
ZONE_HOP_WINDOW_SECS = 0.9
ZONE_HOP_MIN_EVENTS = 7
ZONE_HOP_MIN_TRANSITIONS = 4
ZONE_HOP_MIN_FAR_HOPS = 3
ZONE_HOP_MIN_UNIQUE_ZONES = 4
TODDLER_ZONE_HOP_MIN_EVENTS = 5
TODDLER_ZONE_HOP_MIN_TRANSITIONS = 3
TODDLER_ZONE_HOP_MIN_FAR_HOPS = 2
TODDLER_ZONE_HOP_MIN_UNIQUE_ZONES = 3

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

ZONE_COORDS = {
    "top-left": (0, 0),
    "top-center": (0, 1),
    "top-right": (0, 2),
    "home-left": (1, 0),
    "home-center": (1, 1),
    "home-right": (1, 2),
    "bottom-left": (2, 0),
    "bottom-center": (2, 1),
    "bottom-right": (2, 2),
}

KEY_PRIMARY_ZONE: dict[int, str] = {}
for _zone_name, _keys in ZONE_KEYS.items():
    for _code in _keys:
        KEY_PRIMARY_ZONE.setdefault(_code, _zone_name)

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

_lock_circuit_state = {
    "count": 0,
    "last": 0.0,
}
_lock_circuit_guard = threading.Lock()
_action_dispatch_guard = threading.Lock()
_action_safety_state = {
    "last_dispatch": 0.0,
    "consecutive_failures": 0,
    "lock_disabled_until": 0.0,
    "process_started": time.monotonic(),
}
_action_safety_guard = threading.Lock()
_heartbeat_state = {
    "last": 0.0,
}
_heartbeat_guard = threading.Lock()


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


def walk_temporal_gate(
    score: float,
    threshold: float,
    consecutive_hits: int,
    *,
    required_hits: int = WALK_CONFIRMATION_REQUIRED,
    strong_margin: float = WALK_STRONG_MARGIN,
) -> tuple[bool, int]:
    """
    Decide walk firing using temporal consistency.

    Rules:
    - score < threshold: reset confirmation state.
    - threshold <= score < threshold + strong_margin: require repeated hits.
    - score >= threshold + strong_margin: fire immediately.
    """
    if score < threshold:
        return False, 0

    if score >= (threshold + strong_margin):
        return True, 0

    next_hits = consecutive_hits + 1
    if next_hits >= required_hits:
        return True, 0
    return False, next_hits


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _strength_to_likelihood_ratio(strength: float) -> float:
    """Map [0,1] evidence strength into a smooth Bayes likelihood ratio."""
    centered = (_clamp01(strength) - 0.5) * 4.0
    return math.exp(centered)


def bayesian_reason_posterior(reason: str, strength: float, priors: dict[str, float] | None = None) -> float:
    """Calibrated posterior confidence for one reason from prior and evidence strength."""
    priors = priors or REASON_BAYES_PRIORS
    prior = _clamp01(priors.get(reason, 0.10))
    prior = min(0.999, max(0.001, prior))
    lr = _strength_to_likelihood_ratio(strength)
    odds = (prior / (1.0 - prior)) * lr
    return odds / (1.0 + odds)


def fused_posterior_risk_score(
    reason_strengths: dict[str, float],
    *,
    priors: dict[str, float] | None = None,
    global_prior: float = GLOBAL_FUSION_PRIOR,
) -> tuple[float, dict[str, float]]:
    """
    Fuse multiple reason posteriors into one calibrated risk probability.

    The fusion assumes conditional independence in the complement space and
    anchors to a small global prior so weak signals do not over-trigger.
    """
    per_reason: dict[str, float] = {}
    for reason, strength in reason_strengths.items():
        if reason not in FUSION_REASONS:
            continue
        if strength <= 0.0:
            continue
        per_reason[reason] = bayesian_reason_posterior(reason, strength, priors=priors)

    complement_prob = 1.0
    for posterior in per_reason.values():
        complement_prob *= (1.0 - _clamp01(posterior))
    fused = 1.0 - complement_prob

    anchored = _clamp01(global_prior + ((1.0 - global_prior) * fused))
    return anchored, per_reason


@dataclass
class TemporalSignalMemory:
    """Decay-weighted memory of suspicious micro-signals across recent events."""
    half_life_secs: float = SIGNAL_DECAY_HALF_LIFE_SECS
    min_strength: float = SIGNAL_DECAY_MIN_STRENGTH
    _events: deque = field(default_factory=lambda: deque(maxlen=512))

    def _decay_weight(self, age_secs: float) -> float:
        if age_secs <= 0.0:
            return 1.0
        return 0.5 ** (age_secs / max(0.001, self.half_life_secs))

    def observe(self, reason: str, strength: float, now: float) -> None:
        s = _clamp01(strength)
        if s <= 0.0:
            return
        self._events.append((float(now), reason, s))

    def decayed_reason_strengths(self, now: float) -> dict[str, float]:
        accum: dict[str, float] = {}
        for ts, reason, strength in self._events:
            age = max(0.0, float(now) - ts)
            weighted = strength * self._decay_weight(age)
            if weighted < self.min_strength:
                continue
            accum[reason] = accum.get(reason, 0.0) + weighted
        return {reason: min(1.0, value) for reason, value in accum.items()}


@dataclass
class TypingCadenceEnvelope:
    """Online estimator of user typing cadence and variance for rate normalization."""
    warmup_events: int = CADENCE_WARMUP_EVENTS
    min_std_interval: float = CADENCE_MIN_STD_INTERVAL
    _count: int = 0
    _mean_interval: float = 0.0
    _m2_interval: float = 0.0
    _last_keydown: float | None = None

    def observe_keydown(self, now: float) -> None:
        if self._last_keydown is None:
            self._last_keydown = float(now)
            return
        interval = max(0.001, float(now) - self._last_keydown)
        self._last_keydown = float(now)
        self._count += 1
        delta = interval - self._mean_interval
        self._mean_interval += delta / self._count
        delta2 = interval - self._mean_interval
        self._m2_interval += delta * delta2

    def interval_std(self) -> float:
        if self._count < 2:
            return self.min_std_interval
        variance = self._m2_interval / (self._count - 1)
        return max(self.min_std_interval, math.sqrt(max(0.0, variance)))

    def normalized_rate_z(self, observed_rate: float) -> float:
        if self._count < self.warmup_events or self._mean_interval <= 0.0:
            return 0.0
        baseline_rate = 1.0 / self._mean_interval
        std_rate = self.interval_std() / max(0.001, self._mean_interval ** 2)
        std_rate = max(0.20, std_rate)
        return (float(observed_rate) - baseline_rate) / std_rate


def normalized_walk_rate(rate: float, cadence_z: float, z_weight: float = CADENCE_RATE_Z_WEIGHT) -> float:
    """Boost walk rate when current cadence is an outlier versus user baseline."""
    boost = max(0.0, cadence_z) * z_weight
    boost = min(boost, 0.50)
    return float(rate) * (1.0 + boost)


def walk_micro_signal_strength(score: float, threshold: float) -> float:
    if threshold <= 0:
        return 0.0
    ratio = score / threshold
    return _clamp01((ratio - 0.75) / 0.35)


def hold_micro_signal_strength(metrics: dict | None) -> float:
    if not metrics:
        return 0.0
    max_repeats = int(metrics.get("max_repeats", 0) or 0)
    held_keys = int(metrics.get("held_keys", 0) or 0)
    repeat_ratio = max_repeats / max(1, HOLD_MIN_REPEATS)
    multi_ratio = held_keys / max(1, HOLD_MULTI_KEYS)
    return _clamp01(max(repeat_ratio, multi_ratio))


def zone_hop_micro_signal_strength(
    transitions: int,
    far_hops: int,
    unique_zones: int,
    *,
    toddler_mode: bool,
) -> float:
    min_transitions = TODDLER_ZONE_HOP_MIN_TRANSITIONS if toddler_mode else ZONE_HOP_MIN_TRANSITIONS
    min_far_hops = TODDLER_ZONE_HOP_MIN_FAR_HOPS if toddler_mode else ZONE_HOP_MIN_FAR_HOPS
    min_unique = TODDLER_ZONE_HOP_MIN_UNIQUE_ZONES if toddler_mode else ZONE_HOP_MIN_UNIQUE_ZONES
    trans_ratio = transitions / max(1, min_transitions)
    hops_ratio = far_hops / max(1, min_far_hops)
    uniq_ratio = unique_zones / max(1, min_unique)
    return _clamp01((trans_ratio + hops_ratio + uniq_ratio) / 3.0)


def brier_score(probability_targets: list[tuple[float, bool]]) -> float:
    """Return mean Brier score over (predicted_probability, observed_label)."""
    if not probability_targets:
        return 0.0
    total = 0.0
    for probability, observed in probability_targets:
        p = _clamp01(probability)
        y = 1.0 if observed else 0.0
        total += (p - y) ** 2
    return total / len(probability_targets)


def reliability_bins(probability_targets: list[tuple[float, bool]], bins: int = 10) -> list[dict]:
    """Compute reliability diagram buckets for calibration analysis."""
    if bins <= 0:
        raise ValueError("bins must be positive")
    if not probability_targets:
        return []

    raw = [
        {
            "start": i / bins,
            "end": (i + 1) / bins,
            "count": 0,
            "mean_predicted": 0.0,
            "empirical": 0.0,
        }
        for i in range(bins)
    ]
    sums_pred = [0.0] * bins
    sums_obs = [0.0] * bins

    for probability, observed in probability_targets:
        p = _clamp01(probability)
        idx = min(bins - 1, int(p * bins))
        raw[idx]["count"] += 1
        sums_pred[idx] += p
        sums_obs[idx] += 1.0 if observed else 0.0

    out: list[dict] = []
    for idx, row in enumerate(raw):
        count = row["count"]
        if count == 0:
            continue
        row["mean_predicted"] = sums_pred[idx] / count
        row["empirical"] = sums_obs[idx] / count
        out.append(row)
    return out


def severity_calibration_metrics(records: list[dict], probability_key: str = "posterior_risk_score") -> dict:
    """Aggregate calibration metrics from replay/detection records."""
    pairs: list[tuple[float, bool]] = []
    for rec in records:
        if probability_key not in rec or "expected_positive" not in rec:
            continue
        pairs.append((float(rec[probability_key]), bool(rec["expected_positive"])))
    return {
        "count": len(pairs),
        "brier_score": brier_score(pairs),
        "reliability_bins": reliability_bins(pairs),
    }


def fit_reason_priors_from_replay_samples(
    samples: list[dict],
    *,
    reasons: tuple[str, ...] = FUSION_REASONS,
    smoothing: float = 1.0,
) -> dict[str, float]:
    """Estimate per-reason priors from labeled replay samples with Laplace smoothing."""
    priors: dict[str, float] = {}
    for reason in reasons:
        subset = [sample for sample in samples if str(sample.get("reason")) == reason]
        positives = sum(1 for sample in subset if bool(sample.get("expected_positive", False)))
        total = len(subset)
        prior = (positives + smoothing) / (total + (2.0 * smoothing)) if total else REASON_BAYES_PRIORS[reason]
        priors[reason] = _clamp01(prior)
    return priors


def tune_early_walk_posterior_threshold_from_replay(
    samples: list[dict],
    *,
    min_threshold: float = 0.55,
    max_threshold: float = 0.98,
    step: float = 0.01,
    min_precision: float = 0.95,
    fallback: float = EARLY_WALK_POSTERIOR_THRESHOLD,
) -> float:
    """
    Tune early-walk shortcut threshold using labeled walk posterior outcomes.

    Objective:
    - satisfy precision floor when possible,
    - maximize recall among precision-safe candidates,
    - tie-break with lower Brier error and higher threshold stability.
    """
    walk_samples = [
        sample for sample in samples
        if str(sample.get("reason")) == "walking" and sample.get("posterior_risk_score") is not None
    ]
    if not walk_samples:
        return fallback

    thresholds: list[float] = []
    t = min_threshold
    while t <= max_threshold + 1e-9:
        thresholds.append(round(t, 4))
        t += step

    best_threshold = fallback
    best_rank: tuple[float, float, float, float] | None = None
    for threshold in thresholds:
        tp = fp = fn = 0
        pairs: list[tuple[float, bool]] = []
        for sample in walk_samples:
            p = _clamp01(float(sample["posterior_risk_score"]))
            y = bool(sample["expected_positive"])
            predicted = p >= threshold
            pairs.append((1.0 if predicted else 0.0, y))
            if predicted and y:
                tp += 1
            elif predicted and not y:
                fp += 1
            elif (not predicted) and y:
                fn += 1

        precision = (tp / (tp + fp)) if (tp + fp) else 1.0
        recall = (tp / (tp + fn)) if (tp + fn) else 0.0
        brier = brier_score(pairs)
        precision_ok = 1.0 if precision >= min_precision else 0.0

        # Sort key: precision floor first, then recall, lower Brier, then higher threshold.
        rank = (precision_ok, recall, -brier, threshold)
        if best_rank is None or rank > best_rank:
            best_rank = rank
            best_threshold = threshold

    return _clamp01(best_threshold)


def calibrate_fusion_from_replay_samples(samples: list[dict]) -> dict:
    """Derive fusion priors and early-walk threshold from labeled replay statistics."""
    priors = fit_reason_priors_from_replay_samples(samples)
    threshold = tune_early_walk_posterior_threshold_from_replay(samples)
    metrics = severity_calibration_metrics(samples)
    return {
        "reason_priors": priors,
        "early_walk_posterior_threshold": threshold,
        "calibration_metrics": metrics,
        "sample_count": len(samples),
    }


def generate_synthetic_near_threshold_human_trace() -> list[dict]:
    """Generate deterministic human-like trace that rides thresholds without crossing cat signals."""
    keys = [30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49]
    events: list[dict] = []
    for code in keys:
        events.append({"kind": "down", "code": code, "delay": 0.028})
        events.append({"kind": "up", "code": code, "delay": 0.010})
    events.extend(
        [
            {"kind": "down", "code": 14, "delay": 0.020},
            {"kind": "up", "code": 14, "delay": 0.015},
            {"kind": "down", "code": 31, "delay": 0.018},
            {"kind": "up", "code": 31, "delay": 0.015},
        ]
    )
    return events


def generate_synthetic_adversarial_cat_trace() -> list[dict]:
    """Generate deterministic near-threshold cat-like trace with sustained suspicious bursts."""
    wave = [2, 3, 4, 5, 6, 7, 21, 22, 8, 9, 10, 11, 35, 36, 37, 38, 33, 34, 47, 48, 30, 31, 32, 44]
    events: list[dict] = []
    for _ in range(2):
        for code in wave:
            events.append({"kind": "down", "code": code, "delay": 0.010})
            events.append({"kind": "up", "code": code, "delay": 0.005})
    return events


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
    action_outcome: str
    lock_profile: str
    reason_severity: float
    adaptive_medium_escalated: bool
    posterior_risk_score: float
    walk_score: float | None = None
    walk_threshold: float | None = None


DETECTION_RECORD_REQUIRED_FIELDS = {
    "timestamp_utc",
    "entity",
    "reason",
    "sensitivity",
    "toddler_mode",
    "metrics",
    "action_outcome",
    "lock_profile",
    "reason_severity",
    "adaptive_medium_escalated",
    "posterior_risk_score",
    "walk_score",
    "walk_threshold",
}


def validate_detection_record_payload(payload: dict) -> None:
    """Validate JSONL payload shape and types before writing."""
    missing = DETECTION_RECORD_REQUIRED_FIELDS - set(payload.keys())
    if missing:
        raise ValueError(f"Detection record missing fields: {sorted(missing)}")

    # Accept only ISO-8601 timestamps generated by datetime.isoformat().
    try:
        datetime.fromisoformat(payload["timestamp_utc"])
    except Exception as exc:
        raise ValueError("Detection record timestamp_utc is not valid ISO format") from exc

    if not isinstance(payload["entity"], str):
        raise ValueError("Detection record entity must be a string")
    if not isinstance(payload["reason"], str):
        raise ValueError("Detection record reason must be a string")
    if not isinstance(payload["sensitivity"], str):
        raise ValueError("Detection record sensitivity must be a string")
    if not isinstance(payload["toddler_mode"], bool):
        raise ValueError("Detection record toddler_mode must be a bool")
    if not isinstance(payload["metrics"], dict):
        raise ValueError("Detection record metrics must be an object")
    if payload.get("action_outcome") not in {"locked", "neutralized-only"}:
        raise ValueError("Detection record action_outcome must be 'locked' or 'neutralized-only'")
    if not isinstance(payload.get("lock_profile"), str):
        raise ValueError("Detection record lock_profile must be a string")
    reason_severity = payload.get("reason_severity")
    if not isinstance(reason_severity, (int, float)):
        raise ValueError("Detection record reason_severity must be numeric")
    if not (0.0 <= float(reason_severity) <= 1.0):
        raise ValueError("Detection record reason_severity must be in [0.0, 1.0]")
    if not isinstance(payload.get("adaptive_medium_escalated"), bool):
        raise ValueError("Detection record adaptive_medium_escalated must be a bool")
    posterior_risk_score = payload.get("posterior_risk_score")
    if not isinstance(posterior_risk_score, (int, float)):
        raise ValueError("Detection record posterior_risk_score must be numeric")
    if not (0.0 <= float(posterior_risk_score) <= 1.0):
        raise ValueError("Detection record posterior_risk_score must be in [0.0, 1.0]")
    if not all(isinstance(k, str) for k in payload["metrics"].keys()):
        raise ValueError("Detection record metric keys must be strings")

    for optional_float in ("walk_score", "walk_threshold"):
        value = payload.get(optional_float)
        if value is not None and not isinstance(value, (int, float)):
            raise ValueError(f"Detection record {optional_float} must be numeric or null")


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


@dataclass
class AdaptiveRiskWindowCalibrator:
    """Per-reason adaptive windowing for medium-risk lock escalation."""
    min_window_secs: float = 20.0
    max_window_secs: float = 120.0
    escalate_min_events: int = 3
    severity_floor: float = 0.60
    alpha: float = 0.25
    _timestamps: dict[str, deque] = field(default_factory=dict)
    _severities: dict[str, deque] = field(default_factory=dict)
    _last_seen: dict[str, float] = field(default_factory=dict)
    _interval_ewma: dict[str, float] = field(default_factory=dict)

    def _window_secs_for(self, reason: str) -> float:
        ewma = self._interval_ewma.get(reason, 25.0)
        # A few cadence intervals define the personalized medium-risk window.
        window = ewma * 4.0
        return max(self.min_window_secs, min(window, self.max_window_secs))

    def observe_and_should_escalate(self, reason: str, now: float, severity: float) -> bool:
        if reason in HIGH_RISK_REASONS:
            return False

        last = self._last_seen.get(reason)
        if last is not None:
            interval = max(0.001, now - last)
            prev = self._interval_ewma.get(reason, interval)
            self._interval_ewma[reason] = (self.alpha * interval) + ((1.0 - self.alpha) * prev)
        self._last_seen[reason] = now

        ts = self._timestamps.setdefault(reason, deque(maxlen=128))
        sv = self._severities.setdefault(reason, deque(maxlen=128))
        ts.append(now)
        sv.append(float(severity))

        cutoff = now - self._window_secs_for(reason)
        while ts and ts[0] < cutoff:
            ts.popleft()
            sv.popleft()

        if len(ts) < self.escalate_min_events:
            return False
        avg_severity = sum(sv) / max(1, len(sv))
        return avg_severity >= self.severity_floor


def reason_severity_weight(reason: str, metrics: dict | None = None) -> float:
    """Return normalized urgency confidence in [0.0, 1.0] for policy analytics."""
    metrics = metrics or {}
    if reason == "sitting/standing":
        repeats = int(metrics.get("max_repeats", 0) or 0)
        if repeats >= 25:
            return 1.00
        if repeats >= 18:
            return 0.96
        return 0.90
    if reason == "enter+simultaneous":
        simultaneous = int(metrics.get("simultaneous", 0) or 0)
        return 1.00 if simultaneous >= 4 else 0.97
    if reason == "walking":
        raw = metrics.get("score")
        if raw is not None:
            try:
                return max(0.40, min(0.95, float(raw) / 1.20))
            except (TypeError, ValueError):
                pass
        return 0.70
    if reason == "zone hopping":
        far_hops = int(metrics.get("far_hops", 0) or 0)
        return min(0.90, 0.58 + (0.06 * far_hops))
    if reason == "paw press":
        simultaneous = int(metrics.get("simultaneous", 0) or 0)
        return min(0.90, 0.55 + (0.08 * simultaneous))
    if reason == "key streak":
        count = int(metrics.get("count", 0) or 0)
        return min(0.85, 0.50 + (0.04 * count))
    return 0.50


def _state_dir() -> Path:
    """Return cross-platform state directory for logs and heartbeat data."""
    if _PLATFORM == "Windows":
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata) / "cat-detector"
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "cat-detector"
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return state_home / "cat-detector"


def _event_log_path() -> Path:
    return _state_dir() / "detections.jsonl"


def _heartbeat_path() -> Path:
    return _state_dir() / "heartbeat.json"


def _status_page_path() -> Path:
    return _state_dir() / "status.html"


def _open_path_with_default_app(path: Path) -> bool:
    """Open a path with the platform default app/browser."""
    try:
        if _PLATFORM == "Windows" and hasattr(os, "startfile"):
            os.startfile(str(path))
            return True
        if _PLATFORM == "Linux" and shutil.which("xdg-open"):
            subprocess.Popen(
                ["xdg-open", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        return bool(webbrowser.open(path.as_uri()))
    except Exception as exc:
        log.warning("Failed to open path %s: %s", path, exc)
        return False


def read_runtime_status_snapshot(now_utc: datetime | None = None) -> dict:
    """Read the latest heartbeat and derive freshness metadata for UI surfaces."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    path = _heartbeat_path()
    if not path.exists():
        return {
            "available": False,
            "freshness_seconds": None,
            "freshness_label": "unknown",
            "input_freshness_seconds": None,
            "input_freshness_label": "unknown",
            "last_detection_reason": None,
            "heartbeat_version": None,
            "schema_current": False,
        }

    payload = json.loads(path.read_text(encoding="utf-8"))
    ts = datetime.fromisoformat(payload["timestamp_utc"])
    freshness_seconds = max(0.0, (now_utc - ts).total_seconds())
    if freshness_seconds <= HEARTBEAT_INTERVAL_SECS * 2:
        freshness_label = "fresh"
    elif freshness_seconds <= HEARTBEAT_INTERVAL_SECS * 6:
        freshness_label = "stale"
    else:
        freshness_label = "offline"

    input_ts_text = payload.get("last_successful_input_event_utc")
    if input_ts_text:
        input_ts = datetime.fromisoformat(input_ts_text)
        input_freshness_seconds = max(0.0, (now_utc - input_ts).total_seconds())
        if input_freshness_seconds <= HEARTBEAT_INTERVAL_SECS * 4:
            input_freshness_label = "active"
        elif input_freshness_seconds <= HEARTBEAT_INTERVAL_SECS * 20:
            input_freshness_label = "idle"
        else:
            input_freshness_label = "quiet"
    else:
        input_freshness_seconds = None
        input_freshness_label = "unknown"

    heartbeat_version = payload.get("heartbeat_version")
    return {
        **payload,
        "available": True,
        "freshness_seconds": freshness_seconds,
        "freshness_label": freshness_label,
        "input_freshness_seconds": input_freshness_seconds,
        "input_freshness_label": input_freshness_label,
        "heartbeat_version": heartbeat_version,
        "schema_current": heartbeat_version == HEARTBEAT_SCHEMA_VERSION,
    }


def migrate_heartbeat_payload(payload: dict) -> dict:
    """Upgrade older heartbeat payloads to the current schema shape."""
    migrated = dict(payload)
    migrated.setdefault("heartbeat_version", HEARTBEAT_SCHEMA_VERSION)
    migrated.setdefault("last_successful_input_event_utc", None)
    migrated.setdefault("last_detection_reason", None)
    return migrated


def migrate_heartbeat_file() -> bool:
    """Rewrite an older heartbeat file to the current schema when needed."""
    path = _heartbeat_path()
    if not path.exists():
        return False
    payload = json.loads(path.read_text(encoding="utf-8"))
    migrated = migrate_heartbeat_payload(payload)
    if migrated == payload:
        return False
    path.write_text(json.dumps(migrated, sort_keys=True), encoding="utf-8")
    return True


def open_status_page() -> bool:
    """Open the generated status page using the platform's default browser."""
    write_runtime_status_page()
    return _open_path_with_default_app(_status_page_path())


def open_raw_heartbeat() -> bool:
    """Open the raw heartbeat JSON for support and debug workflows."""
    if not _heartbeat_path().exists():
        return False
    return _open_path_with_default_app(_heartbeat_path())


def open_status_page_main() -> None:
    open_status_page()


def open_raw_heartbeat_main() -> None:
    open_raw_heartbeat()


def write_runtime_status_page() -> None:
    """Write a tiny human-readable status page for background runtime monitoring."""
    try:
        status = read_runtime_status_snapshot()
        if not status.get("available"):
            body = "<p>No heartbeat has been recorded yet.</p>"
        else:
            reason = status.get("last_detection_reason") or "none"
            last_input = status.get("last_successful_input_event_utc") or "none"
            input_age = status.get("input_freshness_seconds")
            input_age_text = "unknown" if input_age is None else f"{int(input_age)} seconds"
            schema_text = "current" if status.get("schema_current") else "stale"
            body = f"""
<p><strong>Heartbeat freshness:</strong> <span id=\"freshness-label\">{status['freshness_label']}</span></p>
<p><strong>Last heartbeat:</strong> <span id=\"heartbeat-ts\">{status['timestamp_utc']}</span></p>
<p><strong>Last detection reason:</strong> {reason}</p>
<p><strong>Heartbeat schema version:</strong> {status.get('heartbeat_version')} ({schema_text})</p>
<p><strong>Last successful input event:</strong> {last_input}</p>
<p><strong>Input stream health:</strong> {status.get('input_freshness_label')} ({input_age_text})</p>
<p><strong>Mode:</strong> sensitivity={status.get('sensitivity')} toddler={status.get('toddler_mode')}</p>
<p><strong>Lock policy:</strong> profile={status.get('lock_profile')} enabled={status.get('lock_enabled')}</p>
<p><strong>PID:</strong> {status.get('pid')}</p>
<p><strong>Freshness age:</strong> <span id=\"freshness-age\">{int(status['freshness_seconds'])}</span> seconds</p>
"""

        html = f"""<!doctype html>
<html lang=\"en\">
<head>
    <meta charset=\"utf-8\">
    <meta http-equiv=\"refresh\" content=\"15\">
    <title>cat-detector status</title>
    <style>
        body {{ font-family: sans-serif; margin: 24px; background: #f7f7f7; color: #222; }}
        .card {{ max-width: 720px; background: #fff; border: 1px solid #ddd; border-radius: 12px; padding: 20px; }}
        .fresh {{ color: #0a7a2f; }}
        .stale {{ color: #a56a00; }}
        .offline {{ color: #b42318; }}
    </style>
</head>
<body>
    <div class=\"card\">
        <h1>cat-detector status</h1>
        {body}
    </div>
    <script>
        (function () {{
            const tsText = document.getElementById('heartbeat-ts');
            const ageEl = document.getElementById('freshness-age');
            const labelEl = document.getElementById('freshness-label');
            if (!tsText || !ageEl || !labelEl) return;
            const ts = new Date(tsText.textContent);
            function tick() {{
                const age = Math.max(0, Math.floor((Date.now() - ts.getTime()) / 1000));
                ageEl.textContent = String(age);
                labelEl.className = '';
                if (age <= {int(HEARTBEAT_INTERVAL_SECS * 2)}) {{
                    labelEl.textContent = 'fresh';
                    labelEl.classList.add('fresh');
                }} else if (age <= {int(HEARTBEAT_INTERVAL_SECS * 6)}) {{
                    labelEl.textContent = 'stale';
                    labelEl.classList.add('stale');
                }} else {{
                    labelEl.textContent = 'offline';
                    labelEl.classList.add('offline');
                }}
            }}
            tick();
            window.setInterval(tick, 1000);
        }})();
    </script>
</body>
</html>
"""
        path = _status_page_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
    except Exception as exc:
        log.warning("Failed to write runtime status page: %s", exc)


def record_detection_event(record: DetectionRecord) -> None:
    """Append a structured detection event record for longitudinal analysis."""
    try:
        payload = record.__dict__.copy()
        validate_detection_record_payload(payload)
        path = _event_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, sort_keys=True) + "\n")
    except Exception as exc:
        log.warning("Failed to write detection event record: %s", exc)


def write_runtime_heartbeat(
    args,
    *,
    force: bool = False,
    last_detection_reason: str | None = None,
    last_successful_input_event_utc: str | None = None,
    now_monotonic: float | None = None,
) -> None:
    """Persist a lightweight runtime heartbeat for background health monitoring."""
    if now_monotonic is None:
        now_monotonic = time.monotonic()
    with _heartbeat_guard:
        last = _heartbeat_state["last"]
        if not force and last and (now_monotonic - last) < HEARTBEAT_INTERVAL_SECS:
            return
        _heartbeat_state["last"] = now_monotonic

    try:
        payload = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "heartbeat_version": HEARTBEAT_SCHEMA_VERSION,
            "pid": os.getpid(),
            "platform": _PLATFORM,
            "sensitivity": getattr(args, "sensitivity", "medium"),
            "toddler_mode": bool(getattr(args, "toddler", False)),
            "lock_profile": lock_profile(args),
            "lock_enabled": bool(getattr(args, "lock", False)),
            "last_detection_reason": last_detection_reason,
            "last_successful_input_event_utc": last_successful_input_event_utc,
        }
        path = _heartbeat_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fp:
            json.dump(payload, fp, sort_keys=True)
        write_runtime_status_page()
    except Exception as exc:
        log.warning("Failed to write runtime heartbeat: %s", exc)


def _linux_soft_neutralize_input() -> bool:
    """Best-effort Linux mitigation: cancel active combos/menus via xdotool."""
    if not shutil.which("xdotool"):
        return False
    try:
        # Release common modifiers first, then send Escape twice to cancel
        # app/window switchers without aggressive user disruption.
        subprocess.run(
            [
                "xdotool",
                "keyup", "Alt_L",
                "keyup", "Alt_R",
                "keyup", "Control_L",
                "keyup", "Control_R",
                "keyup", "Shift_L",
                "keyup", "Shift_R",
                "keyup", "Super_L",
                "keyup", "Super_R",
                "key", "Escape",
                "key", "Escape",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def _windows_soft_neutralize_input() -> bool:
    """Best-effort Windows mitigation: release modifiers and send Escape."""
    if not _user32:
        return False
    try:
        keyeventf_keyup = 0x0002
        vk_modifiers = (0x10, 0x11, 0x12, 0x5B, 0x5C)  # Shift/Ctrl/Alt/LWin/RWin
        for vk in vk_modifiers:
            _user32.keybd_event(vk, 0, keyeventf_keyup, 0)

        vk_escape = 0x1B
        _user32.keybd_event(vk_escape, 0, 0, 0)
        _user32.keybd_event(vk_escape, 0, keyeventf_keyup, 0)
        _user32.keybd_event(vk_escape, 0, 0, 0)
        _user32.keybd_event(vk_escape, 0, keyeventf_keyup, 0)
        return True
    except Exception:
        return False


def neutralize_active_input() -> None:
    """
    Smooth mitigation step to reduce accidental typing/window switching.

    This does not grab devices. It only performs best-effort cancellation
    gestures (release modifiers + Escape taps) to reduce immediate damage.
    """
    ok = False
    if _PLATFORM == "Linux":
        ok = _linux_soft_neutralize_input()
    elif _PLATFORM == "Windows":
        ok = _windows_soft_neutralize_input()
    if not ok:
        log.debug("Soft mitigation unavailable on this platform/runtime")


def lock_profile(args) -> str:
    """Resolve lock profile from args or environment with safe fallback."""
    profile = getattr(args, "lock_profile", None)
    if not profile:
        profile = os.environ.get(LOCK_PROFILE_ENV, LOCK_PROFILE_DEFAULT)
    profile = str(profile).strip().lower()
    if profile not in {LOCK_PROFILE_ALL, LOCK_PROFILE_HIGH_RISK, LOCK_PROFILE_ADAPTIVE}:
        return LOCK_PROFILE_DEFAULT
    return profile


def policy_should_lock(profile: str, reason: str, adaptive_medium_escalated: bool = False) -> bool:
    """Pure policy function for lock decision by profile and reason."""
    if profile == LOCK_PROFILE_ALL:
        return True
    if reason in HIGH_RISK_REASONS:
        return True
    if profile == LOCK_PROFILE_HIGH_RISK:
        return False
    if profile == LOCK_PROFILE_ADAPTIVE:
        return adaptive_medium_escalated
    return True


def should_lock_for_reason(args, reason: str, adaptive_medium_escalated: bool = False) -> bool:
    """Return True when current policy requires screen lock for this reason."""
    if not getattr(args, "lock", False):
        return False
    if os.environ.get(LOCK_HARD_DISABLE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    profile = lock_profile(args)
    return policy_should_lock(profile, reason, adaptive_medium_escalated)


def reset_lock_circuit_state() -> None:
    """Reset lock circuit counters; useful for tests and controlled restarts."""
    with _lock_circuit_guard:
        _lock_circuit_state["count"] = 0
        _lock_circuit_state["last"] = 0.0


def reset_action_safety_state(now: float | None = None) -> None:
    """Reset action-safety counters; useful for tests and controlled restarts."""
    if now is None:
        now = time.monotonic()
    with _action_safety_guard:
        _action_safety_state["last_dispatch"] = 0.0
        _action_safety_state["consecutive_failures"] = 0
        _action_safety_state["lock_disabled_until"] = 0.0
        _action_safety_state["process_started"] = float(now)


def _run_with_timeout(fn, timeout_secs: float, label: str) -> bool:
    """Run a side-effect function with a hard timeout to avoid hangs."""
    outcome = {"ok": True}

    def _target() -> None:
        try:
            fn()
        except Exception as exc:
            outcome["ok"] = False
            log.warning("Action side-effect failed (%s): %s", label, exc)

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=max(0.05, float(timeout_secs)))
    if thread.is_alive():
        log.warning("Action side-effect timed out (%s)", label)
        return False
    return bool(outcome["ok"])


def _note_action_failure(now: float) -> None:
    with _action_safety_guard:
        failures = int(_action_safety_state["consecutive_failures"]) + 1
        _action_safety_state["consecutive_failures"] = failures
        if failures >= ACTION_FAILURE_MAX_CONSECUTIVE:
            _action_safety_state["lock_disabled_until"] = max(
                float(_action_safety_state["lock_disabled_until"]),
                now + ACTION_LOCK_DISABLE_WINDOW_SECS,
            )


def _note_action_success() -> None:
    with _action_safety_guard:
        if _action_safety_state["consecutive_failures"] > 0:
            _action_safety_state["consecutive_failures"] = int(_action_safety_state["consecutive_failures"]) - 1


def _dispatch_throttle_allows(now: float) -> bool:
    with _action_safety_guard:
        last = float(_action_safety_state["last_dispatch"])
        if last and (now - last) < ACTION_MIN_INTERVAL_SECS:
            return False
        _action_safety_state["last_dispatch"] = now
    return True


def _lock_safety_allows(now: float) -> bool:
    with _action_safety_guard:
        if (now - float(_action_safety_state["process_started"])) < ACTION_LOCK_STARTUP_GRACE_SECS:
            return False
        if float(_action_safety_state["lock_disabled_until"]) > now:
            return False
    return True


def lock_circuit_allows(now: float | None = None) -> bool:
    """Safety gate to avoid repeated lock loops during persistent event storms."""
    if now is None:
        now = time.monotonic()
    with _lock_circuit_guard:
        count = _lock_circuit_state["count"]
        last = _lock_circuit_state["last"]
        if count >= LOCK_CIRCUIT_MAX_PER_SESSION:
            return False
        if last and (now - last) < LOCK_CIRCUIT_MIN_INTERVAL_SECS:
            return False
        _lock_circuit_state["count"] = count + 1
        _lock_circuit_state["last"] = now
    return True


def dispatch_detection_actions(
    args,
    message: str,
    reason: str,
    adaptive_medium_escalated: bool = False,
    now_monotonic: float | None = None,
) -> str:
    """Execute side effects for a detection event."""
    if now_monotonic is None:
        now_monotonic = time.monotonic()

    if not _action_dispatch_guard.acquire(blocking=False):
        log.warning("Detection action skipped: action dispatcher busy")
        return "neutralized-only"

    try:
        if not _dispatch_throttle_allows(now_monotonic):
            log.warning("Detection action skipped: throttle active")
            return "neutralized-only"

        ok_notify = _run_with_timeout(
            lambda: notify(message),
            ACTION_NOTIFY_TIMEOUT_SECS,
            "notify",
        )
        if not ok_notify:
            _note_action_failure(now_monotonic)

        ok_neutralize = _run_with_timeout(
            neutralize_active_input,
            ACTION_NEUTRALIZE_TIMEOUT_SECS,
            "neutralize",
        )
        if not ok_neutralize:
            _note_action_failure(now_monotonic)

        if args.sound:
            ok_sound = _run_with_timeout(play_meow, ACTION_SOUND_TIMEOUT_SECS, "sound")
            if not ok_sound:
                _note_action_failure(now_monotonic)

        should_lock = should_lock_for_reason(args, reason, adaptive_medium_escalated)
        if should_lock and _lock_safety_allows(now_monotonic) and lock_circuit_allows(now_monotonic):
            ok_lock = _run_with_timeout(lock_screen, ACTION_LOCK_TIMEOUT_SECS, "lock")
            if ok_lock:
                _note_action_success()
                return "locked"
            _note_action_failure(now_monotonic)
        return "neutralized-only"
    finally:
        _action_dispatch_guard.release()


def score_policy_pairs_from_replay_samples(
    samples: list[dict],
    profiles: tuple[str, ...] = (LOCK_PROFILE_ALL, LOCK_PROFILE_HIGH_RISK, LOCK_PROFILE_ADAPTIVE),
) -> dict[tuple[str, str], dict]:
    """
    Compute precision and disruption by (reason, profile) over replay samples.

    Sample shape:
      {
        "reason": str,
        "expected_positive": bool,
        "adaptive_medium_escalated": bool (optional, default False),
      }
    """
    buckets: dict[tuple[str, str], dict[str, int]] = {}
    calibration_samples: dict[tuple[str, str], list[tuple[float, bool]]] = {}
    for sample in samples:
        reason = str(sample["reason"])
        expected_positive = bool(sample["expected_positive"])
        adaptive_flag = bool(sample.get("adaptive_medium_escalated", False))
        posterior_risk_score = sample.get("posterior_risk_score")
        for profile in profiles:
            key = (reason, profile)
            state = buckets.setdefault(
                key,
                {"tp_locks": 0, "fp_locks": 0, "positive_total": 0, "negative_total": 0, "locks": 0},
            )
            if posterior_risk_score is not None:
                calibration_samples.setdefault(key, []).append((float(posterior_risk_score), expected_positive))
            if expected_positive:
                state["positive_total"] += 1
            else:
                state["negative_total"] += 1
            if policy_should_lock(profile, reason, adaptive_flag):
                state["locks"] += 1
                if expected_positive:
                    state["tp_locks"] += 1
                else:
                    state["fp_locks"] += 1

    scored: dict[tuple[str, str], dict] = {}
    for key, state in buckets.items():
        tp = state["tp_locks"]
        fp = state["fp_locks"]
        neg = state["negative_total"]
        precision = (tp / (tp + fp)) if (tp + fp) else None
        disruption = (fp / neg) if neg else 0.0
        scored[key] = {
            **state,
            "precision": precision,
            "disruption": disruption,
        }
        if key in calibration_samples:
            pairs = calibration_samples[key]
            scored[key]["brier_score"] = brier_score(pairs)
            scored[key]["reliability_bins"] = reliability_bins(pairs)
    return scored


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
    metrics = hold_window_metrics(key_hold_times, now)
    active_held = metrics["held_keys"]
    max_repeats = metrics["max_repeats"]
    if (
        (active_held >= HOLD_MULTI_KEYS or max_repeats >= HOLD_MIN_REPEATS)
        and cooldown_allows(now, last_detection)
    ):
        return metrics
    return None


def hold_window_metrics(key_hold_times: dict, now: float) -> dict:
    """Prune hold buffers and compute repeat intensity metrics."""
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
    return {"held_keys": active_held, "max_repeats": max_repeats}


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


def zone_hop_detection_signal(
    zone_event_times: deque,
    now: float,
    last_detection: float,
    toddler_mode: bool,
) -> dict | None:
    """Pure detector for rapid non-adjacent zone-hopping movement."""
    while zone_event_times and zone_event_times[0][0] < now - ZONE_HOP_WINDOW_SECS:
        zone_event_times.popleft()

    stats = zone_hop_window_stats(zone_event_times)
    transitions = stats["transitions"]
    far_hops = stats["far_hops"]
    unique_zones = stats["unique_zones"]

    min_events = TODDLER_ZONE_HOP_MIN_EVENTS if toddler_mode else ZONE_HOP_MIN_EVENTS
    min_transitions = (
        TODDLER_ZONE_HOP_MIN_TRANSITIONS if toddler_mode else ZONE_HOP_MIN_TRANSITIONS
    )
    min_far_hops = TODDLER_ZONE_HOP_MIN_FAR_HOPS if toddler_mode else ZONE_HOP_MIN_FAR_HOPS
    min_unique_zones = (
        TODDLER_ZONE_HOP_MIN_UNIQUE_ZONES if toddler_mode else ZONE_HOP_MIN_UNIQUE_ZONES
    )

    if len(zone_event_times) < min_events or not cooldown_allows(now, last_detection):
        return None

    if (
        transitions >= min_transitions
        and far_hops >= min_far_hops
        and unique_zones >= min_unique_zones
    ):
        return {
            "events": len(zone_event_times),
            "transitions": transitions,
            "far_hops": far_hops,
            "unique_zones": unique_zones,
            "window": f"{ZONE_HOP_WINDOW_SECS:.1f}s",
        }
    return None


def zone_hop_window_stats(zone_event_times: deque) -> dict:
    """Compute transitions/far hops/unique zones from current zone event window."""
    compressed: list[str] = []
    for _, zone in zone_event_times:
        if not compressed or compressed[-1] != zone:
            compressed.append(zone)

    transitions = 0
    far_hops = 0
    for i in range(1, len(compressed)):
        prev = compressed[i - 1]
        curr = compressed[i]
        if curr == prev:
            continue
        transitions += 1
        pr, pc = ZONE_COORDS[prev]
        cr, cc = ZONE_COORDS[curr]
        manhattan = abs(pr - cr) + abs(pc - cc)
        if manhattan >= 2:
            far_hops += 1

    return {
        "events": len(zone_event_times),
        "transitions": transitions,
        "far_hops": far_hops,
        "unique_zones": len(set(compressed)),
    }


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
    risk_window = AdaptiveRiskWindowCalibrator()
    cadence = TypingCadenceEnvelope()
    signal_memory = TemporalSignalMemory()
    fusion_priors = dict(REASON_BAYES_PRIORS)
    early_walk_threshold = EARLY_WALK_POSTERIOR_THRESHOLD

    calibration = getattr(args, "fusion_calibration", None)
    if isinstance(calibration, dict):
        candidate_priors = calibration.get("reason_priors")
        if isinstance(candidate_priors, dict):
            for reason in FUSION_REASONS:
                if reason in candidate_priors:
                    fusion_priors[reason] = _clamp01(candidate_priors[reason])
        candidate_threshold = calibration.get("early_walk_posterior_threshold")
        if candidate_threshold is not None:
            early_walk_threshold = _clamp01(float(candidate_threshold))

    key_times:           dict[int, deque] = collections.defaultdict(lambda: deque(maxlen=200))
    key_hold_times:      dict[int, deque] = collections.defaultdict(lambda: deque(maxlen=200))
    zone_event_times:    deque            = deque(maxlen=120)
    keys_currently_held: set[int]         = set()
    walk_consecutive_hits = 0
    last_detection = 0.0
    last_input_event_utc: str | None = None

    def _fire(
        reason: str,
        walk_score: float | None = None,
        walk_threshold: float | None = None,
        posterior_risk_score: float | None = None,
        **log_kw,
    ):
        nonlocal last_detection
        nonlocal walk_consecutive_hits
        now_mono = time.monotonic()
        last_detection = now_mono
        if posterior_risk_score is None:
            reason_strengths = signal_memory.decayed_reason_strengths(now_mono)
            posterior_risk_score, _ = fused_posterior_risk_score(reason_strengths, priors=fusion_priors)
        posterior_risk_score = _clamp01(posterior_risk_score)
        msg = random.choice(messages)
        log.warning("%s DETECTED (%s)! %s",
                    entity.upper(), reason,
                    " ".join(f"{k}={v}" for k, v in log_kw.items()))
        severity_raw = reason_severity_weight(reason, log_kw)
        severity = _clamp01((0.65 * severity_raw) + (0.35 * posterior_risk_score))
        adaptive_medium_escalated = risk_window.observe_and_should_escalate(
            reason,
            now_mono,
            severity,
        )
        action_outcome = dispatch_detection_actions(
            args,
            msg,
            reason,
            adaptive_medium_escalated=adaptive_medium_escalated,
        )
        record = DetectionRecord(
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            entity=entity,
            reason=reason,
            sensitivity=args.sensitivity,
            toddler_mode=bool(args.toddler),
            metrics=log_kw,
            action_outcome=action_outcome,
            lock_profile=lock_profile(args),
            reason_severity=severity,
            adaptive_medium_escalated=adaptive_medium_escalated,
            posterior_risk_score=posterior_risk_score,
            walk_score=walk_score,
            walk_threshold=walk_threshold,
        )
        record_detection_event(record)
        write_runtime_heartbeat(
            args,
            force=True,
            last_detection_reason=reason,
            last_successful_input_event_utc=last_input_event_utc,
            now_monotonic=now_mono,
        )

        key_times.clear()
        key_hold_times.clear()
        zone_event_times.clear()
        keys_currently_held.clear()
        walk_consecutive_hits = 0

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
    write_runtime_heartbeat(args, force=True, last_successful_input_event_utc=last_input_event_utc)

    while True:
        try:
            kind, code = event_queue.get(timeout=1.0)
        except queue.Empty:
            write_runtime_heartbeat(args, last_successful_input_event_utc=last_input_event_utc)
            continue

        now = time.monotonic()
        last_input_event_utc = datetime.now(timezone.utc).isoformat()
        write_runtime_heartbeat(
            args,
            now_monotonic=now,
            last_successful_input_event_utc=last_input_event_utc,
        )

        # ── Key up ──────────────────────────────────────────────────────────
        if kind == "up":
            keys_currently_held.discard(code)
            continue

        # ── Hold / sit (autorepeat flood) ────────────────────────────────────
        if kind == "hold":
            hold_metrics = hold_detection_signal(key_hold_times, code, now, last_detection)
            if code not in HUMAN_HOLD_KEYS:
                micro_hold_metrics = hold_metrics or hold_window_metrics(key_hold_times, now)
                signal_memory.observe(
                    "sitting/standing",
                    hold_micro_signal_strength(micro_hold_metrics),
                    now,
                )
            if hold_metrics is not None:
                reason_strengths = signal_memory.decayed_reason_strengths(now)
                posterior_risk_score, per_reason = fused_posterior_risk_score(
                    reason_strengths,
                    priors=fusion_priors,
                )
                _fire(
                    "sitting/standing",
                    posterior_risk_score=posterior_risk_score,
                    per_reason_posteriors={k: round(v, 3) for k, v in per_reason.items()},
                    **hold_metrics,
                )
            continue

        # key_down from here ──────────────────────────────────────────────────
        keys_currently_held.add(code)
        if code not in HUMAN_HOLD_KEYS and code not in MODIFIER_KEYS:
            cadence.observe_keydown(now)
            zone = KEY_PRIMARY_ZONE.get(code)
            if zone is not None:
                zone_event_times.append((now, zone))

        zone_stats = zone_hop_window_stats(zone_event_times)
        zone_strength = zone_hop_micro_signal_strength(
            zone_stats["transitions"],
            zone_stats["far_hops"],
            zone_stats["unique_zones"],
            toddler_mode=bool(args.toddler),
        )
        signal_memory.observe("zone hopping", zone_strength, now)

        hop_metrics = zone_hop_detection_signal(zone_event_times, now, last_detection, args.toddler)
        if hop_metrics is not None:
            reason_strengths = signal_memory.decayed_reason_strengths(now)
            posterior_risk_score, per_reason = fused_posterior_risk_score(
                reason_strengths,
                priors=fusion_priors,
            )
            _fire(
                "zone hopping",
                posterior_risk_score=posterior_risk_score,
                per_reason_posteriors={k: round(v, 3) for k, v in per_reason.items()},
                **hop_metrics,
            )
            continue

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
        cadence_z = cadence.normalized_rate_z(metrics.rate)
        adjusted_rate = normalized_walk_rate(metrics.rate, cadence_z)
        score = walk_confidence(metrics.unique_keys, adjusted_rate, metrics.spread, thresh)
        adaptive_min = baseline.threshold()
        threshold = max(walk_score_min, adaptive_min)

        signal_memory.observe("walking", walk_micro_signal_strength(score, threshold), now)
        reason_strengths = signal_memory.decayed_reason_strengths(now)
        posterior_risk_score, per_reason = fused_posterior_risk_score(
            reason_strengths,
            priors=fusion_priors,
        )

        if (
            metrics.unique_keys >= thresh["min_keys"]
            and metrics.rate    >= thresh["min_rate"]
            and metrics.spread  >= thresh["spread"]
            and not (active_keys & HUMAN_HOLD_KEYS)
            and cooldown_allows(now, last_detection)
        ):
            required_hits = (
                1
                if posterior_risk_score >= early_walk_threshold
                else WALK_CONFIRMATION_REQUIRED
            )
            should_fire, walk_consecutive_hits = walk_temporal_gate(
                score,
                threshold,
                walk_consecutive_hits,
                required_hits=required_hits,
            )
            if not should_fire:
                continue
            _fire("walking",
                  posterior_risk_score=posterior_risk_score,
                  walk_score=score,
                  walk_threshold=threshold,
                  keys=metrics.unique_keys,
                  rate=f"{metrics.rate:.1f}/s",
                  normalized_rate=f"{adjusted_rate:.1f}/s",
                  cadence_z=f"{cadence_z:.2f}",
                  spread=f"{metrics.spread*100:.0f}%",
                  score=f"{score:.2f}",
                  threshold=f"{threshold:.2f}",
                  required_hits=required_hits,
                  per_reason_posteriors={k: round(v, 3) for k, v in per_reason.items()})
            continue

        walk_consecutive_hits = 0

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
