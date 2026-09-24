"""Feingehalte, Karat, Gewicht und Materialwert.

Wichtig (Abschnitt 11 der Grundprompt): Alles hier sind *Angaben im Text*,
keine Identifikation. Eine "585" im Text ist eine Verkäuferbehauptung, keine
gesicherte Punze.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

FEINGEHALTE = {
    "333": 0.333,
    "375": 0.375,
    "417": 0.417,
    "585": 0.585,
    "750": 0.750,
    "916": 0.916,
    "999": 0.999,
}

KARAT = {8: 0.333, 9: 0.375, 10: 0.417, 14: 0.585, 18: 0.750, 21: 0.875, 22: 0.916, 24: 0.999}

# Ankaufsquote für Altgold (Händler zahlen typischerweise 85–95 % des Materialwerts)
ANKAUFSQUOTE = 0.9

_FEINGEHALT_RE = re.compile(r"(?<![0-9.,])(333|375|417|585|750|916|999)(?:er|/000|/1000)?(?![0-9])")
_KARAT_RE = re.compile(
    r"(?<![0-9.,])(8|9|10|14|18|21|22|24)\s?"
    r"(k|kt|kr|ct|kar|karat|karaat|carat|carats|carati|ct gold|kt gold)(?![a-z])"
)
_GEWICHT_RE = re.compile(
    r"(?<![0-9])(\d{1,3}(?:[.,]\d{1,2})?)\s?(g|gr|gramm|gram|grams|grammes|grammi|grs)(?![a-z])"
)
_GEWICHT_LABEL_RE = re.compile(r"(?:gewicht|wiegt|weight|poids|peso)\s*(?:ca\.?|circa|etwa|:|=)?\s*(\d{1,3}(?:[.,]\d{1,2})?)")


@dataclass(frozen=True)
class Goldangabe:
    text: str
    feingehalt: float


def finde_feingehalte(text_norm: str, gold_erwaehnt: bool) -> list[Goldangabe]:
    """Findet Feingehaltsangaben wie 585, 750er, 18k, 14 Karat.

    ``999`` zählt nur, wenn im Text überhaupt von Gold die Rede ist
    (sonst meist Feinsilber).
    """
    treffer: list[Goldangabe] = []
    for m in _FEINGEHALT_RE.finditer(text_norm):
        zahl = m.group(1)
        if zahl == "999" and not gold_erwaehnt:
            continue
        treffer.append(Goldangabe(m.group(0), FEINGEHALTE[zahl]))
    for m in _KARAT_RE.finditer(text_norm):
        treffer.append(Goldangabe(m.group(0).strip(), KARAT[int(m.group(1))]))
    eindeutig: dict[float, Goldangabe] = {}
    for g in treffer:
        eindeutig.setdefault(g.feingehalt, g)  # "585" und "585er" sind dieselbe Angabe
    return list(eindeutig.values())


def finde_gewicht(text: str) -> float | None:
    """Liest ein Gewicht in Gramm aus dem Text (größter plausibler Wert)."""
    t = text.lower()
    werte: list[float] = []
    for m in _GEWICHT_RE.finditer(t):
        werte.append(float(m.group(1).replace(",", ".")))
    for m in _GEWICHT_LABEL_RE.finditer(t):
        werte.append(float(m.group(1).replace(",", ".")))
    plausibel = [w for w in werte if 0.2 <= w <= 500]
    return max(plausibel) if plausibel else None


def materialwert(gewicht_g: float, feingehalt: float, goldpreis_eur_g: float) -> float:
    """Reiner Feingoldwert in Euro."""
    return round(gewicht_g * feingehalt * goldpreis_eur_g, 2)


def ankaufswert(gewicht_g: float, feingehalt: float, goldpreis_eur_g: float) -> float:
    """Konservativer Altgold-Ankaufswert (was ein Händler mindestens zahlt)."""
    return round(materialwert(gewicht_g, feingehalt, goldpreis_eur_g) * ANKAUFSQUOTE, 2)
