# Repair report: Start, Lullaby, recharge, calibration, rod minigames

The macro is external only. It reads the screen and sends normal mouse and key input. It does not read game
memory, inject anything or bypass anti-cheat. **No live Roblox session was available while this work was
done.** Everything below was tested against the built-in Fisch simulator and real screenshots, not in the
live game. Items that need live checking are marked **verify in game**.

## 1. Root causes found

| Symptom | Root cause | Fix |
|---|---|---|
| Start does nothing (about 80% of the time) | Start focused Roblox, then the UI showed the mini window. Showing it took focus back from Roblox. With *require focus* on, the engine waited silently with "Waiting for Roblox to be focused". | The mini window can no longer take focus (`WA_ShowWithoutActivating`, `WindowDoesNotAcceptFocus`) and is shown **before** the engine starts. The engine retries focusing Roblox 4 times in the 6 s after Start or Resume, then shows "Click into Roblox". Each start stage (profile valid, capture started, game window found, input enabled, game focused) is logged in `start_report` and shown on the Diagnostics page. If Start fails, a dialog names the failed stage. |
| Duplicate engines after fast Stop/Start | Every thread pair shared one stop flag. A thread that was slow to stop saw the flag cleared again by the next Start and kept running alongside the new pair. | Each start gets its own stop event, passed to its threads. A second Start while running is refused. |
| Lullaby mode changes when pressing Start | `_ensure_lullaby_mode` pressed Q up to 7 times when OCR could not read the mode name, without knowing the current mode. The solver also pressed Q `mode_presses` times at the start of every catch. | `automation/lullaby_mode.py`: Q is pressed only when exactly one mode name is readable. Each press must show a *different* name, or switching stops. If no name is readable, nothing is pressed. The check runs once per Start. Q is never pressed during a catch; `mode_presses` is ignored. |
| Sovereign recharge spam | 1) The default power region was a guess that covered the bait count and hotbar numbers. 2) `parse_power` accepted any bare number. 3) One safe point could use up to 10 relics, with no cooldown and no limit per session. | The power region is off until the user picks it. Only text with `%` or `/100` is accepted, and two readings in a row must agree. A state machine (`RechargeMachine`: idle → in progress → complete / failed → cooldown → disabled) allows at most 4 relics per attempt, and each must raise the power. A failure starts a 5-minute cooldown; after 3 failures the add-on stops for the session. Stop or pause cancels an attempt. |
| Lost casts cost 45 s each | If the game ignored a cast press (for example, still showing the catch result), the macro waited the whole bite timeout with no line in the water, then recovered and often lost the next cast too. | Event-driven cast check: once the power bar has been seen on an earlier cast, a press that shows no bar within 0.7 s is released and repeated (at most twice). |
| Stellarwave model wrong | The solver assumed a 4-sign wheel and a single click. | 12 signs; the one asked for is shown above the bar and follows a fixed order. State machine AIM → VERIFY → hit/miss: each click is checked (the sign asked for must change), a wrong sign is never clicked twice, and after 3 tries the solver waits for the next sign. |
| Halibut solver clicked targets | The game has nothing to click. Harpoons land on "!" marks, and those thin marks could be taken for the fish. | Halibut sends no minigame input. A fish "jump" is believed only when it is seen in the same place for 3 frames, which stops "!" marks from pulling the bar away. |
| No MiguRod support | — | Presses the MiguRod key (Shift by default) once per timing bar, aimed at the middle, with the learned input delay. |
| Calibration accepted one lucky look | One window of frames decided everything. | Sample-based calibration (section 6). |

## 1b. Checked on real screenshots (sent by the player, kept as tests)

| Screenshot | What it showed | Result |
|---|---|---|
| Stellarwave reel (2) | The reel bar itself is made of 12 zodiac glyphs, shuffled every catch; the fixed Aries..Pisces row with stars is above it. The glyph-filled track broke the track-based tracker. | New fallback: the catch bar is the long run of columns bright from top to bottom. Fish within 1 px, bar edge within 5 px on both shots. |
| Halibut Harpoon reel | The "!" is an icon **above** the bar next to the fish icon, not on the track. | Fish within 2 px, bar within 6 px. No clicks. |
| MiguRod counterattack | Red bar, orange diamond in the middle, white line sweeping, SHIFT prompt. | The red bar is found first, then the line and the diamond are read inside it: line within 0.4% of the bar, diamond centred. |
| Sovereign power | "90% Power" under an enchant line full of other percentages, plus "Press (G) To Open". OCR found nothing in the 3-line box. | OCR re-reads low, wide boxes line by line; the number next to "Power" wins; enchant text alone reads as nothing. Reads 90. |

