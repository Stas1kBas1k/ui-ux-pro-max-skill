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
The current list is at the end of section 12.

## 12. Rebuild from the player's recording, per-rod configuration, new interface

### Stage 1: audit (confirmed causes)
- **Shake clicked the wrong thing:** the colour method fired on the Roblox player list in 297 of 634
  recorded frames.
- **Fish lost on special rods:** the colour fish finder missed the fish on Stellarwave (0/7 frames) and
  locked onto red slash effects.
- **Stellarwave bar not found:** the standard bar detector does not see the bright capsule bar on the
  sign strip.
- **Lullaby clicked off the lit part:** it learned an input delay from lit sections changing, but on the
  real gauge a hit does not change them.
- **Full frames skipped the current state's detectors:** this reset the Lullaby history.

### Stage 2: fixes, measured on the recording (`tests/test_recording.py`, 21 tests)
| Check | Before | After |
|---|---|---|
| False shake clicks | 297 / 634 frames | 0 (real button still confirmed in 0.1 s) |
| Fish found (labelled frames) | 5/8 standard, 0/7 Stellarwave | 15/15 |
| Bar found (steered rods) | Stellarwave missed | 10/10 within 25 px |
| Stellarwave next sign | not implemented | correct sign at the correct position; low-confidence frames are not clicked |
| Lullaby clicks inside the lit part (replay) | not checked | 9/9 |

- **Shake:** a candidate is clicked only when it looks like one word and OCR reads it as SHAKE. The OCR
  runs in the background, and the result is remembered per position. The colour method is opt-in.
- **Fish:** an edge-based finder looks for a thin line that continues past the track, and rejects red
  slash effects.
- **Stellarwave:** a "capsule" reel profile follows the bright bar. The picker reads the 12-sign row,
  counts lit stars, and finds the next sign on the moving strip by shape. The top-row sign is the
  template, so it follows skins. It keeps the cursor on that sign, taps, and checks that the star lights.
- **Lullaby:** the half-moon gauge is read in polar coordinates (lit parts and pendulum angle). A click is
  sent only when the pendulum is inside a lit part now *and* when the click lands. The fish is not
  steered.
- **MiguRod:** the "!" marks on the track are found, and the bar aims away from them while keeping the
  fish.
- **Replay tool:** `python -m fischmacro.diagnostics.replay FRAMES --rod stellarwave --out DIR` runs a
  recording through the real engine and draws what it saw and sent.

### Stage 3: per-rod configuration and licensing groundwork
- **Per-rod definition** (`fischmacro/rods/config.py`): behaviour, reel layout, note, and how it was
  verified.
- **Editor schema:** one per rod. The simple fields come first; everything technical is under Advanced.
  Sensitivity is one slider that sets all three controller gains.
- **Profiles:** each rod, and each skin you add, is saved as its own profile. Edits are a draft until
  Save, with Revert and Recommended.
- **Licensing** (`fischmacro/licensing`): a provider interface checked once at Start. Development builds
  use an always-allowed provider. A server provider stub describes the one-device activation API
  (`/v1/activate`, `/v1/validate`, `/v1/deactivate`; signed token). The device id is a salted hash, so
  the raw machine id never leaves the PC. There is no fake protection: nothing is enforced until a
  server exists.

### Stage 4: new interface
The main window is now an HTML/CSS interface running inside the app (QtWebEngine, local files only),
connected to the same engine through one bridge (`fischmacro/ui/web_api.py`).
- **Dashboard:** one large Start/Stop button and status tiles (game, rod and skin, configuration,
  calibration, fish tracking, automation), plus session stats.
- **Rod Library:** searchable rod cards with filters. A side drawer shows the rod's skins, its
  configuration, and *Save and use* / *Use & start*.
- **Automation:** five steps (rod, skin, configuration, calibrate, start). Each step is ticked when it is
  done. Below them: Watch the game, Test this rod, Live view and the extras.
- **Profiles:** a list plus the editor (Save / Revert / Recommended, duplicate, rename, export, delete,
  import).
- **Settings tabs:**
  - General
  - Hotkeys (click, then press a key)
  - Diagnostics (live view with detections and the last inputs)
  - Advanced tools (the classic pages, in their own window)
  - Licence
  - About
- **Design:** near-black background, one violet accent, Inter font (bundled, OFL), and Lucide icons.
- **Classic interface:** still available under *Settings → General → Interface → Classic*, and used
  automatically if QtWebEngine is missing.

