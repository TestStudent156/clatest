"""Textnormalisierung und robuste Begriffssuche.

Verkäufer schreiben uneinheitlich ("Anhänger", "Anhaenger", "ANHÄNGER",
"Art-Déco", "art deco"). Alle Texte und alle Begriffe aus der Wissensbasis
laufen deshalb durch dieselbe Normalisierung, bevor verglichen wird.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Iterable

_TRENNER = re.compile(r"[\-_/|•·+]+")
_LEER = re.compile(r"\s+")


def normalisiere(text: str | None) -> str:
    """Kleinschreibung, Akzente weg, ß -> ss, ae/oe/ue -> a/o/u, Bindestriche -> Leerzeichen."""
    if not text:
        return ""
    t = text.lower().replace("ß", "ss")
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.replace("ae", "a").replace("oe", "o").replace("ue", "u")
    t = _TRENNER.sub(" ", t)
    return _LEER.sub(" ", t).strip()


@lru_cache(maxsize=4096)
def _muster(begriff: str) -> re.Pattern[str]:
    b = normalisiere(begriff)
    kern = re.escape(b)
    if len(b) >= 6:
        # Lange Begriffe dürfen Teil eines Kompositums sein ("weissgoldring").
        return re.compile(kern)
    if len(b) >= 4:
        # Mittlere Begriffe: Wortanfang fest, kurze Endung erlaubt ("ringe", "brosche").
        return re.compile(rf"(?<![a-z0-9]){kern}[a-z]{{0,2}}(?![a-z0-9])")
    return re.compile(rf"(?<![a-z0-9]){kern}(?![a-z0-9])")


def enthaelt(text_norm: str, begriff: str) -> bool:
    return bool(_muster(begriff).search(text_norm))


def finde(text_norm: str, begriffe: Iterable[str]) -> list[str]:
    """Gibt alle gefundenen Begriffe (in Originalschreibweise, ohne Duplikate) zurück."""
    treffer: list[str] = []
    gesehen: set[str] = set()
    for b in begriffe:
        n = normalisiere(b)
        if not n or n in gesehen:
            continue
        gesehen.add(n)
        if _muster(b).search(text_norm):
            treffer.append(b)
    # "stempel" nicht zusätzlich zählen, wenn schon "gestempelt" gefunden wurde
    norm = {t: normalisiere(t) for t in treffer}
    return [t for t in treffer if not any(norm[t] != norm[o] and norm[t] in norm[o] for o in treffer)]


@lru_cache(maxsize=4096)
def _kompositum_muster(begriff: str) -> re.Pattern[str]:
    n = normalisiere(begriff)
    b = re.escape(n)
    if len(n) < 4:
        return re.compile(rf"(?<![a-z0-9]){b}(?![a-z0-9])")
    # Deutsches Kompositum: Kopf steht hinten ("Goldkette", "Siegelring").
    return re.compile(rf"(?<![a-z0-9])[a-z]*{b}[a-z]{{0,2}}(?![a-z0-9])")


def endet_mit_begriff(text_norm: str, begriffe: Iterable[str]) -> bool:
    return any(_kompositum_muster(b).search(text_norm) for b in begriffe)


def damerau_levenshtein(a: str, b: str) -> int:
    """Editierdistanz inkl. Buchstabendreher (für Tippfehler-Erkennung)."""
    la, lb = len(a), len(b)
    if abs(la - lb) > 2:
        return 3
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            kosten = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + kosten)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[la][lb]


def woerter(text_norm: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text_norm)
