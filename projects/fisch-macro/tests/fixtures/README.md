# Test fixtures

The images here are **synthetic** screenshots rendered by the built-in simulator
(`fischmacro/simulation/game.py`) in the default calibrated layout, at several
resolutions (720p, 900p, 1080p = 150 % DPI equivalent), with sensor noise and
JPEG compression variants. Each image has a `.json` file with its ground truth.

They prove the detectors work on known inputs. They are **not** real Fisch
screenshots, so they do not prove the default colours match the live game.

## Adding real screenshots

1. Calibrate a profile against the live game.
2. Press the diagnostic-snapshot hotkey (default **F11**) at the moment you
   want to capture (reel minigame, shake prompt, ...).
3. Copy `raw.png` from the snapshot folder into `tests/fixtures/real/` and
   write a `.json` next to it with the fields you want to assert
   (`state`, `fish_x`, `bar_left`, `bar_right`, `progress`, `button`).
4. Copy the profile JSON to `tests/fixtures/real/profile.json`.
   `tests/test_real_fixtures.py` runs automatically when that folder exists.
