"""Kommandozeile: ``python -m vinted_hunter <befehl> …``"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .ablage import Ablage
from .bericht import Laufstatistik, erstelle_bericht, fund_markdown, speichere_berichte
from .einstellungen import DOMAINS, Einstellungen
from .jagd import Jagd, JagdOptionen, lade_anzeigen_datei
from .suchanfragen import ALLE_RICHTUNGEN, Suchgenerator
from .vinted import VintedClient, VintedFehler, domain_aus_url, finde_schmuck_kataloge, item_id_aus_url
from .wissen import lade_wissen


def _gemeinsame_optionen(p: argparse.ArgumentParser) -> None:
    p.add_argument("--domain", choices=sorted(DOMAINS), help="Vinted-Land (Standard: de)")
    p.add_argument("--goldpreis", type=float, help="Goldkurs in €/g Feingold (Standard: 110 oder VH_GOLDPREIS)")
    p.add_argument("--verzoegerung", type=float, help="Pause zwischen Vinted-Anfragen in Sekunden (Standard: 2)")
    p.add_argument("--ohne-ablage", action="store_true", help="Keine SQLite-Datenbank verwenden")
    p.add_argument("-v", "--verbose", action="store_true", help="Ausführliche Protokollausgabe")


def _ki_optionen(p: argparse.ArgumentParser) -> None:
    p.add_argument("--ki", action="store_true", help="Fotos + Text mit Claude nach der Grundprompt prüfen (API-Schlüssel nötig)")
    p.add_argument("--recherche", action="store_true", help="Zusätzlich externe Vergleichsstücke per Websuche suchen (Abschnitt 12)")
    p.add_argument("--modell", help="Claude-Modell (Standard: claude-opus-5 oder VH_MODELL)")


def baue_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vinted_hunter",
        description="Vinted Treasure Hunter – sucht Fehlbewertungen bei Vintage- und Designer-Schmuck.",
    )
    sub = parser.add_subparsers(dest="befehl", required=True)

    j = sub.add_parser("jagd", help="Vollständiger Suchlauf über die Richtungen A–G")
    _gemeinsame_optionen(j)
    _ki_optionen(j)
    j.add_argument("--richtungen", default=ALLE_RICHTUNGEN, help="Suchrichtungen, z. B. ABF (Standard: ABCDEFG)")
    j.add_argument("--max-anfragen", type=int, default=40, help="Maximale Anzahl Suchanfragen (Standard: 40)")
    j.add_argument("--keine-rotation", action="store_true", help="Immer dieselben Anfragen statt Tagesrotation")
    j.add_argument("--seiten", type=int, default=1, help="Ergebnisseiten pro Anfrage (Standard: 1 = 96 Anzeigen)")
    j.add_argument("--max-preis", type=float, default=150, help="Preisobergrenze in € (Standard: 150, 0 = keine)")
    j.add_argument("--katalog-ids", default="", help="Kommagetrennte Vinted-Katalog-IDs (siehe Befehl 'kataloge')")
    j.add_argument("--details", type=int, default=40, help="Für wie viele Anzeigen Beschreibung/Fotos geladen werden (Standard: 40)")
    j.add_argument("--ki-triage", type=int, default=25, help="Max. Anzeigen für die KI-Erstsichtung (Standard: 25)")
    j.add_argument("--ki-tief", type=int, default=8, help="Max. Anzeigen für die KI-Tiefenprüfung (Standard: 8)")
    j.add_argument("--visuell", type=int, default=8, help="Max. 'unauffällige' Anzeigen aus Richtung G für die Bildprüfung (Standard: 8)")
    j.add_argument("--nur-neue", action="store_true", help="Nur neue oder im Preis gesenkte Anzeigen berichten")
    j.add_argument("--auch-interessant", action="store_true", help="Auch 🔥-Funde anzeigen (Standard: nur 🔥🔥🔥 und 🔥🔥)")
    j.add_argument("--chat-export", action="store_true", help="Zusätzlich Kandidatenliste zum Einfügen in einen Claude-Chat")
    j.add_argument("--bilder", action="store_true", help="Fotos der Kandidaten nach daten/bilder/<id>/ laden")

    a = sub.add_parser("anfragen", help="Erzeugte Suchanfragen anzeigen (ohne Vinted aufzurufen)")
    a.add_argument("--domain", choices=sorted(DOMAINS), default="de")
    a.add_argument("--richtungen", default=ALLE_RICHTUNGEN)
    a.add_argument("--max-anfragen", type=int)
    a.add_argument("--rotation", action="store_true")

    p = sub.add_parser("pruefe", help="Eine einzelne Anzeige (URL oder ID) prüfen")
    p.add_argument("anzeige", help="Vinted-Link oder Artikel-ID")
    _gemeinsame_optionen(p)
    _ki_optionen(p)

    d = sub.add_parser("datei", help="Anzeigen aus einer JSON-Datei bewerten (offline)")
    d.add_argument("pfad", type=Path)
    _gemeinsame_optionen(d)
    _ki_optionen(d)
    d.add_argument("--auch-interessant", action="store_true")
    d.add_argument("--chat-export", action="store_true")

    k = sub.add_parser("kataloge", help="Schmuck-Katalog-IDs von Vinted auflisten")
    k.add_argument("--domain", choices=sorted(DOMAINS), default="de")
    return parser


def _einstellungen(args: argparse.Namespace) -> Einstellungen:
    e = Einstellungen()
    if getattr(args, "domain", None):
        e.domain = args.domain
    if getattr(args, "goldpreis", None):
        e.goldpreis_eur_g = args.goldpreis
    if getattr(args, "verzoegerung", None) is not None:
        e.verzoegerung_s = args.verzoegerung
    if getattr(args, "modell", None):
        e.modell = args.modell
    return e


def _ablage(args: argparse.Namespace, e: Einstellungen) -> Ablage | None:
    return None if getattr(args, "ohne_ablage", False) else Ablage(e.db_pfad)


def befehl_jagd(args: argparse.Namespace) -> int:
    e = _einstellungen(args)
    e.max_anfragen = args.max_anfragen
    e.seiten_pro_anfrage = max(1, args.seiten)
    e.max_preis = args.max_preis or None
    e.katalog_ids = [int(x) for x in args.katalog_ids.split(",") if x.strip()]
    e.triage_anzahl = args.ki_triage
    e.tiefen_anzahl = args.ki_tief
    o = JagdOptionen(
        richtungen=args.richtungen.upper(),
        rotation=not args.keine_rotation,
        details_top=args.details,
        visuell_top=args.visuell,
        ki=args.ki,
        recherche=args.recherche,
        nur_neue=args.nur_neue,
        bilder_export=args.bilder,
    )
    ablage = _ablage(args, e)
    jagd = Jagd(e, o, ablage=ablage)
    try:
        funde = jagd.lauf()
    except VintedFehler as err:
        print(f"Fehler: {err}", file=sys.stderr)
        return 2
    finally:
        if ablage:
            ablage.schliessen()
    pfade = speichere_berichte(funde, jagd.stat, e.berichte_dir, args.auch_interessant, args.chat_export)
    print(erstelle_bericht(funde, jagd.stat, args.auch_interessant))
    print(f"Bericht gespeichert: {pfade['markdown']}", file=sys.stderr)
    if "chat" in pfade:
        print(f"Chat-Export: {pfade['chat']}", file=sys.stderr)
    if jagd.stat.eindeutig == 0 and jagd.stat.fehler:
        print("Keine Anzeigen geladen – Vinted war nicht erreichbar (siehe README: 'Wenn Vinted blockiert').", file=sys.stderr)
        return 2
    return 0


def befehl_anfragen(args: argparse.Namespace) -> int:
    e = Einstellungen(domain=args.domain)
    gen = Suchgenerator(lade_wissen(), e.sprache)
    anfragen = gen.erzeuge(args.richtungen, args.max_anfragen, rotation=args.rotation)
    for q in anfragen:
        print(f"[{q.richtung}] {q.text:40s}  – {q.grund}")
    print(f"\n{len(anfragen)} Anfragen", file=sys.stderr)
    return 0


def befehl_pruefe(args: argparse.Namespace) -> int:
    e = _einstellungen(args)
    if not args.domain:
        e.domain = domain_aus_url(args.anzeige, e.domain)
    ablage = _ablage(args, e)
    jagd = Jagd(e, JagdOptionen(ki=args.ki), ablage=ablage)
    try:
        anzeige = jagd.client.details(item_id_aus_url(args.anzeige))
    except (VintedFehler, ValueError) as err:
        print(f"Fehler: {err}", file=sys.stderr)
        return 2
    if anzeige is None:
        print("Anzeige nicht gefunden.", file=sys.stderr)
        return 1
    fund = jagd.pruefe_einzeln(anzeige, recherche=args.recherche)
    if ablage:
        ablage.schliessen()
    if fund.vorbewertung.ausgeschlossen and not fund.analyse:
        print(f"❌ Aussortiert: {fund.vorbewertung.ausschlussgrund}")
    print(fund_markdown(fund))
    if jagd.stat.ki_verbrauch:
        print(f"KI: {jagd.stat.ki_verbrauch}", file=sys.stderr)
    return 0


def befehl_datei(args: argparse.Namespace) -> int:
    e = _einstellungen(args)
    anzeigen = lade_anzeigen_datei(args.pfad, e.domain)
    ablage = _ablage(args, e)
    jagd = Jagd(e, JagdOptionen(ki=args.ki, recherche=args.recherche), ablage=ablage)
    jagd.stat.eindeutig = len(anzeigen)
    funde = jagd.ablegen(jagd.vorfiltern(anzeigen))
    if args.ki:
        jagd.ki_pruefen(funde)
    if ablage:
        ablage.schliessen()
    pfade = speichere_berichte(funde, jagd.stat, e.berichte_dir, args.auch_interessant, args.chat_export)
    print(erstelle_bericht(funde, jagd.stat, args.auch_interessant))
    print(f"Bericht gespeichert: {pfade['markdown']}", file=sys.stderr)
    return 0


def befehl_kataloge(args: argparse.Namespace) -> int:
    try:
        kataloge = VintedClient(args.domain).kataloge()
    except VintedFehler as err:
        print(f"Fehler: {err}", file=sys.stderr)
        return 2
    treffer = finde_schmuck_kataloge(kataloge)
    for kid, pfad in treffer:
        print(f"{kid:>8}  {pfad}")
    if treffer:
        print(f"\nBeispiel: --katalog-ids {','.join(str(k) for k, _ in treffer[:3])}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = baue_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if getattr(args, "verbose", False) else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    befehle = {"jagd": befehl_jagd, "anfragen": befehl_anfragen, "pruefe": befehl_pruefe, "datei": befehl_datei, "kataloge": befehl_kataloge}
    return befehle[args.befehl](args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
