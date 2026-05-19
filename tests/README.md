# cat-detector — Test Suite

## Structure

| <sub>File</sub> | <sub>Type</sub> | <sub>Purpose</sub> |
|------|------|---------|
| <sub>`conftest.py`</sub> | <sub>Infrastructure</sub> | <sub>Platform stubs (evdev/pynput/winotify), `EngineHarness`, fixtures</sub> |
| <sub>`test_unit_constants.py`</sub> | <sub>Unit</sub> | <sub>Constants, `zone_spread()`, key sets, messages</sub> |
| <sub>`test_zone_spread_parametric.py`</sub> | <sub>Unit (parametric)</sub> | <sub>Every zone tested with a representative keycode</sub> |
| <sub>`test_integration_detection.py`</sub> | <sub>Integration</sub> | <sub>Full engine: paw, streak, walk/burst, hold/sit, cooldown</sub> |
| <sub>`test_regression_false_positives.py`</sub> | <sub>Regression</sub> | <sub>Human typing patterns that must NEVER trigger detection</sub> |
| <sub>`test_toddler_mode.py`</sub> | <sub>Feature</sub> | <sub>`--toddler` thresholds, messages, zero lock delay</sub> |
| <sub>`test_cli_args.py`</sub> | <sub>CLI</sub> | <sub>Argparse defaults — `--lock` on by default, `--no-lock`, `--toddler`</sub> |
| <sub>`test_platform_abstraction.py`</sub> | <sub>Platform</sub> | <sub>`notify()`, `lock_screen()`, `play_meow()` on Linux & Windows stubs</sub> |
| <sub>`test_deployment.py`</sub> | <sub>Deployment</sub> | <sub>Import smoke, `pyproject.toml`, service file, `install.sh`</sub> |
| <sub>`test_windows_vk_map.py`</sub> | <sub>Platform</sub> | <sub>Windows VK→evdev translation correctness</sub> |

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