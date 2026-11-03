# Special rods: research, support and how to test them

Every rod below was looked up on the Fisch wiki (fischipedia.org, 1 November 2026: each rod's own page, plus a
full-text search of the wiki for "custom UI", "Charge Meter", "Special Action", "holding an input", "rhythm" and
"lanes"). The mechanics are the wiki's own words, shortened. Nothing is guessed: when a page does not say what to
press or what the UI looks like, the rod is marked **needs footage**.

The same data is in the app: open a rod in the **Rod Library** to see what it does in the game, what the player
does, what the macro does and how well that is checked. Source: `fischmacro/rods/catalog.py`.

## How the macro handles the different kinds

| Kind | Rods | What the macro does | Checked |
|---|---|---|---|
| Lullaby metronome | Lullaby and its skins (Hollowed Harp, Seastrum, Porcelain Chord, Serenity, Nameless Illuminator) | One click on every pass over every lit part, aimed at the middle. Finds the gauge's real centre itself. Reads recoloured skins from their own dark/light levels; Hollowed Harp's paler lit parts and thicker ring are found by a second test. | Your recording (4/4 passes, all on the lit part; also pale and tinted copies, and the centre 50 px off). Hollowed Harp: your 3 screenshots (centre found exactly). |
| Falling objects to catch | Pinion's Aria (notes), Santa's Miracle Rod (presents), Starshell Rod (shells) | Finds anything moving down toward the bar (any colour or shape). Moves the bar under the next one when the fish stays inside. | Test game: objects caught 14% -> 50% (margin test), every fish still caught. |
| Inverted controls | Dreambreaker after 40% progress - and any rod | Watches how the bar answers hold / release; when it is clearly reversed for 5 frames, flips the input. | Test game: 0/9 -> 9/9 catches with inversion; 0 false flips in 24 normal catches. |
| Special Action key | Dutchman's Rod | Presses your Special Action key every 2.5 s during the catch (set the key first). | Unit test (key pressed only when set). |
| Slashes to dodge | MiguRod | Keeps the bar away from the slash marks. | Your recording. |
| Zodiac signs | Stellarwave Melody | Taps the signs in order and checks each star. | Your recording. |
| Harpoon marks | Halibut Harpoon | Ignores the '!' marks. | Real screenshot. |
| Charge meter bonus | Cupid's Bow, Maelstrom, Apollo's Sunshot, Sand Castle Caster, Acidgrinder, Lemonade Serenade | Normal tracking catches the fish; the optional meter bonus is not automated yet. | - |
| Custom look / passive effects | Masterline Rod, Doomsekkar, Eldritch, Boglin Branch, Jack-o-Blazer, Tiki, ... (see table) | Normal tracking: nothing to press. The reel is found by shape and contrast, not colour. | Not on these rods' UIs (no footage). |

## Testing table

