"""Suchgenerator für die Richtungen A–G (Abschnitt 15 der Grundprompt).

Verbesserungen gegenüber einer manuellen Suche:

* alle sieben Richtungen werden systematisch und gemischt abgedeckt,
* Richtung F erzeugt Tippfehler-Varianten von Marken automatisch
  (genau die Anzeigen, die andere Käufer NICHT finden),
* eine Tagesrotation verteilt große Suchmengen über mehrere Läufe,
  damit Vinted nicht mit hunderten Anfragen auf einmal belastet wird.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import date

from .text import normalisiere
from .wissen import Marke, Wissen

ALLE_RICHTUNGEN = "ABCDEFG"

# Schmuckarten, mit denen Marken kombiniert werden (Richtung E)
_MARKEN_ZUSATZ = {
    "luxus": ["vintage"],
    "sammler": [""],
    "goldschmied": [""],
    "designer_modeschmuck": ["", "Brosche"],
}


@dataclass(frozen=True)
class Suchanfrage:
    text: str
    richtung: str
    grund: str

    @property
    def schluessel(self) -> str:
        return normalisiere(self.text)


def tippfehler_varianten(name: str, max_anzahl: int = 6) -> list[str]:
    """Erzeugt plausible Falschschreibungen eines Markennamens.

    Regeln: Doppelkonsonant vereinfachen/verdoppeln, Buchstabendreher,
    typische Lautverwechslungen (ph/f, y/i, c/k, ie/i, th/t, é/e).
    """
    basis = name.lower()
    varianten: list[str] = []

    def dazu(v: str) -> None:
        v = " ".join(v.split())
        if v and v != basis and v not in varianten and len(v) >= 4:
            varianten.append(v)

    ersetzungen = [
        ("ph", "f"), ("y", "i"), ("i", "y"), ("c", "k"), ("k", "c"), ("ie", "i"), ("th", "t"),
        ("é", "e"), ("è", "e"), ("ö", "o"), ("ü", "u"), ("ä", "a"), ("ss", "s"), ("tz", "z"),
        ("v", "w"), ("w", "v"), ("ou", "u"), ("ch", "sh"), ("ck", "k"), ("qu", "k"),
    ]
    for alt, neu in ersetzungen:
        if alt in basis:
            dazu(basis.replace(alt, neu, 1))
    # Doppelbuchstaben vereinfachen
    for i in range(len(basis) - 1):
        if basis[i] == basis[i + 1] and basis[i].isalpha():
            dazu(basis[:i] + basis[i + 1:])
    # Konsonant verdoppeln (nur an der ersten passenden Stelle nach dem Anfang)
    for i in range(2, len(basis) - 1):
        c = basis[i]
        if c.isalpha() and c not in "aeiouy" and basis[i - 1] != c and basis[i + 1] != c:
            dazu(basis[:i] + c + basis[i:])
            break
    # Buchstabendreher in der Wortmitte
    for i in range(1, len(basis) - 2):
        if basis[i].isalpha() and basis[i + 1].isalpha() and basis[i] != basis[i + 1]:
            dazu(basis[:i] + basis[i + 1] + basis[i] + basis[i + 2:])
            break
    # Letzten Buchstaben weglassen
    if len(basis) > 6 and basis[-1].isalpha():
        dazu(basis[:-1])
    return varianten[:max_anzahl]


class Suchgenerator:
    def __init__(self, wissen: Wissen, sprache: str = "de"):
        self.w = wissen
        self.sprache = sprache

    def _richtungsbegriffe(self, kuerzel: str) -> list[str]:
        r = self.w.richtungen.get(kuerzel)
        if not r:
            return []
        begriffe = list(r.begriffe.get(self.sprache) or ())
        if not begriffe:
            begriffe = list(r.begriffe.get("en") or ())
        return begriffe

    def _marken_fuer_suche(self) -> list[Marke]:
        return [m for m in self.w.marken if m.suche and m.stufe in _MARKEN_ZUSATZ]

    def richtung(self, kuerzel: str) -> list[Suchanfrage]:
        k = kuerzel.upper()
        if k == "E":
            anfragen = []
            for m in self._marken_fuer_suche():
                for zusatz in _MARKEN_ZUSATZ[m.stufe]:
                    text = f"{m.suchtext} {zusatz}".strip()
                    anfragen.append(Suchanfrage(text, "E", f"Marke ({m.stufe})"))
            return anfragen
        if k == "F":
            anfragen = [Suchanfrage(t, "F", "Fehler-/Stempelsuche") for t in self._richtungsbegriffe("F")]
            for m in self._marken_fuer_suche():
                if m.stufe == "luxus":
                    continue  # Tippfehler bei Luxusmarken liefern v. a. Fälschungen
                bekannt = list(m.tippfehler)
                auto = tippfehler_varianten(m.suchtext, max_anzahl=3)
                for t in bekannt[:3] + [a for a in auto if a not in bekannt][:1]:
                    anfragen.append(Suchanfrage(t, "F", f"Tippfehler von {m.name}"))
            return anfragen
        name = self.w.richtungen[k].name if k in self.w.richtungen else k
        return [Suchanfrage(t, k, name) for t in self._richtungsbegriffe(k)]

    def erzeuge(
        self,
        richtungen: str = ALLE_RICHTUNGEN,
        max_anfragen: int | None = None,
        rotation: bool = False,
        stichtag: date | None = None,
    ) -> list[Suchanfrage]:
        """Mischt die Richtungen reihum, damit auch bei einem Limit alle vertreten sind."""
        je_richtung: dict[str, list[Suchanfrage]] = {}
        for k in richtungen.upper():
            if k not in ALLE_RICHTUNGEN:
                raise ValueError(f"Unbekannte Suchrichtung '{k}' (erlaubt: {ALLE_RICHTUNGEN})")
            liste = self.richtung(k)
            if rotation:
                tag = (stichtag or date.today()).isoformat()
                seed = int(hashlib.sha256(f"{tag}{k}".encode()).hexdigest(), 16)
                random.Random(seed).shuffle(liste)
            je_richtung[k] = liste
        ergebnis: list[Suchanfrage] = []
        gesehen: set[str] = set()
        runde = 0
        while any(runde < len(l) for l in je_richtung.values()):
            for liste in je_richtung.values():
                if runde < len(liste):
                    a = liste[runde]
                    if a.schluessel not in gesehen:
                        gesehen.add(a.schluessel)
                        ergebnis.append(a)
            runde += 1
        if max_anfragen is not None:
            ergebnis = ergebnis[:max_anfragen]
        return ergebnis
