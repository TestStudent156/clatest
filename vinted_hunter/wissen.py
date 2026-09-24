"""Lädt die editierbare Wissensbasis (TOML-Dateien in ``vinted_hunter/wissen``)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .text import normalisiere

WISSEN_DIR = Path(__file__).parent / "wissen"

STUFEN_PUNKTE = {
    "luxus": 12,
    "sammler": 30,
    "goldschmied": 28,
    "designer_modeschmuck": 16,
    "neutral": 0,
    "massenware": 0,
}


@dataclass(frozen=True)
class Marke:
    name: str
    aliase: tuple[str, ...]
    tippfehler: tuple[str, ...]
    stufe: str
    land: str = ""
    epoche: str = ""
    hinweis: str = ""
    suche: bool = True
    suchbegriff: str = ""

    @property
    def suchtext(self) -> str:
        return self.suchbegriff or self.name.split(" (")[0]

    @property
    def punkte(self) -> int:
        return STUFEN_PUNKTE.get(self.stufe, 0)


@dataclass(frozen=True)
class DNA:
    erinnert_an: str
    alle: tuple[str, ...] = ()
    eines: tuple[str, ...] = ()
    eines_zusatz: tuple[str, ...] = ()
    gold: bool = False
    gewicht: int = 5


@dataclass(frozen=True)
class Richtung:
    kuerzel: str
    name: str
    beschreibung: str
    begriffe: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class Wissen:
    marken: tuple[Marke, ...]
    begriffe: dict
    richtungen: dict[str, Richtung]
    dna: tuple[DNA, ...]

    def liste(self, *pfad: str) -> list[str]:
        """Zugriff wie ``liste("gold", "woerter")`` – liefert immer eine Liste."""
        knoten = self.begriffe
        for p in pfad:
            knoten = knoten.get(p, {}) if isinstance(knoten, dict) else {}
        return list(knoten) if isinstance(knoten, list) else []

    def wert(self, *pfad: str, standard=None):
        knoten = self.begriffe
        for p in pfad:
            if not isinstance(knoten, dict) or p not in knoten:
                return standard
            knoten = knoten[p]
        return knoten


def _lade_toml(name: str, verzeichnis: Path) -> dict:
    with open(verzeichnis / name, "rb") as f:
        return tomllib.load(f)


@lru_cache(maxsize=4)
def lade_wissen(verzeichnis: str | None = None) -> Wissen:
    pfad = Path(verzeichnis) if verzeichnis else WISSEN_DIR
    roh_marken = _lade_toml("marken.toml", pfad).get("marke", [])
    marken = tuple(
        Marke(
            name=m["name"],
            aliase=tuple(m.get("aliase", [])),
            tippfehler=tuple(m.get("tippfehler", [])),
            stufe=m.get("stufe", "neutral"),
            land=m.get("land", ""),
            epoche=m.get("epoche", ""),
            hinweis=m.get("hinweis", ""),
            suche=m.get("suche", True),
            suchbegriff=m.get("suchbegriff", ""),
        )
        for m in roh_marken
    )
    begriffe = _lade_toml("begriffe.toml", pfad)
    suche = _lade_toml("suche.toml", pfad)
    richtungen = {
        k: Richtung(
            kuerzel=k,
            name=v.get("name", k),
            beschreibung=v.get("beschreibung", ""),
            begriffe={s: tuple(v.get(s, [])) for s in ("de", "fr", "it", "nl", "en")},
        )
        for k, v in suche.get("richtung", {}).items()
    }
    dna = tuple(
        DNA(
            erinnert_an=d["erinnert_an"],
            alle=tuple(d.get("alle", [])),
            eines=tuple(d.get("eines", [])),
            eines_zusatz=tuple(d.get("eines_zusatz", [])),
            gold=d.get("gold", False),
            gewicht=d.get("gewicht", 5),
        )
        for d in suche.get("dna", [])
    )
    _pruefe_aliase(marken)
    return Wissen(marken=marken, begriffe=begriffe, richtungen=richtungen, dna=dna)


def _pruefe_aliase(marken: tuple[Marke, ...]) -> None:
    """Verhindert, dass ein Alias zwei Marken mit unterschiedlicher Stufe zugeordnet ist."""
    gesehen: dict[str, Marke] = {}
    for m in marken:
        for a in m.aliase:
            n = normalisiere(a)
            alt = gesehen.get(n)
            if alt and alt.stufe != m.stufe:
                raise ValueError(f"Alias '{a}' ist doppelt vergeben: {alt.name} / {m.name}")
            gesehen[n] = m