Because of this, the earlier Stellarwave sign-clicking model (one target sign shown above the bar) was
wrong. The Stellarwave preset now only reels, and sign picking stays off until it's confirmed how a sign is
picked.

## 2. Research used

- **Fisch wiki (Stellarwave Melody):** 12 zodiac signs appear above and on the bar. The order above the bar is
  fixed: Aries → Pisces. Mastery quest: "Click the correct star sign 4 times in a row".
- **Fisch wiki (MiguRod):** "if you manage to dodge all the slashes, a minigame will appear above the control
  bar, where it requires you to press shift on the middle"; a hit gives a large progress boost. *How* the
  slashes are dodged is not documented, so slash dodging is **not automated**.
- **Fisch wiki (Halibut Harpoon):** harpoons home in on "!" spots and add progress while the fish is in the bar.
  There is nothing to click.
- **OpenMacro changelog:** confirms these minigames need dedicated handling, and that Sovereign recharge must
  check the result. No code was copied. OpenMacro-XTernal reads game memory, so its approach was **not** used.

## 3. Test report (all run in this repository; none skipped silently)

New test files: `tests/test_reliability.py`, `tests/test_calibration_session.py`. New rod tests are in
`tests/test_rod_minigames.py`; diagnostics, wizard and observe-only tests are in `tests/test_ui.py`.

- **Start/Stop:** 15 Start/Stop cycles with fast and slow gaps. A second Start is refused, exactly one engine
  thread pair runs, and all inputs are released after every Stop. Restarting after a full stop fishes again.
  A broken profile fails at the "profile valid" stage, with no threads left behind.
- **Lullaby:** a mode already set gets 0 presses. Switching stops on the right mode. An unreadable mode gets 0
  presses. A key that does nothing gets 1 press, then stops. Text naming several modes (an open menu) is
  ignored. 10 repeated Starts give 0 presses. The engine checks once per Start.
- **Recharge:** stops at the target. At most 4 relics per attempt. A relic with no effect over 200 simulated
  catches (more than an hour) uses exactly 3 relics, then the add-on is disabled. No new reading means the
  attempt fails instead of looping. The attempt can be cancelled.
- **Casting:** with a 2.6 s result screen, every lost cast is pressed again. 5/5 catches, no "no bite"
  timeouts.
- **Stellarwave:** 3/3 catches with ≥12 correct signs in order and few misses. A wrong look-alike is never
  repeated, and the solver gives up after 3 tries and resumes on the next sign.
- **MiguRod:** 2/2 catches, every timing bar hit, 0 misses. Kept separate from Stellarwave: neither solver
  scores on the other's screen.
- **Halibut:** 3/3 catches, harpoons land, no rod-key presses. The jump filter is unit-tested.
- **Calibration:** agreeing looks finish after the minimum of 5. Scattered looks need more. One wrong look is
  dropped as an outlier and the median is used. "Never seen" and "keeps disagreeing" fail with a reason. A
  wrong region fails validation and nothing is saved. End-to-end on simulated frames, it finds the reel
  within 2%.
- **UI:** Diagnostics page, setup wizard (all 8 steps, step 1 requires the acknowledgement), and observe-only
  mode (no input reaches the backend).

Full suite on Linux: **250 passed, 1 skipped** (the skip is a generic real-screenshot test with no labelled cases yet; the real Plaguereaver and SHAKE screenshots are tested in test_live_fixes.py). The Windows CI workflow runs the same suite.

## 4. Performance (simulator, 3 seeds; `python -m fischmacro.simulation.benchmark`)

| Scenario | Before | After |
|---|---|---|
| Normal game, 60 cycles | 60/60 caught, 8.29 s per cycle, 434 catches/h | 60/60, 8.29 s, 434 catches/h (unchanged) |
| Result screen outlasts the post-catch wait (2.6 s), 30 cycles | **7/30 caught**, 185 s per cycle, **19.5 catches/h**, 167 s per cycle stuck waiting for a bite, one error stop | **30/30 caught**, 8.76 s per cycle, **411 catches/h** |
| Fish found after the reel appears | 25 ms (1 frame) | 25 ms (1 frame) |
| Vision time per frame (p50 / p95) | 2.84 / 7.41 ms | 2.88 / 7.04 ms |

