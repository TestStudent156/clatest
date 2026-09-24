"""Zentrale Einstellungen – alles per CLI-Option oder Umgebungsvariable änderbar."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJEKT_DIR = Path(__file__).resolve().parent.parent
PROMPT_DATEI = PROJEKT_DIR / "prompts" / "grundprompt.md"
ANALYSE_DATEI = PROJEKT_DIR / "prompts" / "analyse_auftrag.md"


def _float_env(name: str, standard: float) -> float:
    try:
        return float(os.environ.get(name, standard))
    except ValueError:
        return standard


@dataclass
class Einstellungen:
    # Markt
    domain: str = field(default_factory=lambda: os.environ.get("VH_DOMAIN", "de"))
    # Goldkurs in €/g Feingold. Bitte aktuell halten (z. B. per --goldpreis oder VH_GOLDPREIS).
    goldpreis_eur_g: float = field(default_factory=lambda: _float_env("VH_GOLDPREIS", 110.0))
    # Abschnitt 13: Mindestinteressantheit für Nicht-Gold-Einzelstücke
    mindest_wiederverkauf_eur: float = 40.0
    # Suche
    max_preis: float | None = 150.0
    seiten_pro_anfrage: int = 1
    pro_seite: int = 96
    max_anfragen: int = 40
    katalog_ids: list[int] = field(default_factory=list)
    verzoegerung_s: float = field(default_factory=lambda: _float_env("VH_VERZOEGERUNG", 2.0))
    # KI
    modell: str = field(default_factory=lambda: os.environ.get("VH_MODELL", "claude-opus-5"))
    triage_anzahl: int = 25
    tiefen_anzahl: int = 8
    max_fotos_triage: int = 3
    max_fotos_tief: int = 8
    # Ablage
    daten_dir: Path = field(default_factory=lambda: Path(os.environ.get("VH_DATEN", PROJEKT_DIR / "daten")))
    berichte_dir: Path = field(default_factory=lambda: Path(os.environ.get("VH_BERICHTE", PROJEKT_DIR / "berichte")))

    @property
    def db_pfad(self) -> Path:
        return self.daten_dir / "hunter.sqlite"

    @property
    def sprache(self) -> str:
        return SPRACHE_JE_DOMAIN.get(self.domain, "en")


DOMAINS = {
    "de": "www.vinted.de",
    "at": "www.vinted.at",
    "lu": "www.vinted.lu",
    "fr": "www.vinted.fr",
    "be": "www.vinted.be",
    "nl": "www.vinted.nl",
    "it": "www.vinted.it",
    "es": "www.vinted.es",
    "pt": "www.vinted.pt",
    "pl": "www.vinted.pl",
    "cz": "www.vinted.cz",
    "lt": "www.vinted.lt",
    "uk": "www.vinted.co.uk",
}

SPRACHE_JE_DOMAIN = {"de": "de", "at": "de", "lu": "de", "fr": "fr", "be": "fr", "nl": "nl", "it": "it"}
