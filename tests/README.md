# cat-detector test suite

## Coverage model

The test suite validates five layers:

1. Pure unit logic

- Constants and zone spread math.
- Walk-confidence score properties.

1. Engine integration

- End-to-end event stream processing through the shared detection engine.
- Walk, streak, hold/sit, paw press, and cooldown behavior.

1. Regression guardrails

- Human typing and navigation patterns that must never trigger detection.

1. Platform abstraction

- Notification, lock, and audio side effects under Linux and Windows mocks.

1. Deployment and packaging smoke checks

- Project metadata, service file structure, and installer script syntax.

1. Deterministic replay traces

- Recorded edge-case event traces replayed through the engine for reproducible regressions.

1. Property-based invariants

- Score monotonicity and cooldown monotonicity verified over generated input ranges.

## Test architecture

- Platform imports are stubbed in conftest fixtures so tests run without hardware devices.
- EngineHarness injects synthetic keyboard events and captures detector outputs.
- Parser tests use the production parser builder to prevent drift between implementation and tests.
- Replay fixtures are stored under tests/fixtures/traces and loaded via trace_loader.

## Current expectations

- Input grabbing/freeze logic is not part of runtime behavior.
- Locking is opt-in.
- Detection decisions remain deterministic and formula-based.
