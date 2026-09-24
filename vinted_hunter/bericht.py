"""Berichte im Ausgabeformat der Grundprompt (Abschnitt 18).

Standardmäßig nur 🔥🔥🔥 und 🔥🔥 (Abschnitt 17). Ohne KI-Analyse wird klar
als "Vorfilter" gekennzeichnet und NIE ein Kaufurteil ausgesprochen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .heuristik import GOLD_BESCHREIBUNG, PRIO_RANG, PRIO_SYMBOL, Vorbewertung
from .modelle import Anzeige

EVIDENZ_SYMBOL = {
    "IDENTIFIZIERT": "🟢 IDENTIFIZIERT",
    "SEHR_WAHRSCHEINLICH": "🟢 SEHR WAHRSCHEINLICH",
    "PLAUSIBEL": "🟡 PLAUSIBEL",
    "VERDACHT": "🟠 VERDACHT",
    "KEIN_HINWEIS": "🔴 KEIN AUSREICHENDER HINWEIS",
}


@dataclass
class Fund:
    anzeige: Anzeige
    vorbewertung: Vorbewertung
    triage: dict | None = None
    analyse: dict | None = None
    recherche: str | None = None
    ablage_status: str = ""
    fehler: str = ""

    @property
    def prioritaet(self) -> str:
        if self.analyse:
            return self.analyse.get("prioritaet", self.vorbewertung.prioritaet)
        if self.triage and not self.triage.get("vertiefen", True):
            return self.triage.get("prioritaet", self.vorbewertung.prioritaet)
        return self.vorbewertung.prioritaet

    @property
    def rang(self) -> tuple[int, int]:
        return PRIO_RANG.get(self.prioritaet, 0), self.vorbewertung.punkte


@dataclass
class Laufstatistik:
    anfragen: int = 0
    treffer_gesamt: int = 0
    eindeutig: int = 0
    ausgeschlossen: dict[str, int] = field(default_factory=dict)
    neu: int = 0
    preis_gesenkt: int = 0
    fehler: list[str] = field(default_factory=list)
    ki_verbrauch: str = ""
    goldpreis: float = 0.0

    def zaehle_ausschluss(self, grund: str) -> None:
        schluessel = grund.split(" (")[0].split(" ('")[0]
        self.ausgeschlossen[schluessel] = self.ausgeschlossen.get(schluessel, 0) + 1


def _eur(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _liste(werte: list[str], leer: str = "—") -> str:
    return "\n".join(f"- {w}" for w in werte) if werte else leer


def fund_markdown(f: Fund) -> str:
    a, v, k = f.anzeige, f.vorbewertung, f.analyse
    preis = _eur(a.preis) + (f" (inkl. Käuferschutz {_eur(a.gesamtpreis)})" if a.gesamtpreis else "")
    kopf = PRIO_SYMBOL.get(f.prioritaet, f.prioritaet)
    quelle = "KI-Tiefenprüfung" if k else ("KI-Triage + Vorfilter" if f.triage else "nur Text-Vorfilter")
    herkunft = f" · gefunden über Richtung {', '.join(a.richtungen)}" if a.richtungen else ""
    teile = [f"### {kopf}", "", f"*Bewertung: {quelle} · Vorfilter {v.punkte}/100{herkunft}*", ""]
    if f.ablage_status == "preis_gesenkt":
        teile += ["**⬇️ Preis wurde gesenkt, seit die Anzeige zuletzt gesehen wurde.**", ""]
    teile += [
        f"**Artikel:** [{a.titel}]({a.url})",
        "",
        f"**Preis:** {preis}",
        "",
    ]
    if k:
        teile += [
            f"**Was der Verkäufer glaubt:** {k.get('was_der_verkaeufer_glaubt', '')}",
            "",
            "**Was daran verdächtig ist:**",
            _liste(k.get("was_verdaechtig_ist", [])),
            "",
            f"**Goldverdacht:** {EVIDENZ_SYMBOL.get(k['goldverdacht']['stufe'], '')} – {k['goldverdacht']['begruendung']}",
            "",
            f"**Designer-/Markenverdacht:** {EVIDENZ_SYMBOL.get(k['designerverdacht']['stufe'], '')}"
            + (f" ({k['designerverdacht']['kandidat']})" if k["designerverdacht"].get("kandidat") else "")
            + f" – {k['designerverdacht']['begruendung']}",
            "",
            f"**Historische Einordnung:** {k.get('historische_einordnung') or '—'}",
            "",
            f"**Warum könnte der Verkäufer den Wert übersehen haben?** {k.get('warum_uebersehen', '')}",
            "",
            "**Nicht gezeigt (Negativsuche):**",
            _liste(k.get("nicht_gezeigt", [])),
            "",
        ]
        if k.get("gelesene_punzen"):
            teile += ["**Auf Fotos gelesen:**", _liste([f"{p['text']} (Foto {p['foto_nr']}, {EVIDENZ_SYMBOL.get(p['stufe'], p['stufe'])})" for p in k["gelesene_punzen"]]), ""]
        if k.get("einzelstuecke"):
            teile += ["**Einzelstücke (Konvolut):**", _liste([f"{PRIO_SYMBOL.get(e['prioritaet'], '')}: {e['beschreibung']} – {e['auffaelligkeit']}" for e in k["einzelstuecke"]]), ""]
        urteil = {"KAUFEN": "🟢 KAUFEN", "NUR_WENN_PREIS": f"🟡 NUR WENN PREIS ≤ {k.get('max_preis_eur', 0):.0f} €", "NICHT_KAUFEN": "🔴 NICHT KAUFEN"}[k["urteil"]]
        teile += [
            f"**Realistischer Wiederverkaufswert:** {k['wiederverkauf_min_eur']:.0f}–{k['wiederverkauf_max_eur']:.0f} € "
            f"(Händler: {k.get('haendlerpreis') or '—'}; Auktion: {k.get('auktionspreis') or '—'})",
            "",
            f"**Risiko:** {k['risiko']}",
            "",
            f"**Mein Urteil:** {urteil}",
            "",
            f"**Wichtigstes fehlendes Foto:** {k.get('wichtigstes_fehlendes_foto') or '—'}",
            "",
            f"**Begründung in einem Satz:** {k.get('begruendung_ein_satz', '')}",
            "",
        ]
    else:
        teile += [
            f"**Was der Verkäufer glaubt:** {v.verkaeufer_glaubt}",
            "",
            "**Was daran verdächtig ist:**",
            _liste(v.indizien + v.asymmetrie),
            "",
            f"**Goldverdacht:** {GOLD_BESCHREIBUNG[v.goldstatus]}"
            + (f" · Materialwert laut Textangaben ≈ {_eur(v.materialwert_eur)}" if v.materialwert_eur else ""),
            "",
            "**Designer-/Markenverdacht:** "
            + ("; ".join(f"{m.marke} ({m.art}: '{m.fundstelle}')" for m in v.echte_marken) or "—")
            + (f" · Formensprache erinnert an: {'; '.join(v.dna)}" if v.dna else ""),
            "",
            f"**Historische Einordnung:** {', '.join(v.epochen) if v.epochen else '—'} (nur Textangabe)",
            "",
            "**Nicht gezeigt / fehlt (Negativsuche):**",
            _liste(v.info_luecken),
            "",
        ]
        if f.triage:
            teile += [f"**KI-Erstsichtung:** {f.triage.get('hypothese', '')} – {f.triage.get('begruendung', '')}", ""]
        untergrenze = (
            f"{_eur(v.wert_untergrenze_eur)}" + (f" (≈ {v.preis_verhaeltnis:g}× Preis)" if v.preis_verhaeltnis else "")
            if v.wert_untergrenze_eur is not None
            else "aus dem Text nicht bestimmbar (kein Feingehalt, keine Sammlermarke)"
        )
        teile += [
            f"**Konservative Untergrenze:** {untergrenze} – Heuristik, keine Bewertung",
            "",
            "**Mein Urteil:** 🟡 PRÜFEN – Fotos selbst ansehen oder mit `--ki` analysieren; noch kein Kauf.",
            "",
            f"**Wichtigstes fehlendes Foto:** {v.wichtigstes_foto}",
            "",
        ]
    if v.warnungen:
        teile += ["**Warnungen:**", _liste(v.warnungen), ""]
    teile += [f"**Nachfrage an Verkäufer (Vorschlag):** _{v.nachricht_an_verkaeufer}_", ""]
    if f.recherche:
        teile += ["<details><summary>Vergleichsrecherche (ungeprüft)</summary>", "", f.recherche, "", "</details>", ""]
    if f.fehler:
        teile += [f"> ⚠️ {f.fehler}", ""]
    return "\n".join(teile)


def erstelle_bericht(
    funde: list[Fund],
    stat: Laufstatistik,
    auch_interessant: bool = False,
    titel: str = "Vinted-Schatzsuche",
) -> str:
    grenze = 1 if auch_interessant else 2
    sichtbar = sorted((f for f in funde if PRIO_RANG.get(f.prioritaet, 0) >= grenze), key=lambda f: f.rang, reverse=True)
    zeit = datetime.now().strftime("%d.%m.%Y %H:%M")
    zeilen = [
        f"# {titel} – {zeit}",
        "",
        f"- Suchanfragen: {stat.anfragen} · Treffer: {stat.treffer_gesamt} · eindeutige Anzeigen: {stat.eindeutig} "
        f"· neu: {stat.neu} · Preis gesenkt: {stat.preis_gesenkt}",
        f"- Goldkurs-Annahme: {stat.goldpreis:g} €/g Feingold (mit `--goldpreis` anpassen)",
    ]
    if stat.ki_verbrauch:
        zeilen.append(f"- KI: {stat.ki_verbrauch}")
    if stat.ausgeschlossen:
        gruende = ", ".join(f"{k}: {v}" for k, v in sorted(stat.ausgeschlossen.items(), key=lambda x: -x[1]))
        zeilen.append(f"- Aussortiert (Negativfilter): {gruende}")
    if stat.fehler:
        zeilen.append(f"- Fehler: {len(stat.fehler)} (siehe Ende)")
    zeilen += ["", f"Angezeigt: {'🔥🔥🔥, 🔥🔥 und 🔥' if auch_interessant else '🔥🔥🔥 und 🔥🔥'} · {len(sichtbar)} Funde", ""]
    if not sichtbar:
        zeilen += [
            "**Keine belastbaren Verdachtsfälle in diesem Lauf.** "
            "Lieber einen guten Fund verpassen als unbegründete „vielleicht wertvoll“-Artikel zu zeigen.",
            "",
        ]
    for f in sichtbar:
        zeilen += ["---", "", fund_markdown(f)]
    visuell = [f for f in funde if f.vorbewertung.visuell_kandidat and not f.analyse and not f.triage][:12]
    if visuell:
        zeilen += [
            "---",
            "",
            "## Nur per Foto beurteilbar (Richtung G)",
            "",
            "Der Text verrät nichts – ob Konstruktion oder Verarbeitung auffällig hochwertig sind, zeigt nur das Foto "
            "(mit `--ki` automatisch, sonst selbst ansehen):",
            "",
        ]
        zeilen += [f"- [{f.anzeige.titel}]({f.anzeige.url}) – {_eur(f.anzeige.einkaufspreis)}, {len(f.anzeige.fotos)} Foto(s)" for f in visuell]
        zeilen.append("")
    if stat.fehler:
        zeilen += ["---", "", "## Fehler", ""] + [f"- {e}" for e in stat.fehler[:50]]
    return "\n".join(zeilen).rstrip() + "\n"


def erstelle_chat_export(funde: list[Fund], max_anzahl: int = 15) -> str:
    """Kandidatenliste zum Einfügen in einen Claude-Chat (ohne API-Schlüssel nutzbar)."""
    kandidaten = sorted((f for f in funde if not f.vorbewertung.ausgeschlossen), key=lambda f: f.rang, reverse=True)[:max_anzahl]
    zeilen = [
        "Prüfe die folgenden Vinted-Anzeigen streng nach meiner Grundprompt (Schatzsucher-Regeln).",
        "Öffne jeden Link, sieh dir ALLE Fotos an und bewerte im Ausgabeformat (Abschnitt 18).",
        "Die Notizen stammen aus einem automatischen Text-Vorfilter und können falsch sein.",
        "Zeige nur 🔥🔥🔥 und 🔥🔥.",
        "",
    ]
    for i, f in enumerate(kandidaten, start=1):
        a, v = f.anzeige, f.vorbewertung
        notizen = (v.indizien + v.asymmetrie)[:4]
        zeilen += [
            f"{i}. {a.titel} – {_eur(a.einkaufspreis)} – {a.url}",
            f"   Vorfilter: {PRIO_SYMBOL[v.prioritaet]} ({v.punkte}/100), Gold: {v.goldstatus}, fehlt: {', '.join(v.info_luecken) or '—'}",
        ]
        zeilen += [f"   · {n}" for n in notizen]
    return "\n".join(zeilen) + "\n"


def speichere_berichte(
    funde: list[Fund], stat: Laufstatistik, verzeichnis: Path, auch_interessant: bool = False, chat_export: bool = False
) -> dict[str, Path]:
    verzeichnis.mkdir(parents=True, exist_ok=True)
    stempel = datetime.now().strftime("%Y-%m-%d_%H%M")
    pfade = {"markdown": verzeichnis / f"schatzsuche_{stempel}.md", "json": verzeichnis / f"schatzsuche_{stempel}.json"}
    pfade["markdown"].write_text(erstelle_bericht(funde, stat, auch_interessant), encoding="utf-8")
    daten = {
        "statistik": stat.__dict__,
        "funde": [
            {
                "anzeige": f.anzeige.als_dict(),
                "vorbewertung": f.vorbewertung.als_dict(),
                "triage": f.triage,
                "analyse": f.analyse,
                "recherche": f.recherche,
                "prioritaet": f.prioritaet,
                "ablage_status": f.ablage_status,
                "fehler": f.fehler,
            }
            for f in sorted(funde, key=lambda f: f.rang, reverse=True)
            if not f.vorbewertung.ausgeschlossen
        ],
    }
    pfade["json"].write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
    if chat_export:
        pfade["chat"] = verzeichnis / f"schatzsuche_{stempel}_chat.md"
        pfade["chat"].write_text(erstelle_chat_export(funde), encoding="utf-8")
    return pfade
