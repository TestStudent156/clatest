"""Die Such-Pipeline: Suchen → Vorfilter → Details → Vorfilter → (KI) → Bericht."""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .ablage import Ablage
from .bericht import Fund, Laufstatistik
from .einstellungen import Einstellungen
from .heuristik import PRIO_INTERESSANT, PRIO_RANG, Vorfilter
from .ki import ClaudeAnalyst, KIFehler
from .modelle import Anzeige
from .suchanfragen import Suchgenerator
from .vinted import VintedClient, VintedFehler, anzeige_aus_api
from .wissen import lade_wissen

log = logging.getLogger(__name__)


def _melde(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


@dataclass
class JagdOptionen:
    richtungen: str = "ABCDEFG"
    rotation: bool = True
    details_top: int = 40
    visuell_top: int = 8
    ki: bool = False
    recherche: bool = False
    nur_neue: bool = False
    bilder_export: bool = False


class Jagd:
    def __init__(
        self,
        einstellungen: Einstellungen,
        optionen: JagdOptionen | None = None,
        client: VintedClient | None = None,
        analyst: ClaudeAnalyst | None = None,
        ablage: Ablage | None = None,
        melde: Callable[[str], None] = _melde,
    ):
        self.e = einstellungen
        self.o = optionen or JagdOptionen()
        self.wissen = lade_wissen()
        self.vorfilter = Vorfilter(self.wissen, einstellungen)
        self._client = client
        self._analyst = analyst
        self.ablage = ablage
        self.melde = melde
        self.stat = Laufstatistik(goldpreis=einstellungen.goldpreis_eur_g)

    @property
    def client(self) -> VintedClient:
        if self._client is None:
            self._client = VintedClient(self.e.domain, self.e.verzoegerung_s)
        return self._client

    @property
    def analyst(self) -> ClaudeAnalyst:
        if self._analyst is None:
            self._analyst = ClaudeAnalyst(self.e, foto_lader=self.client.lade_foto)
        return self._analyst

    # ------------------------------------------------------------ 1. Suchen
    def suchen(self) -> dict[str, Anzeige]:
        gen = Suchgenerator(self.wissen, self.e.sprache)
        anfragen = gen.erzeuge(self.o.richtungen, self.e.max_anfragen, rotation=self.o.rotation)
        self.melde(f"🔎 {len(anfragen)} Suchanfragen in Richtungen {self.o.richtungen} auf vinted.{self.e.domain}")
        funde: dict[str, Anzeige] = {}
        fehler_in_folge = 0
        for i, q in enumerate(anfragen, start=1):
            for seite in range(1, self.e.seiten_pro_anfrage + 1):
                try:
                    ergebnisse = self.client.suche(
                        q.text, seite=seite, pro_seite=self.e.pro_seite, preis_bis=self.e.max_preis, katalog_ids=self.e.katalog_ids
                    )
                    fehler_in_folge = 0
                except VintedFehler as err:
                    fehler_in_folge += 1
                    self.stat.fehler.append(f"Suche '{q.text}': {err}")
                    if fehler_in_folge >= 3:
                        self.melde("⛔ Vinted blockiert wiederholt – Suche abgebrochen (siehe README: VINTED_COOKIE).")
                        self.stat.anfragen = i
                        return funde
                    break
                self.stat.treffer_gesamt += len(ergebnisse)
                for a in ergebnisse:
                    vorhanden = funde.setdefault(a.id, a)
                    vorhanden.merke_fund(q.text, q.richtung)
                if len(ergebnisse) < self.e.pro_seite:
                    break
            if i % 10 == 0:
                self.melde(f"   … {i}/{len(anfragen)} Anfragen, {len(funde)} eindeutige Anzeigen")
        self.stat.anfragen = len(anfragen)
        return funde

    # ------------------------------------------------------------ 2./3. Vorfilter + Details
    def vorfiltern(self, anzeigen: Iterable[Anzeige]) -> list[Fund]:
        return [Fund(a, self.vorfilter.bewerte(a)) for a in anzeigen]

    @staticmethod
    def _detail_rang(f: Fund) -> float:
        a, v = f.anzeige, f.vorbewertung
        rang = v.punkte + 5 * (len(a.richtungen) - 1) + 2 * len(a.suchanfragen)
        preis = a.einkaufspreis or 0
        if 0 < preis <= 20:
            rang += 5
        # Beschreibungsbasierte Richtungen (B, F) verraten sich oft erst in der Beschreibung
        if {"B", "F"} & set(a.richtungen):
            rang += 8
        return rang

    def details_laden(self, funde: list[Fund]) -> list[Fund]:
        offen = [f for f in funde if not f.vorbewertung.ausgeschlossen and not f.anzeige.details_geladen]
        offen.sort(key=self._detail_rang, reverse=True)
        auswahl = offen[: self.o.details_top]
        visuell = [f for f in offen[self.o.details_top:] if "G" in f.anzeige.richtungen][: self.o.visuell_top]
        ziel = auswahl + visuell
        if ziel:
            self.melde(f"📄 Lade Details (Beschreibung, alle Fotos) für {len(ziel)} Anzeigen")
        for f in ziel:
            try:
                d = self.client.details(f.anzeige.id)
            except VintedFehler as err:
                self.stat.fehler.append(f"Details {f.anzeige.id}: {err}")
                continue
            if d:
                f.anzeige.uebernimm_details(d)
                f.vorbewertung = self.vorfilter.bewerte(f.anzeige)
        return funde

    # ------------------------------------------------------------ 4. Ablage
    def ablegen(self, funde: list[Fund]) -> list[Fund]:
        for f in funde:
            if f.vorbewertung.ausgeschlossen:
                self.stat.zaehle_ausschluss(f.vorbewertung.ausschlussgrund)
            if self.ablage is None:
                f.ablage_status = "neu"
                self.stat.neu += 1
                continue
            f.ablage_status = self.ablage.speichere(
                f.anzeige, f.vorbewertung.punkte, f.vorbewertung.prioritaet, f.vorbewertung.als_dict()
            )
            if f.ablage_status == "neu":
                self.stat.neu += 1
            elif f.ablage_status == "preis_gesenkt":
                self.stat.preis_gesenkt += 1
            gespeichert = self.ablage.analyse(f.anzeige.id)
            if gespeichert and not self.ablage.braucht_analyse(f.anzeige):
                f.analyse = gespeichert
        if self.o.nur_neue:
            funde = [f for f in funde if f.ablage_status in ("neu", "preis_gesenkt")]
        return funde

    # ------------------------------------------------------------ 5. KI
    def ki_pruefen(self, funde: list[Fund]) -> None:
        kandidaten = [
            f for f in funde
            if not f.vorbewertung.ausgeschlossen and f.analyse is None
            and (PRIO_RANG[f.vorbewertung.prioritaet] >= PRIO_RANG[PRIO_INTERESSANT] or f.vorbewertung.visuell_kandidat)
            and f.anzeige.fotos
        ]
        text_kandidaten = sorted((f for f in kandidaten if not f.vorbewertung.visuell_kandidat), key=lambda f: f.rang, reverse=True)
        visuell = [f for f in kandidaten if f.vorbewertung.visuell_kandidat][: self.o.visuell_top]
        triage = text_kandidaten[: self.e.triage_anzahl] + visuell
        if not triage:
            self.melde("🤖 Keine Kandidaten für die KI-Prüfung.")
            return
        self.melde(f"🤖 KI-Triage für {len(triage)} Anzeigen (Modell {self.e.modell})")
        for f in triage:
            try:
                f.triage = self.analyst.triage(f.anzeige, f.vorbewertung)
            except KIFehler as err:
                f.fehler = f"KI-Triage: {err}"
                self.stat.fehler.append(f"Triage {f.anzeige.id}: {err}")
                if "API-Schlüssel" in str(err):
                    break
        tief = sorted(
            (f for f in triage if f.triage and f.triage.get("vertiefen")),
            key=lambda f: (PRIO_RANG.get(f.triage["prioritaet"], 0), f.vorbewertung.punkte),
            reverse=True,
        )[: self.e.tiefen_anzahl]
        if tief:
            self.melde(f"🔬 Tiefenprüfung für {len(tief)} Anzeigen" + (" inkl. Vergleichsrecherche" if self.o.recherche else ""))
        for f in tief:
            try:
                if self.o.recherche:
                    f.recherche = self.analyst.recherche(f.anzeige, f.triage.get("hypothese", ""))
                f.analyse = self.analyst.tiefenpruefung(f.anzeige, f.vorbewertung, f.recherche, f.triage)
                if self.ablage:
                    self.ablage.speichere_analyse(f.anzeige.id, f.analyse, f.anzeige.preis)
            except KIFehler as err:
                f.fehler = f"KI-Tiefenprüfung: {err}"
                self.stat.fehler.append(f"Tiefenprüfung {f.anzeige.id}: {err}")
        self.stat.ki_verbrauch = self.analyst.verbrauch.zusammenfassung(self.e.modell)

    # ------------------------------------------------------------ 6. Fotos exportieren
    def bilder_exportieren(self, funde: list[Fund], ab_rang: int = 1) -> Path:
        """Speichert Fotos der Kandidaten lokal – z. B. zur Begutachtung durch Claude Code (/schatzsuche)."""
        ziel = self.e.daten_dir / "bilder"
        for f in funde:
            if f.vorbewertung.ausgeschlossen:
                continue
            if PRIO_RANG.get(f.prioritaet, 0) < ab_rang and not f.vorbewertung.visuell_kandidat:
                continue
            ordner = ziel / f.anzeige.id
            ordner.mkdir(parents=True, exist_ok=True)
            (ordner / "anzeige.json").write_text(
                json.dumps({"anzeige": f.anzeige.als_dict(), "vorbewertung": f.vorbewertung.als_dict()}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            for i, url in enumerate(f.anzeige.fotos, start=1):
                datei = ordner / f"foto_{i:02d}.jpg"
                if datei.exists():
                    continue
                geladen = self.client.lade_foto(url)
                if geladen:
                    datei.write_bytes(geladen[0])
        return ziel

    # ------------------------------------------------------------ Gesamtlauf
    def lauf(self) -> list[Fund]:
        roh = self.suchen()
        self.stat.eindeutig = len(roh)
        funde = self.vorfiltern(roh.values())
        funde = self.details_laden(funde)
        funde = self.ablegen(funde)
        if self.o.ki:
            self.ki_pruefen(funde)
        if self.o.bilder_export:
            pfad = self.bilder_exportieren(funde)
            self.melde(f"🖼️  Fotos der Kandidaten gespeichert unter {pfad}")
        return funde

    def pruefe_einzeln(self, anzeige: Anzeige, recherche: bool = False) -> Fund:
        """Einzelne Anzeige vollständig prüfen (ohne Triage-Stufe)."""
        f = Fund(anzeige, self.vorfilter.bewerte(anzeige))
        if self.ablage:
            f.ablage_status = self.ablage.speichere(anzeige, f.vorbewertung.punkte, f.vorbewertung.prioritaet, f.vorbewertung.als_dict())
        if self.o.ki and anzeige.fotos:
            try:
                if recherche:
                    hypothese = "; ".join(f.vorbewertung.indizien[:3]) or anzeige.titel
                    f.recherche = self.analyst.recherche(anzeige, hypothese)
                f.analyse = self.analyst.tiefenpruefung(anzeige, f.vorbewertung, f.recherche)
                if self.ablage:
                    self.ablage.speichere_analyse(anzeige.id, f.analyse, anzeige.preis)
            except KIFehler as err:
                f.fehler = str(err)
            self.stat.ki_verbrauch = self.analyst.verbrauch.zusammenfassung(self.e.modell)
        return f


def lade_anzeigen_datei(pfad: Path, domain: str = "de") -> list[Anzeige]:
    """Liest Anzeigen aus JSON: Liste eigener Anzeige-Dicts, Vinted-API-Objekte oder {"items": [...]}."""
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    if isinstance(daten, dict):
        daten = daten.get("items") or daten.get("anzeigen") or daten.get("funde") or []
    anzeigen = []
    for d in daten:
        if "anzeige" in d and isinstance(d["anzeige"], dict):
            d = d["anzeige"]
        if "titel" in d:
            anzeigen.append(Anzeige.aus_dict(d))
        else:
            anzeigen.append(anzeige_aus_api(d, domain, details=bool(d.get("description"))))
    return anzeigen