The normal loop was already event-driven (bite, shake and reel detection react on the next frame). The real
waste was the 45 s lost on every ignored cast, which is now gone. Fixed waits that remain are configurable
and unverified in game: the 0.35 s pre-cast delay, the 1.6 s post-catch delay and the 0.6 s reel-end grace.
Lower them only after watching a few catches.

## 5. Rod compatibility matrix

| Rod | Handling | Status |
|---|---|---|
| Any normal rod | Colour-free reel tracking, PD/MPC control | Simulator 80/80 on 40 random skins; real Plaguereaver screenshot in the tests |
| Lullaby | Clicks only on lit sections, learned delay, verified mode switch | Simulator; **verify in game**: lead time |
| Stellarwave Melody | Reeling on the glyph-filled bar (real screenshots); sign picking off | **How a sign is picked is not confirmed**; the AIM/VERIFY click solver exists (kind `stellarwave`) but is off by default |
| MiguRod | Precision tracking + Shift when the line is on the diamond | Real screenshot + simulator; **verify in game**: position above the reel, timing; slash dodge not automated |
| Halibut Harpoon | No clicks, fish-jump filter | Real screenshot + simulator |
| Pinion's Aria, tryhard rods | Precision tracking, wider margin | Simulator |
| Sovereign | Recharge add-on (bounded) | Logic tested; **verify in game**: relic flow |

## 6. Calibration tutorial

1. Open Roblox in Fisch, hold your rod and stand at water.
2. In the app: **Calibration → Auto-calibrate** (or step 5 of the Setup wizard).
3. In Roblox: cast, wait for the bite, and **play the reel by hand** until the app says it is done (about
   3-10 s of reel).
4. It takes a look every 0.5 s, needs at least 5 looks that agree (more if they scatter), drops outliers,
   uses the median, then checks the result with the real detectors on the reel frames it saw. **Only a
   result that finds fish and bar in at least 70% of those frames is saved.**
5. If it fails, it says why: the reel was never seen, the looks disagree, or validation failed. Nothing
   changes in that case. Press it again to retry, or **Cancel** at any time.
6. Manual fallback: **Set regions by hand** (F10). Drag boxes for the reel bar, progress bar and shake area,
   then repeat the validation step of the wizard.

## 7. Skins

The reel is tracked by shape and contrast, not colour (`vision/reel_adaptive.py`). 40 random simulated skins
and the real Plaguereaver skin are tested. Other real skins are untested. The skin field in the profile is a
label only. If tracking looks wrong, the Diagnostics page shows the fish and bar confidence. Recalibrate, or
make a profile for that skin.

## 8. Install and start

1. Download the Windows build from the CI artifact and unzip it to `D:\MACROS` (nothing is written to C:;
   data is kept next to the exe).
2. Run `FischMacro.exe` and press **Dashboard → Setup wizard**.
3. Press **Start** (F6). Roblox is brought to the front; if not, click into it. F7 pauses, F8 stops.

## 9. Troubleshooting

- **Start does nothing:** Diagnostics → *Last Start* shows the failed stage.
- **It decides but nothing happens in game:** check that *Observe only* is off (Diagnostics).
- **Lullaby mode was not changed:** the mode name must be readable on screen; the log says why.
- **Recharge stopped:** see *Sovereign recharge* in Diagnostics (cooldown or disabled, with the reason).
  Re-pick the power box.
- **Calibration fails:** follow the reason shown, or use the manual fallback.
- Everything else: the Troubleshooting table in the README.

## 10. Limitations (honest)

- Nothing here was run against the live game. All results come from the simulator and saved screenshots.
- MiguRod slash dodging is not automated, because the mechanic is not documented.
- Stellarwave sign matching uses outline shapes. Real zodiac glyphs were not available as test images.
- The Sovereign relic flow, the Halibut Harpoon Gun key (Q, off by default) and the post-catch timings are
  unverified.
- The OCR-based Lullaby mode check depends on the mode name being visible on screen.

## 11. Tracking engine, rod modules, Rod Library and redesign