| Rod | Special mechanic (wiki) | UI detected | Automation implemented | Tested | Availability |
|---|---|---|---|---|---|
| Halibut Harpoon | 15-35 harpoons home to random spots marked '!'. | Yes - read on screen | Yes | Player's recording / screenshots | obtainable |
| Lullaby | A pendulum swings across a half-moon metronome with lit sections; Q cycles modes. | Yes - read on screen | Yes | Player's recording / screenshots | limited |
| MiguRod | 3 slashes appear on the minigame (every 3 catches / 41% per fish movement); the bar is cut where a hit lands. | Yes - read on screen | Yes | Player's recording / screenshots | unobtainable |
| Stellarwave Melody | 12 zodiac signs appear above and on the fishing bar. | Yes - read on screen | Yes | Player's recording / screenshots | obtainable |
| Dreambreaker | After 40% progress the screen borders dim and the minigame's input is inverted. | Inversion (from how the bar moves) | Yes | Built-in test game | obtainable |
| Dutchman's Rod | Spectral Barrage holds up to 5 fish as ammo. | Not needed (key press) | Yes | Built-in test game | obtainable |
| Pinion's Aria | Notes fall across the bar every 2 s, speeding up to every 1 s. | Falling objects (by movement) | Yes | Built-in test game | obtainable |
| Santa's Miracle Rod | Presents fall across the fishing bar. | Falling objects (by movement) | Yes | Built-in test game | limited (Fischmas) |
| Starshell Rod | Shells fall every 4 s (+6%); a wave on top of the bar pushes the fish. | Falling objects (by movement) | Yes | Built-in test game | limited (Fischfest) |
| Blade Of Glorp | Random laser strikes (2 warning pulses): control drops to a third for 0.3 s; fish still in the bar gives +10%. | Catch bar yes (green look); strike flash not read yet | Precision tracking, wide margin | Needs a recording | obtainable |
| Acidgrinder | Charge meter while reeling. | Catch bar yes; meter no | Normal tracking; bonus not automated | Not on this rod | unobtainable |
| Apollo's Sunshot | Charge Meter above the fishing bar. | Catch bar yes; meter no | Normal tracking; bonus not automated | Not on this rod | obtainable |
| Cupid's Bow | Charge Meter above the fishing bar. | Catch bar yes; meter no | Normal tracking; bonus not automated | Not on this rod | limited (Valentides) |
| Lemonade Serenade | Holding squeezes the control bar (up to 5 drops); releasing rains them down (+5% on the bar). | Catch bar yes; meter no | Normal tracking; bonus not automated | Not on this rod | limited |
| Maelstrom | Charge Meter. | Catch bar yes; meter no | Normal tracking; bonus not automated | Not on this rod | limited (Fischmas) |
| Sand Castle Caster | Charge Meter above the fishing bar. | Catch bar yes; meter no | Normal tracking; bonus not automated | Not on this rod | obtainable |
| Black Fairy | Soul Judgement every 5-8 s: boosts when the center is hit. | No | No - needs a clip | No | obtainable |
| Cerebra | Custom UI (not described). | No | No - needs a clip | No | limited |
| Jinglestar Rod | A bell with a ring counter while fishing. | No | No - needs a clip | No | limited (Fischmas) |
| Noiseform | 3 zones spawn; 3 warnings flash the correct one; Arrow Barrage. | No | No - needs a clip | No | limited |
| Remembrance | A white and a dark fish replace the normal one; butterflies slow the bar. | No | No - needs a clip | No | unobtainable |
| Silly Fun Happy Rod | One of 5 events: spinning bar, random movement, fake catch, jumpscare, boss fight. | No | No - needs a clip | No | unobtainable |
| Tranquility Rod | A 4-lane vertical rhythm game replaces the reeling minigame (chance). | No | No - needs a clip | No | obtainable |
| Ancient Idol Rod | Petrification Bar above the fishing bar. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | obtainable |
| Artisan Rod | Light slashes every 0.8 s. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | obtainable |
| Astraeus Serenade | The screen darkens; Flurry of Stars. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | unobtainable |
| Axe of Rhoads | Custom UI. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | unobtainable |
| Beach Ball Rod | A beach ball bounces on the control bar. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | limited (Fischfest) |
| Boglin Branch | Traps drop on the minigame and hold the fish. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | limited (FischFright) |
| Chasm-Stalker | Own perfect-streak counter; whirlpools in the minigame (50% every 4 s). | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | obtainable |
| Cheeto Rod | Custom UI. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | limited |
| Chrysalis | Custom UI; an eye may catch an extra fish. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | limited |
| Creamsicle Rod | Slippery bar; fish freeze after 8 s. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | limited (Fischfest) |
| Crowbar | Custom UI; a crowbar strikes the fish 3 times. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | obtainable |
| Cryolash | Icicles fall every 2-3 s (+15%). | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | obtainable |
| Cupid's Embrace | Progress speed falls over time. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | limited (Valentides) |
| Doomsekkar Rod | Plants pumpkin bombs on the bar; 6 detonations = slash +50%. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | limited (FischFright) |
| Eardrum | Custom UI; a ghost floats behind the player. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | limited |
| Eldritch Rod | Slashes, Eldritch Curse and Thorns. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | limited (FischFright) |
| Electric Guitar | 16.7% chance of +75% at the start. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | limited |
| Experimental Rod | Custom UI. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | limited |
| Floatie Rod | The minigame slowly floats up the screen. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | limited (Fischfest) |
| Jack-o-Blazer | Jack-o-Lanterns fall every 1 s (+8%). | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | limited (FischFright) |
| Luminescent Oath | Abilities only. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | obtainable |
| Masterline Rod | Custom UI with an Enhancement indicator; Heaven's Ray blasts the fish every 1-3 s. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | obtainable |
| Merlin's Staff | Control slowly drops, then +30% and reset. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | obtainable |
| Nates Blade | Custom UI; slashes stun the fish. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | obtainable |
| Noctone | Custom UI. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | limited |
| Omniscient Spinecaster | A crow pulls the fish into the bar. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | obtainable |
| Onirifalx | Custom UI; 30% chance of +30% at the start. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | obtainable |
| Polaris Serenade | Custom UI; a tree and a butterfly after catches. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | limited |
| Pool Noodle Rod | Custom UI. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | limited (Fischfest) |
| Rainbow Cluster Rod | Custom UI. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | obtainable |
| Requiem | Custom UI. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | obtainable |
| Rod Of The Forgotten Fang | A Meg jumps after 3 perfect catches. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | obtainable |
| Rose Rod | Fish freezes after 65% progress. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | limited (Valentides) |
| Ruinous Oath | Abilities only. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | obtainable |
| Sanguine Spire | Custom UI; slashes stun the fish. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | limited |
| Steady Rod | Shake buttons twice as big. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | obtainable |
| Sword of Light | Custom UI; stabs stun the fish. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | limited |
| Tiki Rod | A tiki mask in the middle: +15% when the fish passes under it. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | limited (Fischfest) |
| Toxic Spire Rod | Toxic strike paralyses the fish. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | obtainable |
| Verdant Oath | At the start the bar breaks in half, showing a green bar in the middle; the fish touching its brown sides costs 20%. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | obtainable |
| Vineweaver Rod | Fish freezes after 70% progress. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | obtainable |
| Webweaver Rod | Spiders and venom slow the fish. | Normal catch bar | Normal tracking (no input needed) | Not on this rod (no footage) | obtainable |

