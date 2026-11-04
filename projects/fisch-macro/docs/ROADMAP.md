# Moon Macro - roadmap (agreed 4 Nov 2026, building starts after the weekly limit resets)

Rules that do not change: screen capture + normal Windows input only. No game memory reading, no injection,
no hiding from or defeating anti-cheat. Nothing written to drive C. No player names/stats committed.
Nothing claimed as working in the game unless it was checked on the player's recording.

## 0. No more manual recording (player: "recording every rod and add-on takes ages")
- **Black box, always on:** keeps the last ~60 s of the reel / menu areas (small, low-res) in memory and
  saves a clip + log by itself whenever something goes wrong: fish lost, reel stuck, stall, an add-on step
  that did not get the expected result. Normal play is the recording.
- **Add-ons check their own result** (appraise: did the trait text change? totem: did the weather change?
  recharge: did the power % go up?) and save a picture of the failing step.
- **One button "Send report"** zips everything since the last report. Later: straight upload, or a
  Remote Control folder so Claude reads the reports on the player's PC with no upload step.
- Menu layouts (appraise, totems, aquarium...) researched from the wiki / videos first; the player only
  sends a screenshot when that is not enough.

## 1. Make the existing add-ons actually work (first, before anything new)
Player: "auto appraise with gamepass doesn't work, all add-ons pretty much don't work".
- Every add-on gets a **Test now** button: runs once, logs each step, saves a picture of what it saw at each
  step into the diagnostics zip. A failing add-on then shows exactly which step failed.
- Player records each add-on (Record reels + a new "Record add-on runs" switch), exports, uploads to Diagnos.
- Fix order: Auto Appraise (gamepass and normal), Sovereign recharge, Auto Totem, Hunt detect, Auto Reconnect,
  potions, Discord webhooks.

## 2. Fisch: features from the other launcher, built our own way
Needs a one-line description + screenshot from the player for each before building:
Auto Aquarium, Trader, Currently Trading, Radar, Fish Skip, Lullaby Buff Cycle, Auto Nuke Capture,
Auto Angler, Enchant, Treasure Appraise, Auto Harpoon, Passive mode, Mastery Mode 4 Only, catch preview.
Still waiting on recordings: Halibut Crimson ("!" marks), Blade of Glorp (laser warning), Lullaby (new clock).

## 3. Moon Launcher (own name, own design - not a copy of anyone's)
Library of macros, install / update / open, subscription + key screen, install folder picker (never C:),
update channel. Fisch becomes the first macro inside it.

## 4. Website + payments + device-locked keys
Landing page on Vercel, accounts, Stripe/PayPal subscription (test mode first), licence server
(fischmacro/licensing has the design: one device per key, signed token, offline start).
The repo must be made private before selling.

## 5. Next games
Not Blade Ball (auto-parry is a cheat against other real players). Pick PvE / grinding games next; each one
needs the player's recordings of that game.
