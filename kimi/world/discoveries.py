"""Local tables of things Kimi can find and notice. No API calls needed."""

from __future__ import annotations

import random
from dataclasses import dataclass

from ..memory.text import keywords


@dataclass(frozen=True)
class Find:
    item: str
    description: str
    rarity: str  # common | uncommon | rare
    tags: tuple[str, ...] = ()


DISCOVERIES: dict[str, tuple[Find, ...]] = {
    "shrub": (
        Find("snail shell", "an empty snail shell that spirals like a tiny staircase", "common", ("snail", "spiral", "shell")),
        Find("blue feather", "a small blue feather, softer than anything", "uncommon", ("feather", "bird", "blue")),
        Find("green beetle", "a beetle with a shell like polished green glass", "common", ("beetle", "insect", "green")),
        Find("dewy cobweb", "a cobweb strung with dew drops like a necklace", "common", ("web", "spider", "dew")),
        Find("hollow", "a hidden hollow deep in the Shrub where the light turns green", "uncommon", ("hollow", "secret", "light")),
        Find("moss cushion", "a cushion of moss so thick Kimi's feet sink into it", "common", ("moss", "plant", "soft")),
        Find("tiny frog", "a frog the size of a fingernail, blinking slowly", "uncommon", ("frog", "pond", "animal")),
        Find("old key", "a little brass key, green with age, half buried in leaves", "rare", ("key", "mystery", "brass")),
        Find("ring of mushrooms", "a perfect ring of tiny white mushrooms", "rare", ("mushroom", "fungi", "ring")),
        Find("striped pebble", "a pebble with a single white stripe around it", "common", ("pebble", "stone", "stripe")),
    ),
    "shrine": (
        Find("folded paper crane", "a folded paper crane someone left on the steps", "uncommon", ("paper", "crane", "gift")),
        Find("smooth river stone", "a smooth grey stone left as an offering", "common", ("stone", "gift")),
        Find("pressed flower", "a pressed violet tucked behind the notice board", "uncommon", ("flower", "gift", "violet")),
        Find("chime note", "a wind chime that rings a note Kimi has never heard before", "common", ("music", "chime", "sound")),
        Find("lichen pattern", "lichen on the shrine stones shaped like a map", "common", ("lichen", "map", "stone")),
        Find("marble", "a glass marble with a swirl of gold inside", "rare", ("marble", "glass", "gold", "gift")),
        Find("candle stub", "a little candle stub that still smells of honey", "common", ("candle", "honey")),
    ),
    "square": (
        Find("lost button", "a shiny red button near the fountain", "common", ("button", "red")),
        Find("coin-shaped leaf", "a round yellow leaf that looks exactly like a coin", "common", ("leaf", "autumn")),
        Find("chalk drawing", "a faded chalk drawing of a boat on the cobbles", "uncommon", ("chalk", "drawing", "boat")),
        Find("fountain echo", "a spot where the fountain's splash echoes strangely", "common", ("water", "sound", "echo")),
        Find("bottle cap", "a bottle cap with a star pressed into it", "uncommon", ("star", "metal")),
    ),
    "nest": (
        Find("thistledown", "a puff of thistledown drifting in the doorway", "common", ("soft", "seed")),
        Find("acorn cap", "a perfect acorn cap, just right as a tiny cup", "common", ("acorn", "cup", "oak")),
        Find("root carving", "faint old marks carved into the oak's roots", "rare", ("carving", "mystery", "oak")),
    ),
}

_DEFAULT_FINDS = DISCOVERIES["square"]

OBSERVATIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "cafe": {
        "day": (
            "Marigold the hedgehog hums while she wipes the counter.",
            "Two pigeons at the window table argue politely about breadcrumbs.",
            "Steam curls off a teapot like a little ghost.",
            "A mouse in a knitted scarf reads a newspaper twice its size.",
            "Marigold slides a fresh tray of seed cakes into the window.",
        ),
        "night": ("The cafe is closed; a lamp glows over the empty tables.",),
    },
    "library": {
        "day": (
            "Professor Quill peers over half-moon spectacles at a map of the stars.",
            "Dust drifts slowly through a beam of light between the shelves.",
            "A book on the returns cart is called 'A Field Guide to Puddles'.",
            "The library clock ticks loudly in the quiet.",
        ),
        "night": ("Professor Quill reads by candlelight, as always.",),
    },
    "print_shop": {
        "day": (
            "Ink, the print shop's black cat, naps on a stack of paper.",
            "The iron press creaks as it cools.",
            "Kimi's earlier drawings flutter on the display wall.",
            "Someone has left a tray of wooden letters spelling 'HELLO'.",
        ),
        "night": ("Moonlight makes the wooden letters cast long shadows.",),
    },
    "shrub": {
        "day": (
            "A bumblebee bumbles from flower to flower.",
            "Leaves shiver and something small scurries away.",
            "Sunlight dapples the ground in moving coins of light.",
            "An ant carries a crumb three times its size.",
        ),
        "night": ("Glow-worms light up deep inside the Shrub.", "An owl calls somewhere far away."),
    },
    "shrine": {
        "day": (
            "The wind chimes stir and ring softly.",
            "A moth rests on the notice board among the visitors' notes.",
            "Moss on the shrine stones is a brighter green after the rain.",
        ),
        "night": ("The shrine is silver in the moonlight.", "The chimes ring once in the dark."),
    },
    "square": {
        "day": (
            "The fountain chatters to itself.",
            "A squirrel delivers acorns to someone's doorstep.",
            "The town clock is five minutes slow, as usual.",
        ),
        "night": ("The square is empty except for the fountain's whisper.",),
    },
    "nest": {
        "day": ("Light filters through the oak leaves overhead.", "The moss lining of the nest feels warm."),
        "night": ("The oak creaks gently, like it's settling down too.",),
    },
}

COMPANY = {"cafe", "library", "print_shop"}


def roll_discovery(location: str, rng: random.Random, curiosity: float, focus: str | None = None) -> Find | None:
    table = DISCOVERIES.get(location, _DEFAULT_FINDS)
    chance = 0.45 + 0.25 * (curiosity / 100.0)
    if rng.random() > chance:
        return None
    weights = []
    focus_words = set(keywords(focus or ""))
    for f in table:
        w = {"common": 6.0, "uncommon": 2.5, "rare": 0.7}[f.rarity]
        if focus_words and focus_words & set(f.tags):
            w *= 3.0
        weights.append(w)
    return rng.choices(table, weights=weights, k=1)[0]


def observe(location: str, is_night: bool, rng: random.Random) -> str:
    table = OBSERVATIONS.get(location, OBSERVATIONS["square"])
    lines = table["night"] if is_night and "night" in table else table["day"]
    return rng.choice(lines)


def has_company(location: str | None, is_night: bool) -> bool:
    return location in COMPANY and not is_night