## What is still needed (send a short clip, 10-20 s, of the catch)

* **Tranquility Rod** - its 4-lane rhythm game replaces the catch bar. The wiki does not name the keys or show
  the layout. A clip with the keys you press would let it be automated.
* **Jinglestar Rod** - the bell's "correct timing".
* **Noiseform** - how a zone is "selected".
* **Black Fairy, Cerebra, Silly Fun Happy Rod, Remembrance** - their custom UI is not described.
* **Charge-meter rods** (Cupid's Bow, Maelstrom, Apollo's Sunshot, Sand Castle Caster) - where the meter is and
  whether it is charged with the same click as the bar.
* **Masterline Rod and its skins** - a clip of the catch with a skin (Grand Symphony, Malisteel, John Reaper, ...)
  to check the bar and fish are found on its custom UI.

## How to test a special rod (tutorial)

1. **Rod Library** -> search the rod -> open it. The panel says what the macro does for it and how well that is
   checked. Press **Save and use**.
2. **Settings -> Diagnostics -> Test a rod mechanic**: pick the mechanic (Lullaby gauge, Stellarwave signs, falling
   objects, MiguRod marks). The macro watches the game **without sending any input**. Play one catch by hand and
   look at the live view:
   * Lullaby: a green arc on each lit part and a pink line on the pendulum. The line under the picture reads
     "Gauge found: pendulum ..., lit parts ...".
   * Falling objects: a yellow circle on each object with the time until it lands.
   * Stellarwave: a yellow ring on the next sign.
   * MiguRod: orange ticks on the slash marks.
3. If it is drawn in the right places, turn the test off and press **Start**. The log shows
   "Special rod handler active: ..." when the rod's handler runs, and "Inverted controls detected - input flipped"
   when a rod inverts the input.
4. If it is not drawn, or drawn in the wrong place, press F11 (diagnostic snapshot) during the catch and send the
   snapshot folder, or a short clip.

### Configuring

* **Lullaby (any skin)**: *Click timing* moves clicks earlier (raise it if they land just after the lit part).
  Hollowed Harp has a slower pendulum in some modes. Pick it under Skin, so it keeps its own Click timing.
* **Dutchman's Rod**: set *Special Action key* to your keybind (Settings in Fisch). Nothing is pressed until it
  is set.
* **Falling objects**: nothing to set. The bar only leaves the fish's side when the fish stays inside.
* **Inverted controls**: on for every rod (*Notice inverted controls*, under Show all settings -> Fish tracking).
