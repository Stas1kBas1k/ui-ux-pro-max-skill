"""Fisch game catalogue used by the selections in the UI.

Names come from the official Fisch wiki and community guides (October 2026).
Everything here is plain data so it can be updated without touching logic.
"""
from __future__ import annotations

# --------------------------------------------------------------------------- hunts (name, dot colour)
_R, _P, _LB, _Y, _PU, _B = "#EF4444", "#F472B6", "#7DD3FC", "#FCD34D", "#A78BFA", "#60A5FA"
_G, _DG, _LI, _BR, _O, _C, _W = "#86EFAC", "#5B8C3A", "#BEF264", "#B07850", "#FDBA74", "#67E8F9", "#D4D4D8"

HUNTS: list[tuple[str, str]] = [
    ("Sovereign Surge", _B), ("Sovereign Storm", "#6366F1"), ("Sovereign Reckoning", "#A855F7"), ("Wisp Haunt", _G),
    ("Soul Scourge", _BR), ("Styx Angler", "#5B9BF0"), ("Storm Flood", _B), ("Tidecrasher Archon", "#7DB8F0"),
    ("Megalodon", _R), ("Ancient Megalodon", _R), ("Phantom Megalodon", "#3B5BDB"), ("Solar Chorus", _Y),
    ("Helios Sunray", "#E0C050"), ("Olympian Devil", "#E07A9A"), ("Kerauno Wyrm", "#C8B840"), ("War Surge", _R),
    ("Legionnaire Lamprey", "#C06060"), ("Kraken", _P), ("Ancient Kraken", _P), ("Leviathan", _Y),
    ("Profane Leviathan", _Y), ("Skeletal Leviathan", _BR), ("Beluga", _R), ("Narwhal", _R),
    ("Magician Narwhal", _R), ("Mosslurker", _R), ("Dreadfin", _W), ("Megamouth Shark", _B),
    ("Orca Migration", _P), ("Whale Migration", _P), ("Humpback Whale", _LB), ("Great White Shark", _P),
    ("Great Hammerhead Shark", _P), ("Whale Shark", _P), ("Plesiosaur", _LB), ("Pliosaur", _Y),
    ("Ancestral Pliosaur", _Y), ("Reef Titan", _C), ("Colossus Reef Titan", _C), ("Omnithal", _PU),
    ("Awakened Omnithal", _PU), ("Goldwraith", _Y), ("Ancient Goldwraith", _Y), ("Colossal Ancient Dragon", _R),
    ("Colossal Blue Dragon", _LB), ("Colossal Ethereal Dragon", "#F5B8F0"), ("Scylla", _G), ("Mossjaw", _DG),
    ("Elder Mossjaw", _DG), ("Flower Guardian", _LI), ("Rotbloom", _BR), ("Toxic Guardian", _LI), ("Ashclaw", _R),
    ("Frostwyrm", _LB), ("Wyvern", "#6FBF73"), ("Baby Bloop Fish", _O), ("Bloop Fish", _R), ("Sunken Chests", _O),
    ("Earthquake", "#F98060"), ("King Crabstle", "#A1A1AA"),
]
HUNT_COLORS = dict(HUNTS)

# --------------------------------------------------------------------------- weather / totems
# (weather shown in game, totem that sets it, dot colour, words that identify it in on-screen text)
WEATHERS: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("Clear", "Clearcast Totem", "#FDE68A", ("clear",)),
    ("Rain", "Tempest Totem", "#60A5FA", ("rain", "rainy")),
    ("Windy", "Windset Totem", "#A7F3D0", ("wind", "windy")),
    ("Foggy", "Smokescreen Totem", "#D4D4D8", ("fog", "foggy")),
    ("Tropical Squall", "Tropical Squall Totem", "#34D399", ("tropical squall",)),
    ("Raging Squall", "Raging Squall Totem", "#818CF8", ("raging squall",)),
    ("Aurora Borealis", "Aurora Totem", "#5EEAD4", ("aurora",)),
    ("Eclipse", "Eclipse Totem", "#F97316", ("eclipse",)),
    ("Blue Moon", "Blue Moon Totem", "#3B82F6", ("blue moon",)),
    ("Starfall", "Starfall Totem", "#C4B5FD", ("starfall",)),
    ("Rainbow", "Rainbow Totem", "#F472B6", ("rainbow",)),
]
WEATHER_TOTEM = {w: t for w, t, _, _ in WEATHERS}

# (surge, totem, dot colour, words that show it is active)
SURGES: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("Shiny", "Shiny Totem", "#FDE047", ("shiny surge",)),
    ("Sparkling", "Sparkling Totem", "#F0ABFC", ("luminous", "sparkling")),
    ("Mutation", "Mutation Totem", "#4ADE80", ("mutation surge",)),
]
SURGE_TOTEM = {s: t for s, t, _, _ in SURGES}
TIME_TOTEM = "Sundial Totem"
TIMES = ["Auto", "Day", "Night"]

# --------------------------------------------------------------------------- appraising
TRAITS: list[str] = [
    "Abyssal", "Albino", "Amber", "Big", "Darkened", "Electric", "Festive", "Fossilized", "Frozen", "Giant",
    "Glossy", "Greedy", "Hexed", "Jolly", "Lunar", "Midas", "Mosaic", "Mythical", "Negative", "Scorched", "Shiny",
    "Silver", "Sparkling", "Translucent",
]

# --------------------------------------------------------------------------- Lullaby rod
# (mode, colour, relative pendulum speed, what it gives)
LULLABY_MODES: list[tuple[str, str, float, str]] = [
    ("Resistant Composition", "#60A5FA", 0.5, "+20% Resilience, +0.05 Control"),
    ("Quickening Symphony", "#FBBF24", 1.0, "+20% Lure Speed, +20% Progress Speed"),
    ("Strengthening Melody", "#F87171", 0.5, "+75,000 Max Kg, +50% XP"),
    ("Fortuitous Harmony", "#4ADE80", 1.0, "+40% Luck, +10% Fish Size"),
    ("Prismatic Sinfonia", "#E879F9", 1.0, "Prismatic, Mythical, Shiny and Sparkling chances"),
    ("Serene Hymn", "#5EEAD4", 1.0, "+10% Serene chance, +45% Resilience"),
]
LULLABY_COLORS = {m: c for m, c, _, _ in LULLABY_MODES}

# --------------------------------------------------------------------------- rods with special handling
KNOWN_RODS = ["Lullaby", "Stellarwave Melody", "Halibut Harpoon", "Pinion's Aria", "Migurod", "Sovereign"]
RELICS = ["Enchant Relic", "Exalted Relic"]