### Fish tracking
**Root cause:** the reel step steered on raw detections. When the fish was missed for a single frame (a
zodiac glyph, the fish over the bar edge, a "!" icon), the mouse was released at once. A single wrong
detection was steered on as if it were true.

**Fix:** `automation/tracking.py` follows the fish and the bar between frames (position plus speed),
which the reel controller now steers on. It:
- ignores a far-away detection until it has been seen 3 times;
- catches up within a few frames when the fish turns or speeds up;
- carries on along the fish's path for up to 0.3 s when the fish is missed;
- reports the fish as lost after that, rather than steering on a guess;
- reports direction, speed and confidence.

The existing PD/MPC controller, which predicts ahead, learns the hover duty and adapts to small or
low-control bars, is unchanged and gets the cleaner input.

| Simulator, 30 catches, difficulty 0.6 | Fish inside the bar (old → new) | Time per catch (old → new) |
|---|---|---|
| Clean detection | 87.5% → 87.2% (same) | 8.2 s → 8.3 s |
| 20% of frames miss the fish, 5% put it in the wrong place | 70.1% → **84.6%** | 10.0 s → **8.4 s** |

Live engine on the test game (`python -m fischmacro.simulation.perf`):

| Measure | Result |
|---|---|
| Frame rate | 77 fps |
| Capture + vision while reeling (p50 / p95) | 2.8 / 3.8 ms |
| Vision per frame (p95) | 8.5 ms |
| CPU use | 43% of one core |
| Peak memory | 127 MB |
| Engine start | 20 ms |
| Window build | ~0.7 s |

Screen capture on Windows costs more than the simulator's capture; measure it with the Diagnostics page.

### Rod modules and on-screen prompts
- Each special rod is its own module in `fischmacro/rods/`, and `rods/__init__.py` lists, for each rod:
  - its settings, split into simple and advanced;
  - the on-screen events it handles;
  - how well it is verified.
- The modules are `lullaby`, `stellarwave`, `migu`, `halibut` and `targets`. Standard reeling is shared
  by all rods.
- `rods/prompts.py` reads key prompts off the screen with OCR in the background (~0.7 s per read on this
  machine), because OCR is too slow for every frame:
  - It reads "SHIFT" from the real MiguRod screenshot.
  - Only allow-listed keys are ever pressed: shift, space, ctrl, alt.
  - MiguRod presses the key shown, at the moment the line reaches the diamond. If the bar is still up a
    second later, the press did not register, and it allows exactly one more press.
- Not automated, because neither mechanic is confirmed:
  - picking Stellarwave signs (the solver exists but is off);
  - dodging MiguRod slashes.

### Rod Library, profiles, UI
- **Rod Library:** about 200 rods as cards with generated artwork.
  - Search, plus filters: Special minigame, Favourites, Recent, Configured.
  - Skin cards for each rod.
  - Each rod (and each skin that needs it) gets its own saved profile, built from your screen
    calibration plus the rod's recommended settings.
  - Changes are a draft until Save, with an "Unsaved changes" marker.
  - Simple settings: tracking mode and sensitivity. Everything technical is under Advanced.
- **Navigation:** five sections.
  - Dashboard: status cards plus Start / Pause / Emergency stop.
  - Rod Library.
  - Automation: Fishing, Setup & tests, Add-ons, Hunts, Assistant.
  - Profiles: cards, plus "Reset to recommended".
  - Settings: General, Hotkeys, Vision & calibration, Diagnostics, Logs & stats, About.
- **Setup & tests** replaces the old manual screen with six plain steps:
  1. Rod and skin.
  2. Calibration.
  3. Test detection.
  4. Test the rod minigame (runs the rod's minigame in the test game).
  5. Reset.
  6. Guided setup.
- **Logo:** a new SVG logo in the sidebar, on the splash screen and as the window and exe icon. The new
  default theme is "Nebula".

### Needs a live Fisch session
1. MiguRod: the counterattack bar's position above the reel, and the timing of the press (Diagnostics →
   "Rod minigame log" shows each press).
2. Stellarwave: how a sign is picked (needed before sign picking can be switched on).
3. Tracking on your PC: start with *Observe only* on, play a reel by hand, and check "Fish tracking" in
   Diagnostics.
4. Skins: there is no built-in skin catalogue. Add a skin from its rod's card, then calibrate it once.
