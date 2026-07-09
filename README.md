# cat-detector

Cross-platform keyboard anomaly detection for cat paws and toddler palm-slams.

## Project Status

This project is in a safety-first state:

- Input grabbing and keyboard freezing behavior are removed.
- Detection is non-destructive by default.
- Optional lock behavior is explicit and opt-in.
- Detection uses deterministic formulas and thresholds, covered by automated tests.

## What Changed Recently

### Safety hardening

- Removed runtime grab/freeze execution paths from the event engine.
- Kept a compatibility placeholder for pause-related settings so older integrations do not break.
- Ensured event processing never blocks keyboard flow.

Benefits:

- Eliminates stuck-key and lockout classes of failure.
- Preserves protective detection while reducing operational risk.
- Keeps backward compatibility for existing automation that still passes legacy pause parameters.

### Detection quality upgrade

The walk/burst detector now includes a normalized confidence score in addition to threshold gates.

For a sensitivity profile with thresholds:

- min_keys
- min_rate
- min_spread

the score is:

score = 0.45 x (unique_keys / min_keys)
      + 0.35 x (event_rate / min_rate)
      + 0.20 x (zone_spread / min_spread)

A walk event now requires:

1. All original hard gates pass.
2. score >= profile-specific minimum.

Benefits:

- Stronger separation between borderline activity and true paw-walk bursts.
- Better explainability in logs through explicit score values.
- Stable behavior under fast human typing edge cases.

### Adaptive baseline calibration

The detector now estimates a per-user typing envelope from non-triggering windows and
raises walk-score thresholds conservatively.

Calibration characteristics:

- Uses rolling score samples from likely-human windows.
- Uses a warmup period before adaptation applies.
- Never lowers the static threshold.
- Caps upward shift to a bounded maximum.

Benefits:

- Reduces false positives for unusually fast or bursty human typists.
- Keeps safety behavior conservative by only shifting upward.
- Preserves deterministic fallback when baseline data is sparse.

### Structured detection records

Each detection now emits a JSONL event record for longitudinal analysis.

Record payload includes:

- reason and entity
- metric values at trigger time
- walk score and active threshold
- sensitivity profile and mode
- UTC timestamp

Benefits:

- Enables offline false-positive analysis and trend monitoring.
- Supports reproducible tuning using real observed detector outputs.
- Improves auditability of production detections.

## Detection Algorithms

The engine evaluates multiple signatures in parallel:

1. Walk/Burst

- Uses unique-key count, event rate, and zone spread.
- Adds weighted confidence scoring for stronger discrimination.

1. Paw Press

- Detects simultaneous non-modifier key clusters.
- Includes explicit Enter-plus-simultaneous-key handling.

1. Hold/Sit

- Detects repeated hold floods and multi-key hold patterns.
- Excludes known human hold/navigation keys.

1. Streak

- Detects rapid same-key repeats, with toddler-specific thresholds.

## Architecture

- Platform adapters feed normalized events into a shared queue.
- Core detection engine is platform-agnostic and deterministic.
- Notification, audio, and lock handlers are isolated side-effect layers.

Core implementation anchors:

- Detection engine: cat_detector.py
- Walk confidence formula: cat_detector.py
- Parser source-of-truth builder: cat_detector.py
- Linux service unit: cat-detector.service

## Reliability and Verification

Quality gates currently enforced in repository checks:

- Full test suite for unit, integration, regression, platform abstraction, and deployment smoke coverage.
- Deterministic replay traces for edge-case regression scenarios.
- Property-based invariants for score monotonicity and cooldown logic.
- Structured detection-record schema validation tests.
- Lightweight throughput regression guard for scoring hot path.
- Linting across the full repository scope.
- CI test workflow across Python 3.11 and 3.12 with dev dependency installation.
- CI markdown lint workflow for all markdown documentation.
- Linux and Windows packaging-validation workflow for editable installs and wheel/sdist artifacts.
- Pinned Linux/Windows constraints files for reproducible tooling resolution.
- Build metadata and packaging scripts aligned with current defaults.

## Documentation Notes

Older references to input grabbing, pause threads, or frozen keyboard behavior are obsolete and have been removed from this documentation.

## Changelog

See CHANGELOG.md for versioned details and rationale.
