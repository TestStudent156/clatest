"""Datenmodell einer Vinted-Anzeige (unabhängig davon, woher sie stammt)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Anzeige:
    id: str
    titel: str
    preis: float | None = None
    waehrung: str = "EUR"
    gesamtpreis: float | None = None  # inkl. Käuferschutz, ohne Versand
    url: str = ""
    beschreibung: str = ""
    marke: str = ""  # Markenfeld der Anzeige (brand_title)
    zustand: str = ""
    groesse: str = ""
    katalog_id: int | None = None
    katalog_name: str = ""
    fotos: list[str] = field(default_factory=list)
    verkaeufer: str = ""
    favoriten: int | None = None
    aufrufe: int | None = None
    erstellt: str = ""
    domain: str = "de"
    suchanfragen: list[str] = field(default_factory=list)
    richtungen: list[str] = field(default_factory=list)
    details_geladen: bool = False

    @property
    def einkaufspreis(self) -> float | None:
        """Was der Käufer mindestens zahlt (Gesamtpreis, sonst Artikelpreis)."""
        return self.gesamtpreis if self.gesamtpreis is not None else self.preis

    def als_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def aus_dict(cls, d: dict[str, Any]) -> "Anzeige":
        felder = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        daten = {k: v for k, v in d.items() if k in felder}
        daten["id"] = str(daten.get("id", ""))
        return cls(**daten)

    def merke_fund(self, anfrage: str, richtung: str) -> None:
        if anfrage not in self.suchanfragen:
            self.suchanfragen.append(anfrage)
        if richtung not in self.richtungen:
            self.richtungen.append(richtung)

    def uebernimm_details(self, andere: "Anzeige") -> None:
        """Ergänzt Felder aus einer Detailabfrage, ohne Suchkontext zu verlieren."""
        for name in ("beschreibung", "marke", "zustand", "groesse", "katalog_name", "verkaeufer", "erstellt"):
            wert = getattr(andere, name)
            if wert:
                setattr(self, name, wert)
        for name in ("preis", "gesamtpreis", "katalog_id", "favoriten", "aufrufe"):
            wert = getattr(andere, name)
            if wert is not None:
                setattr(self, name, wert)
        if len(andere.fotos) > len(self.fotos):
            self.fotos = list(andere.fotos)
        if andere.titel:
            self.titel = andere.titel
        self.details_geladen = self.details_geladen or andere.details_geladen
