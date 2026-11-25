"""Variety from code, not temperature.

Haiku 5.5 rejects `temperature`, and asking a model to "be creative" tends to give the same
favourite images every time. Instead, code picks a couple of random "sparks" and offers them to
the planner as optional ingredients. The planner may ignore any that don't fit the request.
"""

import random

SPARKS = [
    "a kettle that hums when someone is happy",
    "a staircase with one step that creaks a different note",
    "a lighthouse keeper who knits",
    "the smell of warm bread drifting from somewhere",
    "a map drawn on the back of a cereal box",
    "rain tapping a rhythm on a tin roof",
    "a snail who keeps very careful lists",
    "a moon that looks like a fingernail clipping",
    "a scarf that is far too long",
    "fireflies that blink in patterns",
    "a garden where the vegetables are slightly too big",
    "a tiny door at the bottom of a tree",
    "a sleepy hedgehog who hiccups",
    "a paper boat with a name painted on it",
    "socks that never match, on purpose",
    "a library that is open only at dusk",
    "a grandmother's button jar",
    "a cloud that can't decide what shape to be",
    "a train that stops at very small stations",
    "a pocket full of interesting pebbles",
    "snow that squeaks when you step on it",
    "a bakery run by a family of otters",
    "a compass that points toward home",
    "an old armchair everyone wants to sit in",
]


def pick_sparks(rng: random.Random, k: int = 3) -> list[str]:
    return rng.sample(SPARKS, k)
