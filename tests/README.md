# cat-detector — Test Suite

## Structure

| File | Type | Purpose |
|------|------|---------|
| `conftest.py` | Infrastructure | Platform stubs (evdev/pynput/winotify), `EngineHarness`, fixtures |
| `test_unit_constants.py` | Unit | Constants, `zone_spread()`, key sets, messages |
| `test_zone_spread_parametric.py` | Unit (parametric) | Every zone tested with a representative keycode |
| `test_integration_detection.py` | Integration | Full engine: paw, streak, walk/burst, hold/sit, cooldown |
| `test_regression_false_positives.py` | Regression | Human typing patterns that must NEVER trigger detection |
| `test_toddler_mode.py` | Feature | `--toddler` thresholds, messages, zero lock delay |
| `test_cli_args.py` | CLI | Argparse defaults — `--lock` on by default, `--no-lock`, `--toddler` |
| `test_platform_abstraction.py` | Platform | `notify()`, `lock_screen()`, `play_meow()` on Linux & Windows stubs |
| `test_deployment.py` | Deployment | Import smoke, `pyproject.toml`, service file, `install.sh` |
| `test_windows_vk_map.py` | Platform | Windows VK→evdev translation correctness |

## Running

```bash
# All tests (from project root)
pytest

# One file
pytest tests/test_integration_detection.py -v

# Only unit tests
pytest tests/test_unit_constants.py tests/test_zone_spread_parametric.py -v

# Only regression (false-positive guard)
pytest tests/test_regression_false_positives.py -v

# With coverage
pip install pytest-cov
pytest --cov=cat_detector --cov-report=term-missing
```

## Notes

* Tests run on **any platform** — evdev, pynput, and winotify are stubbed.
* The `EngineHarness` drives `_detection_engine` in a daemon thread and
  patches `notify()` to record detections without touching the desktop.
* Integration tests use `h.flush(secs)` to give the engine time to process
  queued events — keep this small but > 0 to avoid flakiness.
* Regression tests (`test_regression_false_positives.py`) are marked as
  **critical** — a single false positive here is a ship-blocker.
