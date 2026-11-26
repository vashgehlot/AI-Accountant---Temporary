"""Where a made-up business is: its address, and the town its card payments print. Documents and statements both take
them from here, so a receipt and the card line paying it name the same town."""
from __future__ import annotations

import random

STREETS = ("High Street", "Station Road", "Mill Lane", "Church Street", "Victoria Road", "Park Road", "Queen Street",
           "King Street", "Quay Street", "Market Place")
TOWNS = {None: (("Bristol", "BS1"), ("Bath", "BA1"), ("Gloucester", "GL1"), ("Cardiff", "CF10"), ("Swindon", "SN1"),
                ("Reading", "RG1"), ("Exeter", "EX1"), ("Cheltenham", "GL50")),
         "Ireland": (("Dublin 2", ""), ("Dublin 4", ""), ("Cork", "")),
         "United States": (("Austin, TX", "78701"), ("Denver, CO", "80202"))}
LETTERS = "ABDEFGHJLNPQRSTUWXY"


def _place(name: str, country: str | None) -> tuple[random.Random, str, str]:
    rng = random.Random(f"address:{name}")
    town, area = rng.choice(TOWNS.get(country, TOWNS[None]))
    return rng, town, area


def town_of(name: str, country: str | None = None) -> str:
    """The town in a made-up business's address: the same every build."""
    return _place(name, country)[1]


def address_of(name: str, country: str | None = None) -> str:
    """A made-up business's address: the same every build."""
    rng, town, area = _place(name, country)
    if country:
        return f"{rng.randint(1, 120)} {rng.choice(STREETS)}, {town}{' ' + area if area else ''}, {country}"
    return (f"{rng.randint(1, 120)} {rng.choice(STREETS)}, {town} {area} "
            f"{rng.randint(1, 9)}{rng.choice(LETTERS)}{rng.choice(LETTERS)}")


def card_town(name: str, country: str | None = None) -> str:
    """The town a card terminal prints after the merchant's name: its address's town, in capitals, without a district
    or state ("DUBLIN" for Dublin 2, "AUSTIN" for Austin, TX)."""
    return town_of(name, country).split(",")[0].split()[0].upper()