### Stage 5/6: every control connected
`tests/test_web_ui.py`:
- **Every call exists:** every `api("...")` call in the page must exist in the bridge.
- **Engine checks:** rod, skin and profile flows, settings, hotkeys, the licence screen, desktop actions,
  Start / Pause / Stop, and the live view are all checked against the engine.
- **Real page test:** the page is loaded in the real QtWebEngine. The test visits every section, opens a
  rod, and starts and stops fishing from the page, with no script errors.
- **Windows build:** the CI smoke test now also requires the "New interface loaded" log line from the
  built exe.

### Needs a live Fisch session (current list)
1. **Stellarwave:** the tap timing on your PC (signs are found correctly on the recording).
2. **Lullaby:** the lead time on your PC (*Lead* under Advanced; the default suits a small input delay).
3. **MiguRod:** the Shift counterattack press is implemented from a screenshot but was not seen in the
   recording. Slash avoidance is checked on the recording.
4. **Skins:** there are too many to list. Normal rods are the focus; a skin you add starts from its rod's
   settings.
5. **Tracking:** check it on your PC with *Observe only*, using Settings → Diagnostics.

## 13. Player feedback round (after the first Windows build)

| Report | Cause found | Change | Checked by |
|---|---|---|---|
| Lullaby "not really working" | The gauge centre came from the saved reel region. With the region 25-50 px off (another screen, or after calibrating), the lit part read as ending at 0.46-0.63 instead of 0.52, so clicks landed on the red. When the gauge was not found, the old colour reader took over, and it clicks off the lit part. | The real centre is searched for once (coarse, then fine; 88 ms) and remembered. The old reader is off on the real game. | `test_lullaby_gauge_found_when_the_region_is_off`: the lit part is correct with the centre off by +50/0, -40/+30 and +30/-25 px. The test game still plays Lullaby 11 hits / 0 misses. |
| Sensitivity too sensitive | The bar could flip hold/release every frame: 11-14 clicks a second in the test game. | Sensitivity now also sets a shortest hold/release (50 ms at 5). It only applies while the fish is near the bar's centre; near an edge the bar reacts at once. 10 = the old behaviour. Old profiles keep their number with the calmer meaning. | Test game, 3 seeds x 4 catches: 12/12 caught at both difficulties. Clicks 9.6 -> 5.5 per second on hard fish; time in bar 81.1% -> 79.6% (easy: 94%, unchanged). |
| Tracking could be better | Not reproducible without a clip from the player's PC. Looking further ahead did not help in the test game (73-77% vs 81%). | The calm zone above keeps full reaction when the fish nears an edge. | As above. A live clip is still needed. |
| Configuration hard to understand | Every section had its own Advanced toggle and technical names. | The basics come first in plain words: Sensitivity (Calm / Quick), Cast style, Wait after a catch, Rod hotbar key, plus the rod's own settings (Lullaby: Click timing). Everything else is behind one "Show all settings". | `test_editor_shows_only_what_the_rod_uses` |
| Add-ons etc. open a new window | Tool pages lived in a separate window. | They open inside the main window, over the content area, with Back / Esc. The sidebar keeps working. | `test_tool_windows_survive_the_event_loop` |
| Recast sooner | 2.6 s between the reel ending and the next cast (0.6 + 1.6 + 0.35). | 1.0 s (0.35 + 0.5 + 0.15). Up to 4 re-presses if a cast is ignored right after a catch. | Test game: 8.16 -> 7.63 s per catch (+7% catches/hour). Holds with a 2 s result screen (7.76 s). |
| Reel stops / fish does not hook | A frozen reel waited for the 120 s reel timeout; a dropped bite waited for the 25 s shake timeout. | If the fish is seen but nothing moves for 6 s ("Stuck after"), or shaking stops with no reel for 6 s, the rod is unequipped and equipped again (rod hotbar key twice) and cast again. Re-equip is now on by default. A reel where the fish cannot be seen is never cancelled. | `test_frozen_reel_is_cleared_by_reequipping_the_rod`, `test_a_moving_reel_or_an_unseen_one_is_never_cancelled`, `test_shake_that_stops_without_a_reel_recasts` |
| Real rod pictures | - | Downloaded on the player's PC from the Fisch wiki API (fischipedia.org, 50 rods per request) into `data/rod_images`, once. They are not shipped with the app. Rods without a picture keep the drawn art. Can be turned off in Settings. | `tests/test_rod_images.py`, with the wiki's real API answer. The download itself is not tested here: the wiki is blocked from the build container. |
