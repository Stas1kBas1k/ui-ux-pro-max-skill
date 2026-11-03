"""What each special rod does while fishing, and what the macro does about it.

Researched from each rod's page on the Fisch wiki (fischipedia.org, 1 November 2026); every mechanic below is
from the page text, nothing is guessed. When the page does not say what to press, the rod is marked
``needs-footage`` and only normal tracking is used. docs/SPECIAL_RODS.md has the table and how to test each one.

Support levels:
  verified      - handler checked on the player's own recording / screenshots
  handled       - handler built from the wiki description and checked in the built-in test game
  normal        - the rod's extra effects need no input (passive, or a custom look): normal tracking
  bonus-manual  - catches with normal tracking; an optional bonus (charge meter...) is not automated yet
  needs-footage - the wiki does not say what to press or how it looks: send a clip to get it automated
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RodMechanic:
    name: str
    mechanic: str                 # what happens during the catch (from the wiki)
    player: str                   # what the player has to do (from the wiki), or "nothing"
    support: str                  # see the module docstring
    macro: str                    # what the macro does
    availability: str = ""        # obtainable / limited (event) / unobtainable
    kind: str = "none"            # MinigameConfig.kind used for it
    skins: tuple[str, ...] = ()   # skins named on the wiki (for the skin picker)
    notes: tuple[str, ...] = field(default_factory=tuple)


_N = "normal tracking - nothing to press"
CATALOG: dict[str, RodMechanic] = {m.name: m for m in (
    # ---------------------------------------------------------------- handlers
    RodMechanic("Lullaby", "A pendulum swings across a half-moon metronome with lit sections; Q cycles modes.",
                "Click while the pendulum is over a lit section (a miss costs 5% progress).", "verified",
                "Clicks once on every pass over every lit part, aimed at its middle.", "limited", "lullaby",
                ("Seastrum", "Porcelain Chord", "Serenity", "Hollowed Harp", "Nameless Illuminator"),
                ("Hollowed Harp: slower pendulum in some modes (e.g. Prismatic Sinfonia), same buffs (wiki).",)),
    RodMechanic("Stellarwave Melody", "12 zodiac signs appear above and on the fishing bar.",
                "Select the correct sign (+3% each).", "verified", "Taps the signs in order and checks each star.",
                "obtainable", "stellarwave",
                ("Stellar Vengeance", "Kitty Keys", "Nullwave", "Ominous Ouija", "Toothly Interstellar")),
    RodMechanic("MiguRod", "3 slashes appear on the minigame (every 3 catches / 41% per fish movement); the bar "
                "is cut where a hit lands.", "Dodge the slashes (+4% per dodge).", "verified",
                "Keeps the bar away from the slash marks while following the fish.", "unobtainable", "migu",
                ("Melodii", "Golden MiguRod", "Boukar", "Makhroing", "Chroma MiguRod", "Baguette",
                 "Mankind's Demise", "Time Reaper")),
    RodMechanic("Halibut Harpoon", "15-35 harpoons home to random spots marked '!'.",
                "Nothing (Q turns it into a Harpoon Gun).", "verified", "Ignores the '!' marks so they are never "
                "mistaken for the fish.", "obtainable", "halibut",
                ("Pufferfish Harpoon", "Party Puffer", "Salty Sardines", "Crimson Excision", "Flak Krakenling")),
    RodMechanic("Pinion's Aria", "Notes fall across the bar every 2 s, speeding up to every 1 s.",
                "Catch the notes with the bar (a missed note: -10% progress, -15% control).", "handled",
                "Moves the bar under each note when the fish stays inside.", "obtainable", "falling",
                ("Golden Pinion's Aria", "Frigid Beauty", "Galactic Virge", "Vespera's Dream", "Meanie Dog",
                 "Sterling Parasol", "Triple Fishstaff", "Weeping Mumster")),
    RodMechanic("Santa's Miracle Rod", "Presents fall across the fishing bar.", "Catch them with the bar (+10%).",
                "handled", "Moves the bar under each present when the fish stays inside.", "limited (Fischmas)",
                "falling", ("Krampus's Miracle Skin",)),
    RodMechanic("Starshell Rod", "Shells fall every 4 s (+6%); a wave on top of the bar pushes the fish.",
                "Catch the shells with the bar.", "handled", "Moves the bar under each shell when the fish stays "
                "inside; the wave is followed by normal tracking.", "limited (Fischfest)", "falling",
                ("Snowshell Rod",)),
    RodMechanic("Dutchman's Rod", "Spectral Barrage holds up to 5 fish as ammo.", "Press the Special Action "
                "keybind while fishing to launch one (keeps the fish off the edges, + progress).", "handled",
                "Presses your Special Action key during the catch (set the key first).", "obtainable",
                "special_key"),
    RodMechanic("Dreambreaker", "After 40% progress the screen borders dim and the minigame's input is "
                "inverted.", "Play with hold and release swapped.", "handled", "Notices the inversion from how "
                "the bar moves and flips the input (any rod).", "obtainable", "none",
                ("Garnetbreaker", "Umbral Vengeance", "Golden Dreambreaker", "Aquabriar", "Dreamshredder")),
    RodMechanic("Blade Of Glorp", "Every 2 s a 20% chance of a laser strike, announced by 2 warning pulses (4 with "
                "the Mastery passive): for 0.3 s control drops to a third and progress moves only 0.25% per frame; "
                "if the fish is still inside the bar after that, +10% progress. Green, non-standard look.",
                "Keep the fish inside the bar through each strike.", "needs-footage",
                "Precision tracking with a wide safety margin, so the fish sits mid-bar when control drops; the "
                "strike's flash is not read yet (send a recording).", "obtainable", "none"),
    RodMechanic("Verdant Oath", "At the start the bar breaks in half, showing a green bar in the middle; the fish "
                "touching its brown sides costs 20%.", "Keep the fish in the green middle.", "normal",
                "Normal tracking: the damped centring keeps the fish near the middle of the bar (the split "
                "bar itself is not tested).", "obtainable", "none",
                ("Fruitshido", "Chromancer")),
    RodMechanic("Requiem", "Custom UI.", "Every start and end of an input while the fish is on the bar gives "
                "+5% progress.", "normal", "Normal tracking already clicks many times a second while the fish is "
                "on the bar.",
                "obtainable", "none"),
    # ---------------------------------------------------------------- bonus not automated (still catches)
    RodMechanic("Cupid's Bow", "Charge Meter above the fishing bar.", "Hold to charge (random rate); release "
                "above 80% with the fish in the bar for +7%.", "bonus-manual", _N + "; the release bonus needs "
                "the meter on video to automate.", "limited (Valentides)"),
    RodMechanic("Maelstrom", "Charge Meter.", "Hold to charge; release above 80% with the fish in the bar for "
                "+15% and a chance to freeze the fish.", "bonus-manual", _N + "; the bonus needs footage.",
                "limited (Fischmas)"),
    RodMechanic("Apollo's Sunshot", "Charge Meter above the fishing bar.", "Hold to 100%, then press while the "
                "bar is over the fish: +9%, may burn the fish.", "bonus-manual", _N + "; the bonus needs footage.",
                "obtainable", skins=("Caelum Lullaby", "Pegasus")),
    RodMechanic("Sand Castle Caster", "Charge Meter above the fishing bar.", "Hold to charge; full = fish frozen "
                "(Sand Castled).", "bonus-manual", _N + "; the freeze needs footage.", "obtainable"),
    RodMechanic("Acidgrinder", "Charge meter while reeling.", "Holding raises charge (faster progress), "
                "releasing lowers it.", "bonus-manual", _N + ".", "unobtainable"),
    RodMechanic("Lemonade Serenade", "Holding squeezes the control bar (up to 5 drops); releasing rains them "
                "down (+5% on the bar).", "Hold, then release.", "bonus-manual", _N + ".", "limited"),
    # ---------------------------------------------------------------- needs footage
    RodMechanic("Tranquility Rod", "A 4-lane vertical rhythm game replaces the reeling minigame (chance).",
                "Time key presses as notes fall (keys not named on the wiki).", "needs-footage",
                "Not automated: the keys and layout are needed (a clip of the rhythm game).", "obtainable",
                skins=("Fishcake Snack", "Whalesong Orcarina")),
    RodMechanic("Jinglestar Rod", "A bell with a ring counter while fishing.", "Ring it 10 times in a row with "
                "the correct timing (+20%).", "needs-footage", "Normal tracking; the bell timing needs a clip.",
                "limited (Fischmas)"),
    RodMechanic("Noiseform", "3 zones spawn; 3 warnings flash the correct one; Arrow Barrage.", "Select the "
                "correct zone (wrong 4 times ends the minigame) - how is not stated.", "needs-footage",
                "Normal tracking; zone selection needs a clip.", "limited"),
    RodMechanic("Black Fairy", "Soul Judgement every 5-8 s: boosts when the center is hit.", "Not stated.",
                "needs-footage", "Normal tracking.", "obtainable"),
    RodMechanic("Silly Fun Happy Rod", "One of 5 events: spinning bar, random movement, fake catch, jumpscare, "
                "boss fight.", "Not stated.", "needs-footage", "Normal tracking (inverted / moving bars are "
                "followed by the tracker).", "unobtainable"),
    RodMechanic("Cerebra", "Custom UI (not described).", "Not stated.", "needs-footage", "Normal tracking.",
                "limited"),
    RodMechanic("Remembrance", "A white and a dark fish replace the normal one; butterflies slow the bar.",
                "Not stated.", "needs-footage", "Normal tracking (follows one fish).", "unobtainable"),
    RodMechanic("Chasm-Stalker", "Own perfect-streak counter; whirlpools in the minigame (50% every 4 s).",
                "Not stated.", "normal", _N + ".", "obtainable"),
    # ---------------------------------------------------------------- passive / custom look: normal tracking
    *(RodMechanic(n, m, "Nothing (passive).", "normal", _N + ".", a) for n, m, a in (
        ("Masterline Rod", "Custom UI with an Enhancement indicator; Heaven's Ray blasts the fish every 1-3 s.",
         "obtainable"),
        ("Doomsekkar Rod", "Plants pumpkin bombs on the bar; 6 detonations = slash +50%.", "limited (FischFright)"),
        ("Eldritch Rod", "Slashes, Eldritch Curse and Thorns.", "limited (FischFright)"),
        ("Boglin Branch", "Traps drop on the minigame and hold the fish.", "limited (FischFright)"),
        ("Webweaver Rod", "Spiders and venom slow the fish.", "obtainable"),
        ("Omniscient Spinecaster", "A crow pulls the fish into the bar.", "obtainable"),
        ("Jack-o-Blazer", "Jack-o-Lanterns fall every 1 s (+8%).", "limited (FischFright)"),
        ("Beach Ball Rod", "A beach ball bounces on the control bar.", "limited (Fischfest)"),
        ("Tiki Rod", "A tiki mask in the middle: +15% when the fish passes under it.", "limited (Fischfest)"),
        ("Creamsicle Rod", "Slippery bar; fish freeze after 8 s.", "limited (Fischfest)"),
        ("Floatie Rod", "The minigame slowly floats up the screen.", "limited (Fischfest)"),
        ("Cupid's Embrace", "Progress speed falls over time.", "limited (Valentides)"),
        ("Astraeus Serenade", "The screen darkens; Flurry of Stars.", "unobtainable"),
        ("Ancient Idol Rod", "Petrification Bar above the fishing bar.", "obtainable"),
        ("Rod Of The Forgotten Fang", "A Meg jumps after 3 perfect catches.", "obtainable"),
        ("Steady Rod", "Shake buttons twice as big.", "obtainable"),
        ("Rose Rod", "Fish freezes after 65% progress.", "limited (Valentides)"),
        ("Vineweaver Rod", "Fish freezes after 70% progress.", "obtainable"),
        ("Toxic Spire Rod", "Toxic strike paralyses the fish.", "obtainable"),
        ("Cryolash", "Icicles fall every 2-3 s (+15%).", "obtainable"),
        ("Crowbar", "Custom UI; a crowbar strikes the fish 3 times.", "obtainable"),
        ("Nates Blade", "Custom UI; slashes stun the fish.", "obtainable"),
        ("Sanguine Spire", "Custom UI; slashes stun the fish.", "limited"),
        ("Sword of Light", "Custom UI; stabs stun the fish.", "limited"),
        ("Onirifalx", "Custom UI; 30% chance of +30% at the start.", "obtainable"),
        ("Merlin's Staff", "Control slowly drops, then +30% and reset.", "obtainable"),
        ("Artisan Rod", "Light slashes every 0.8 s.", "obtainable"),
        ("Cheeto Rod", "Custom UI.", "limited"),
        ("Chrysalis", "Custom UI; an eye may catch an extra fish.", "limited"),
        ("Experimental Rod", "Custom UI.", "limited"),
        ("Noctone", "Custom UI.", "limited"),
        ("Rainbow Cluster Rod", "Custom UI.", "obtainable"),
        ("Axe of Rhoads", "Custom UI.", "unobtainable"),
        ("Pool Noodle Rod", "Custom UI.", "limited (Fischfest)"),
        ("Polaris Serenade", "Custom UI; a tree and a butterfly after catches.", "limited"),
        ("Eardrum", "Custom UI; a ghost floats behind the player.", "limited"),
        ("Electric Guitar", "16.7% chance of +75% at the start.", "limited"),
        ("Luminescent Oath", "Abilities only.", "obtainable"),
        ("Ruinous Oath", "Abilities only.", "obtainable"),
    )),
)}


def mechanic(rod: str) -> RodMechanic | None:
    return CATALOG.get(rod)


def skins(rod: str) -> tuple[str, ...]:
    m = CATALOG.get(rod)
    return m.skins if m else ()
