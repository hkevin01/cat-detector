# Changelog

All notable changes to this project are documented in this file.

## Unreleased

### Added

- Added weighted walk-confidence scoring to strengthen walk/burst detection quality.
- Added parser factory function to make production argument definitions testable as a single source of truth.
- Added dedicated tests for walk-confidence formula behavior.
- Added adaptive baseline calibration to estimate per-user typing envelope and shift walk thresholds conservatively.
- Added structured JSONL detection event records for longitudinal false-positive analysis.
- Added deterministic replay fixtures and replay harness support for edge-trace regression tests.
- Added property-based tests for walk-score monotonicity and cooldown monotonicity invariants.
- Added schema validation for structured detection JSONL payloads with dedicated tests.
- Added lightweight throughput benchmark guard test for walk metric computation.
- Added CI markdown lint workflow for all repository markdown files.
- Added Linux and Windows package-validate CI workflow for editable install and wheel/sdist artifact validation.
- Added pinned constraints files for Linux and Windows dev/build tooling reproducibility.

### Changed

- Updated detection engine walk trigger to require both threshold gates and minimum confidence score.
- Split the detection loop into pure scoring components plus side-effect dispatch for stricter unit isolation.
- Updated repository lint workflow to check the full codebase.
- Added a dedicated GitHub Actions test workflow (Python 3.11/3.12) that installs dev dependencies and runs pytest.
- Updated lint, test, and Windows build workflows to consume pinned constraints.
- Updated documentation to reflect safety-first behavior and removal of runtime input grabbing.
- Updated install/build script messaging to match current lock defaults.
- Switched build backend to setuptools.build_meta.

### Fixed

- Removed dead local variable in detection engine.
- Fixed CLI tests that were validating a synthetic parser instead of production parser configuration.
- Fixed multiple lint violations across test modules (unused imports, ambiguous names, import ordering).
- Removed stale README statements that described obsolete freeze/grab behavior.
- Reduced adaptive baseline hot-path overhead by caching thresholds and recomputing periodically.
- Narrowed optional-property-test skip handling to ImportError so runtime errors are not masked.

## 2.0.0

- Introduced cross-platform detection architecture for Linux and Windows.
- Added multi-algorithm detection coverage and expanded automated tests.
