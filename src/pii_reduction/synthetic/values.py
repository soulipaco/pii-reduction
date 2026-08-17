"""Synthetic values used to build benchmark corpora.

Everything here is invented and safe to commit (``AGENTS.md`` rule 2). Emails use
RFC 2606 reserved domains (ADR-0003); phone numbers come from ranges published as
permanently unassigned (ADR-0014).

Two requirements pull against each other here and both have to hold. A generated
number must be **valid** — ``phonenumbers`` has to recognize it, or the corpus would
only ever measure the recognizer's tolerance for malformed input. It must also be
**unmistakably fake**, because this corpus is committed to a public repository and
the README prints it. Numbers that satisfy only the first are dialable strangers'
phones; numbers that satisfy only the second measure nothing. ADR-0014 records which
range satisfies both per country, and where the guarantee is weaker.

**Deviation from the plan:** Increment A6 was specified as "template + Faker
generation". Faker is not used here. Curated pools are deterministic without seeding a
third-party RNG, keep the generator free of a dev-only dependency, and — the deciding
reason — let Greek names actually be Greek, with a matching Latin transliteration for
the email local part, which locale-based generation does not guarantee. Faker becomes
useful at Increment D, where volume matters more than control; the ``ValueProvider``
protocol below is the seam it plugs into.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol

import phonenumbers

from pii_reduction.synthetic.errors import CorpusError

__all__ = [
    "LANGUAGES",
    "PersonPool",
    "PoolValueProvider",
    "SyntheticValue",
    "ValueProvider",
]

LANGUAGES = ("en", "de", "el")

EMAIL_DOMAINS = ("example.com", "example.org", "example.net")


@dataclass(frozen=True)
class SyntheticValue:
    """One generated value and the id the manifest records it under."""

    value_id: str
    text: str


@dataclass(frozen=True)
class PersonPool:
    """A display name and the ASCII slug used to build its email address."""

    name: str
    slug: str


PERSONS: dict[str, tuple[PersonPool, ...]] = {
    "en": (
        PersonPool("Maria Rossi", "maria.rossi"),
        PersonPool("James Whitfield", "james.whitfield"),
        PersonPool("Aisha Bello", "aisha.bello"),
        PersonPool("Peter Novak", "peter.novak"),
        PersonPool("Grace Okafor", "grace.okafor"),
        PersonPool("Daniel Ferreira", "daniel.ferreira"),
        PersonPool("Helen Marsh", "helen.marsh"),
        PersonPool("Omar Haddad", "omar.haddad"),
    ),
    "de": (
        PersonPool("Jan Becker", "jan.becker"),
        PersonPool("Lukas Schneider", "lukas.schneider"),
        PersonPool("Anja Hoffmann", "anja.hoffmann"),
        PersonPool("Jürgen Müller", "juergen.mueller"),
        PersonPool("Katrin Wagner", "katrin.wagner"),
        PersonPool("Stefan Bauer", "stefan.bauer"),
        PersonPool("Miriam Köhler", "miriam.koehler"),
        PersonPool("Tobias Lang", "tobias.lang"),
    ),
    "el": (
        PersonPool("Ελένη Παππά", "eleni.pappa"),
        PersonPool("Γιώργος Δημητρίου", "giorgos.dimitriou"),
        PersonPool("Μαρία Παπαδοπούλου", "maria.papadopoulou"),
        PersonPool("Νίκος Αντωνίου", "nikos.antoniou"),
        PersonPool("Σοφία Καραγιάννη", "sofia.karagianni"),
        PersonPool("Δημήτρης Λέκκας", "dimitris.lekkas"),
        PersonPool("Άννα Βασιλείου", "anna.vasileiou"),
        PersonPool("Κώστας Ιωάννου", "kostas.ioannou"),
    ),
}

#: Number bodies per language, in international form, drawn from ranges published as
#: permanently unassigned. Every value is checked against ``phonenumbers`` at build
#: time (see :func:`_validate_phone_pools`) — see ADR-0014 for why both properties are
#: required and where each range comes from.
#:
#: - ``en``: NANP ``555-01xx``, reserved for fictional use.
#: - ``de``: Bundesnetzagentur "Drama Numbers", Mitteilung 148/2021 (Amtsblatt 07/21,
#:   14.04.2021) — Berlin block ``030 23125 000`` to ``030 23125 999``, permanently
#:   assigned to no subscriber and free to use in media without permission.
#: - ``el``: Greece publishes no equivalent reserved range; see ADR-0014 for the
#:   compromise and its residual risk.
PHONES: dict[str, tuple[str, ...]] = {
    "en": tuple(f"+1 202 555 01{index:02d}" for index in range(20, 44)),
    "de": tuple(f"+49 30 23125 {index:03d}" for index in range(20, 44)),
    "el": tuple(f"+30 210 000 00{index:02d}" for index in range(20, 44)),
}

#: Short forms a person's name takes in noisy (tier 2) text.
SHORT_NAME_STYLES = ("{first} {initial}.", "{first}", "{first} {last}")


class ValueProvider(Protocol):
    """Where a template gets its values. Increment D can supply a Faker-backed one."""

    def person(self, language: str) -> SyntheticValue: ...

    def person_short(self, language: str) -> SyntheticValue: ...

    def email(self, language: str) -> SyntheticValue: ...

    def phone(self, language: str, *, style: str = "plain") -> SyntheticValue: ...

    def ticket(self) -> SyntheticValue: ...

    def kb_article(self) -> SyntheticValue: ...

    def machine(self) -> SyntheticValue: ...

    def version(self) -> SyntheticValue: ...

    def order(self) -> SyntheticValue: ...


class PoolValueProvider:
    """Deterministic values from curated pools.

    Seeded by construction: two providers built with the same seed emit the same
    sequence, which is what makes a regenerated corpus byte-identical (ADR-0011).
    """

    def __init__(self, seed: int = 42) -> None:
        self._random = random.Random(seed)
        self._counters: dict[str, int] = {}
        _validate_phone_pools()

    def _next(self, kind: str) -> int:
        value = self._counters.get(kind, 0)
        self._counters[kind] = value + 1
        return value

    def _pick_person(self, language: str) -> tuple[PersonPool, int]:
        pool = PERSONS[language]
        index = self._random.randrange(len(pool))
        return pool[index], index

    def person(self, language: str) -> SyntheticValue:
        person, index = self._pick_person(language)
        return SyntheticValue(f"{language}_person_{index:02d}", person.name)

    def person_short(self, language: str) -> SyntheticValue:
        person, index = self._pick_person(language)
        first, _, last = person.name.partition(" ")
        style = SHORT_NAME_STYLES[self._random.randrange(len(SHORT_NAME_STYLES))]
        text = style.format(first=first, last=last, initial=last[:1])
        return SyntheticValue(f"{language}_person_short_{index:02d}", text)

    def email(self, language: str) -> SyntheticValue:
        person, index = self._pick_person(language)
        domain = EMAIL_DOMAINS[self._random.randrange(len(EMAIL_DOMAINS))]
        return SyntheticValue(f"{language}_email_{index:02d}", f"{person.slug}@{domain}")

    def phone(self, language: str, *, style: str = "plain") -> SyntheticValue:
        pool = PHONES[language]
        index = self._random.randrange(len(pool))
        number = pool[index]
        if style == "dashed":
            number = number.replace(" ", "-")
        elif style == "compact":
            number = number.replace(" ", "", 2)
        elif style != "plain":
            raise CorpusError(f"unknown phone style {style!r} (known: plain, dashed, compact)")
        return SyntheticValue(f"{language}_phone_{index:02d}_{style}", number)

    def ticket(self) -> SyntheticValue:
        index = self._next("ticket")
        return SyntheticValue(f"ticket_{index:04d}", f"INC{100000 + index * 37:08d}")

    def kb_article(self) -> SyntheticValue:
        index = self._next("kb")
        return SyntheticValue(f"kb_{index:04d}", f"KB{2700 + index * 13:09d}")

    def machine(self) -> SyntheticValue:
        index = self._next("machine")
        return SyntheticValue(f"machine_{index:04d}", f"DEMO-PC-{6900 + index * 7:04d}")

    def version(self) -> SyntheticValue:
        index = self._next("version")
        return SyntheticValue(f"version_{index:04d}", f"v4.{index % 20}.{index % 7}")

    def order(self) -> SyntheticValue:
        index = self._next("order")
        return SyntheticValue(f"order_{index:04d}", f"{12000 + index * 11}")


def _validate_phone_pools() -> None:
    """Every pooled number must be a valid number, not merely digit-shaped."""
    for language, numbers in PHONES.items():
        for number in numbers:
            parsed = phonenumbers.parse(number, None)
            if not phonenumbers.is_valid_number(parsed):
                raise CorpusError(
                    f"phone pool for {language!r} contains an invalid number at index "
                    f"{numbers.index(number)}"
                )
