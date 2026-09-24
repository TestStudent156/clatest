"""Vorfilter: sucht Diskrepanzen zwischen möglichem Wert und Verkäuferwissen.

Das ist KEINE Wertbestimmung. Der Vorfilter entscheidet nur, welche Anzeigen
genauer angesehen werden (per Bildanalyse oder von dir selbst). Er folgt der
Grundprompt:

* nicht nach Preis suchen, sondern nach Fehlern (Abschnitt 1)
* Goldverdacht auch ohne sichtbare Punze (Abschnitte 2/3)
* Negativsuche: Was fehlt in der Anzeige? (Abschnitte 10/21)
* Verkäuferformulierungen sind nur ein Asymmetrie-Signal, kein Wert (Abschnitt 9)
* harte Negativfilter (Abschnitt 16)
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from . import gold as goldmod
from .einstellungen import Einstellungen
from .modelle import Anzeige
from .text import damerau_levenshtein, endet_mit_begriff, finde, normalisiere, woerter
from .wissen import Marke, Wissen

PRIO_JACKPOT = "JACKPOT"
PRIO_SEHR = "SEHR_INTERESSANT"
PRIO_INTERESSANT = "INTERESSANT"
PRIO_NICHT = "NICHT_INTERESSANT"

PRIO_SYMBOL = {
    PRIO_JACKPOT: "🔥🔥🔥 JACKPOT",
    PRIO_SEHR: "🔥🔥 SEHR INTERESSANT",
    PRIO_INTERESSANT: "🔥 INTERESSANT",
    PRIO_NICHT: "❌ NICHT INTERESSANT",
}
PRIO_RANG = {PRIO_JACKPOT: 3, PRIO_SEHR: 2, PRIO_INTERESSANT: 1, PRIO_NICHT: 0}

GOLD_TEXT = "TEXT_BEHAUPTET"  # Feingehalt/Karat im Text (noch nicht belegt!)
GOLD_VERDACHT = "VERDACHT"
GOLD_PLATTIERT = "PLATTIERT"
GOLD_KEIN = "KEIN_HINWEIS"

GOLD_BESCHREIBUNG = {
    GOLD_TEXT: "🟡 PLAUSIBEL – Verkäufer nennt einen Feingehalt; Punze auf Fotos noch nicht belegt",
    GOLD_VERDACHT: "🟠 VERDACHT – indirekte Indizien, nicht ausreichend belegbar",
    GOLD_PLATTIERT: "🔴 laut Text vergoldet/Doublé – kein Massivgold behauptet",
    GOLD_KEIN: "🔴 KEIN AUSREICHENDER HINWEIS",
}

# Mindest-Wertpunkte, ab denen Asymmetrie-Signale und Informationslücken zählen.
# Darunter gilt: reine Optik / nur billig -> nie interessant (Abschnitt 16).
WERT_SCHWELLE = 12

# Häufige Wörter, die zufällig einem Markennamen ähneln (Fuzzy-Fehlalarme)
_FUZZY_STOPP = {"fahrer", "bulgaria", "carrier", "gartner", "haskel", "bouchet", "geller"}

_SCHMUCK_KATALOG_WOERTER = ("schmuck", "jewel", "bijou", "gioiell", "sieraad", "sieraden", "joya")
_VERGLEICH_VOR_MARKE = re.compile(r"(wie|ahnlich|a la|stil|style|look|kein|keine|nicht|inspiriert|art von)\s+$")
_NEGATION_VOR = re.compile(r"(nicht|kein|keine|no|not|non|pas)\s+$")

# Wörter, die "ring"/"kette" enthalten, aber keine Schmuckart meinen
_KATEGORIE_STOERER = re.compile(
    r"\b(gering\w*|hering\w*|string\w*|spring\w*|bring\w*|during|ringsum\w*|ringel\w*|federring\w*|"
    r"schlusselring\w*|dichtungsring\w*|sicherheitskett\w*|verlangerungskett\w*)\b"
)
# Farbangaben, in denen das Wort "Gold" nur die Farbe meint
_GOLD_ALS_FARBE = re.compile(
    r"(farbe\s*:?\s*gold\w*|gold\s*farb\w*|gold\s*ton\w*|gold\s*optik|gold\s*look|gold\s*colou?r\w*|"
    r"gold\s*tone|in gold\b(?!\s*(333|375|585|750))|couleur or|color oro)"
)
# "evtl. ist auch Gold dabei", "Gold? keine Ahnung", "ob das Gold ist, weiß ich nicht"
_GOLD_UNSICHER = re.compile(
    r"(evtl|eventuell|vielleicht|vermutlich|wahrscheinlich|moglicherweise|ob|keine ahnung ob)\b[^.!\n]{0,30}\bgold\b"
    r"|\bgold\b[^.!\n]{0,20}(\?|ungepruft|nicht gepruft|nicht getestet|unbekannt|weiss (ich )?nicht)"
)
_SILBER_ALS_FARBE = re.compile(r"silber\s*(farb\w*|ton\w*|optik)")
_KARAT_PLATTIERT = re.compile(
    r"((?<![0-9])(8|9|10|14|18|22|24|333|375|585|750)\s?(k|kt|karat|ct|er)?\s?(gold\s?)?(plated|vergoldet|filled|gf|plattiert|beschichtet|vermeil))"
    r"|((925|sterling|silber)\s?(\w+\s)?vergoldet)"
)


@dataclass
class Markentreffer:
    marke: str
    stufe: str
    art: str  # "genannt" | "markenfeld" | "tippfehler" | "vergleich"
    fundstelle: str
    hinweis: str = ""


@dataclass
class Vorbewertung:
    anzeige_id: str
    punkte: int = 0
    prioritaet: str = PRIO_NICHT
    ausgeschlossen: bool = False
    ausschlussgrund: str = ""
    kategorie: str = "sonstiges"
    wertpunkte: int = 0
    goldstatus: str = GOLD_KEIN
    feingehalte: list[str] = field(default_factory=list)
    feingehalt_max: float | None = None
    gewicht_g: float | None = None
    materialwert_eur: float | None = None
    wert_untergrenze_eur: float | None = None
    preis_verhaeltnis: float | None = None
    marken: list[Markentreffer] = field(default_factory=list)
    dna: list[str] = field(default_factory=list)
    epochen: list[str] = field(default_factory=list)
    indizien: list[str] = field(default_factory=list)
    asymmetrie: list[str] = field(default_factory=list)
    info_luecken: list[str] = field(default_factory=list)
    warnungen: list[str] = field(default_factory=list)
    verkaeufer_glaubt: str = ""
    wichtigstes_foto: str = ""
    nachricht_an_verkaeufer: str = ""
    visuell_kandidat: bool = False

    def als_dict(self) -> dict:
        return asdict(self)

    @property
    def symbol(self) -> str:
        return PRIO_SYMBOL[self.prioritaet]

    @property
    def echte_marken(self) -> list[Markentreffer]:
        return [m for m in self.marken if m.art != "vergleich"]


class Vorfilter:
    def __init__(self, wissen: Wissen, einstellungen: Einstellungen | None = None):
        self.w = wissen
        self.e = einstellungen or Einstellungen()
        self._fuzzy_aliase = self._baue_fuzzy_index(wissen.marken)
        self._marken_punkte = {m.name: m.punkte for m in wissen.marken}

    # ------------------------------------------------------------------ Marken
    @staticmethod
    def _baue_fuzzy_index(marken: tuple[Marke, ...]) -> list[tuple[str, int, Marke]]:
        index = []
        for m in marken:
            if m.stufe in ("massenware", "neutral"):
                continue
            for a in m.aliase:
                n = normalisiere(a)
                if len(n.replace(" ", "")) >= 7:
                    index.append((n, n.count(" ") + 1, m))
        return index

    def erkenne_marken(self, a: Anzeige, text_norm: str) -> list[Markentreffer]:
        treffer: dict[str, Markentreffer] = {}
        feld = normalisiere(a.marke)
        for m in self.w.marken:
            if feld and any(normalisiere(x) == feld for x in m.aliase):
                treffer[m.name] = Markentreffer(m.name, m.stufe, "markenfeld", a.marke, m.hinweis)
                continue
            gefunden = finde(text_norm, m.aliase)
            if gefunden:
                art = "vergleich" if self._ist_vergleich(text_norm, gefunden[0]) else "genannt"
                treffer[m.name] = Markentreffer(m.name, m.stufe, art, gefunden[0], m.hinweis)
                continue
            tipp = finde(text_norm, m.tippfehler)
            if tipp:
                treffer[m.name] = Markentreffer(m.name, m.stufe, "tippfehler", tipp[0], m.hinweis)
        # Unscharfe Suche nach unbekannten Tippfehlern (Distanz 1, nur lange Namen)
        wl = [w for w in woerter(text_norm) if len(w) >= 6 and w not in _FUZZY_STOPP]
        bigramme = [f"{x} {y}" for x, y in zip(wl, wl[1:])]
        for alias, n_woerter, m in self._fuzzy_aliase:
            if m.name in treffer:
                continue
            kandidaten = wl if n_woerter == 1 else bigramme
            for k in kandidaten:
                if k != alias and damerau_levenshtein(k, alias) == 1:
                    treffer[m.name] = Markentreffer(m.name, m.stufe, "tippfehler", k, m.hinweis)
                    break
        return list(treffer.values())

    @staticmethod
    def _ist_vergleich(text_norm: str, alias: str) -> bool:
        pos = text_norm.find(normalisiere(alias))
        if pos < 0:
            return False
        return bool(_VERGLEICH_VOR_MARKE.search(text_norm[max(0, pos - 25):pos]))

    # --------------------------------------------------------------- Kategorie
    def erkenne_kategorie(self, titel_norm: str, text_norm: str) -> str:
        kats: dict = self.w.wert("kategorien", standard={})
        reihenfolge = ["konvolut", "manschettenknoepfe", "ohrclips", "ohrringe", "brosche", "armreif", "armband", "kette", "anhaenger", "ring"]
        for quelle in (titel_norm, text_norm):
            quelle = _KATEGORIE_STOERER.sub(" ", quelle)
            for k in reihenfolge:
                begriffe = kats.get(k, [])
                if k == "konvolut":
                    if finde(quelle, begriffe) or re.search(r"\b\d{1,3}\s*(teile|stuck|stk|pieces|pcs)\b", quelle):
                        return k
                elif endet_mit_begriff(quelle, begriffe):
                    return k
        return "sonstiges"

    def ist_schmuck(self, a: Anzeige, text_norm: str) -> bool:
        if a.katalog_id is not None and a.katalog_id in self.e.katalog_ids:
            return True
        kat = normalisiere(a.katalog_name)
        if kat and any(w in kat for w in _SCHMUCK_KATALOG_WOERTER):
            return True
        return endet_mit_begriff(_KATEGORIE_STOERER.sub(" ", text_norm), self.w.liste("schmuck", "woerter"))

    @staticmethod
    def katalog_ist_fremd(a: Anzeige) -> bool:
        """Abschnitt 8: Schmuck in einer Nicht-Schmuck-Kategorie."""
        kat = normalisiere(a.katalog_name)
        return bool(kat) and not any(w in kat for w in _SCHMUCK_KATALOG_WOERTER)

    # ---------------------------------------------------------------- Bewertung
    def bewerte(self, a: Anzeige) -> Vorbewertung:
        w = self.w
        titel_norm = normalisiere(a.titel)
        text_roh = "\n".join(x for x in (a.titel, a.beschreibung, a.marke, a.katalog_name) if x)
        text_norm = normalisiere(text_roh)
        v = Vorbewertung(anzeige_id=a.id)

        if not self.ist_schmuck(a, text_norm):
            return self._raus(v, "kein Schmuck erkannt")

        v.kategorie = self.erkenne_kategorie(titel_norm, text_norm)
        v.marken = self.erkenne_marken(a, text_norm)
        marken = v.echte_marken

        # ---------------- harte Negativfilter (Abschnitt 16)
        massen = [m for m in marken if m.stufe == "massenware"]
        ist_konvolut = v.kategorie == "konvolut"
        if massen and not ist_konvolut:
            return self._raus(v, f"Massenware ({massen[0].marke})")
        if massen:
            # Abschnitt 14: In Konvoluten kann neben Massenware ein wertvolles Einzelstück liegen
            v.warnungen.append(f"Konvolut enthält Massenware ({', '.join(m.marke for m in massen)}) – nur Einzelstücke zählen")
        faelschung = finde(text_norm, w.liste("ausschluss", "faelschung"))
        if faelschung:
            return self._raus(v, f"Fälschung/Replik-Hinweis ('{faelschung[0]}')")
        for liste, grund in (("kinder", "Kinderschmuck"), ("sonstiges", "kein relevanter Schmuck")):
            t = finde(text_norm, w.liste("ausschluss", liste))
            if t:
                return self._raus(v, f"{grund} ('{t[0]}')")

        punkte = 0
        wert = 0

        # ---------------- Marken (Abschnitte 5/6)
        for m in marken:
            if m.stufe == "neutral":
                continue
            bonus = self._marken_punkte.get(m.marke, 0)
            if m.art == "tippfehler":
                bonus += 10
                v.asymmetrie.append(f"Falsch geschriebene Marke '{m.fundstelle}' → {m.marke} (weniger Käufer finden das)")
            wert += bonus
            v.indizien.append(f"Marke {m.marke} ({m.stufe}, {m.art}: '{m.fundstelle}')")
            if m.stufe == "luxus":
                v.warnungen.append(f"{m.marke}: Luxusmarke – bei Niedrigpreis ist eine Fälschung wahrscheinlicher als ein Preisfehler")
                if (a.einkaufspreis or 0) < 60:
                    punkte -= 10
        for m in v.marken:
            if m.art == "vergleich":
                v.warnungen.append(f"Marke nur als Vergleich/Negation genannt ('… {m.fundstelle}') – kein Markenstück behauptet")

        # ---------------- Design-DNA (Abschnitt 5)
        dna_gold = False
        for d in w.dna:
            if not (d.alle or d.eines):
                continue
            if d.alle and not all(finde(text_norm, [x]) for x in d.alle):
                continue
            if d.eines and not finde(text_norm, d.eines):
                continue
            if d.eines_zusatz and not finde(text_norm, d.eines_zusatz):
                continue
            v.dna.append(d.erinnert_an)
            wert += d.gewicht
            dna_gold = dna_gold or d.gold
        if v.dna:
            v.indizien.append("Formensprache erinnert an: " + "; ".join(v.dna[:3]))

        # ---------------- Gold (Abschnitte 2–4)
        text_ohne_farbe = _GOLD_ALS_FARBE.sub(" ", text_norm)
        gold_stark = finde(text_ohne_farbe, w.liste("gold", "stark"))
        gold_woerter = [g for g in finde(text_ohne_farbe, w.liste("gold", "woerter")) if g not in gold_stark]
        gold_unsicher = finde(text_norm, w.liste("gold", "unsicher"))
        if not gold_unsicher:
            m_unsicher = _GOLD_UNSICHER.search(_GOLD_ALS_FARBE.sub(" ", text_norm))
            if m_unsicher:
                gold_unsicher.append(m_unsicher.group(0).strip())
        plattiert = _ohne_negation(text_norm, finde(text_norm, w.liste("plattiert", "woerter")))
        plattiert += [r for r in w.liste("plattiert", "roh") if r in text_roh.lower()]
        farbe = finde(text_norm, w.liste("farbe", "woerter"))
        konstruktion = finde(text_norm, w.liste("konstruktion", "woerter"))
        angaben = goldmod.finde_feingehalte(text_norm, gold_erwaehnt=bool(gold_stark or gold_woerter or gold_unsicher))
        karat_plattiert = bool(_KARAT_PLATTIERT.search(text_norm))
        v.gewicht_g = goldmod.finde_gewicht(text_roh)

        if angaben and not karat_plattiert:
            v.goldstatus = GOLD_TEXT
            v.feingehalte = [g.text for g in angaben]
            v.feingehalt_max = max(g.feingehalt for g in angaben)
            if plattiert:
                wert += 16
                v.warnungen.append(f"Widerspruch: Feingehalt UND Plattierung ('{plattiert[0]}') im Text – Einzelteile prüfen")
            else:
                wert += 32
            v.indizien.append(f"Feingehalt im Text: {', '.join(v.feingehalte)} (Verkäuferangabe – Punze auf Foto prüfen)")
        elif plattiert or karat_plattiert:
            v.goldstatus = GOLD_PLATTIERT
            v.warnungen.append(f"Text nennt Plattierung/Doublé ('{plattiert[0] if plattiert else 'vergoldet'}') – kein Massivgold behauptet")
        else:
            if gold_stark:
                wert += 16
                v.indizien.append(f"Eindeutige Goldbehauptung ohne Feingehalt: {', '.join(gold_stark[:3])}")
            if gold_woerter:
                wert += 8
                v.indizien.append(f"Goldbegriff (kann auch Farbe meinen): {', '.join(gold_woerter[:3])}")
            if gold_unsicher:
                wert += 10
                v.asymmetrie.append(f"Verkäufer unsicher bzgl. Gold: {', '.join(gold_unsicher[:2])}")
            if gold_stark or gold_woerter or gold_unsicher or dna_gold:
                v.goldstatus = GOLD_VERDACHT

        if farbe and v.goldstatus in (GOLD_KEIN, GOLD_VERDACHT):
            if konstruktion or v.dna:
                v.goldstatus = GOLD_VERDACHT
                wert += 10
                v.asymmetrie.append(
                    f"Nur Farbangabe ('{farbe[0]}') trotz Goldschmiede-Konstruktion/Design – Verkäufer glaubt evtl. nicht an Gold"
                )
            else:
                v.asymmetrie.append(f"Farbangabe statt Material ('{farbe[0]}')")

        # ---------------- Konstruktion (Abschnitt 3)
        if konstruktion:
            k_gewicht = int(w.wert("konstruktion", "gewicht", standard=4))
            wert += min(k_gewicht * len(konstruktion), 16)
            v.indizien.append(f"Konstruktionsmerkmale: {', '.join(konstruktion[:5])}")

        # ---------------- Steine
        edel = finde(text_norm, w.liste("steine", "edel"))
        halb = finde(text_norm, w.liste("steine", "halbedel"))
        billig = finde(text_norm, w.liste("steine", "modern_billig"))
        if edel:
            wert += min(5 * len(edel), 10)
            v.indizien.append(f"Edelsteinangaben: {', '.join(edel[:3])} (unbelegt)")
        if halb:
            wert += min(2 * len(halb), 6)
            v.indizien.append(f"Farbsteine/Material: {', '.join(halb[:3])}")
        if billig:
            punkte -= min(3 * len(billig), 6)

        # ---------------- Punze / Signatur (Abschnitt 4)
        punze = finde(text_norm, w.liste("punze", "woerter"))
        unbekannt = finde(text_norm, w.liste("punze", "unbekannte_marke"))
        if punze:
            wert += 6
            v.indizien.append(f"Stempel/Signatur erwähnt: {', '.join(punze[:3])}")
        if unbekannt:
            wert += 6
            v.asymmetrie.append(f"Marke/Stempel vom Verkäufer nicht zugeordnet: '{unbekannt[0]}'")

        # ---------------- Epochen (Abschnitt 7)
        ep = w.begriffe.get("epochen", {})
        for schluessel, deckel in (("fruehe", 15), ("mitte", 12), ("jahrzehnte", 6), ("vage", 2)):
            gef = finde(text_norm, ep.get(schluessel, []))
            if gef:
                wert += min(int(ep.get(f"{schluessel}_gewicht", 1)) * len(gef), deckel)
                if schluessel != "vage":
                    v.epochen.extend(gef)
        if v.epochen:
            v.indizien.append(f"Stil/Epoche genannt: {', '.join(v.epochen[:3])} (nur mit Konstruktionsbeleg relevant)")

        region = finde(text_norm, w.liste("region", "woerter"))
        if region:
            wert += min(int(w.wert("region", "gewicht", standard=4)) * len(region), 8)
            v.indizien.append(f"Herkunftsangabe: {', '.join(region[:2])}")

        # ---------------- Silber ohne Besonderheit (Abschnitt 16)
        silber = finde(_SILBER_ALS_FARBE.sub(" ", text_norm), w.liste("silber", "woerter"))
        hat_designer = any(m.stufe in ("sammler", "goldschmied", "designer_modeschmuck", "luxus") for m in marken)
        if (
            silber
            and v.goldstatus in (GOLD_KEIN, GOLD_PLATTIERT)
            and not hat_designer
            and not v.dna
            and not finde(text_norm, ep.get("fruehe", []) + ep.get("mitte", []))
            and not region
        ):
            return self._raus(v, "gewöhnlicher Silberschmuck ohne Designer/Epoche")

        # ---------------- Materialausschluss (mit Ausnahme bei starken Signalen)
        material = finde(text_norm, w.liste("ausschluss", "material"))
        stark = v.goldstatus == GOLD_TEXT or any(m.stufe in ("sammler", "goldschmied") for m in marken)
        if material and not stark and not ist_konvolut:
            return self._raus(v, f"Material ohne Wertpotenzial ('{material[0]}')")

        imitat = finde(text_norm, w.liste("ausschluss", "perlenimitat"))
        if imitat:
            if wert < 15:
                return self._raus(v, f"gewöhnliches Perlenimitat ('{imitat[0]}')")
            punkte -= 15
            v.warnungen.append(f"Perlenimitat erwähnt ('{imitat[0]}')")
        look = finde(text_norm, w.liste("ausschluss", "look"))
        if look:
            punkte -= 8
            v.warnungen.append(f"Nur 'Look' beschrieben ('{look[0]}')")
        if finde(text_norm, w.liste("ausschluss", "neu_massenware")) and not hat_designer:
            punkte -= 6
            v.warnungen.append("Neuware ohne Marke – eher Massenware")

        # ---------------- Informationsasymmetrie (Abschnitt 9)
        ahnung = finde(text_norm, w.liste("ahnungslos", "woerter"))
        unsicher = finde(text_norm, w.liste("ahnungslos", "unsicher"))
        if ahnung:
            v.asymmetrie.append(f"Verkäuferformulierung: {', '.join(repr(x) for x in ahnung[:3])}")
        signale = len(ahnung) + (1 if unsicher else 0) + len(v.asymmetrie)
        if wert >= WERT_SCHWELLE:
            punkte += min(4 * signale, 16)
        else:
            punkte += min(2 * signale, 4)

        # ---------------- Negativsuche: Was fehlt? (Abschnitte 10/21)
        v.info_luecken = self._info_luecken(a, v, marken)
        if wert >= WERT_SCHWELLE:
            punkte += min(3 * len(v.info_luecken), 9)
        if self.katalog_ist_fremd(a):
            v.asymmetrie.append(f"Falsche Kategorie: '{a.katalog_name}' statt Schmuck (Abschnitt 8)")
            punkte += 6

        # ---------------- Konvolut (Abschnitt 14)
        if v.kategorie == "konvolut":
            if wert >= WERT_SCHWELLE:
                punkte += 5
                v.indizien.append("Konvolut mit Wertsignal – jedes Stück einzeln prüfen")
            else:
                punkte -= 5
                v.warnungen.append("Konvolut ohne konkretes Wertsignal – billig allein genügt nicht")

        # ---------------- Preis-Diskrepanz (Abschnitte 1 + 13)
        punkte += self._preisdiskrepanz(a, v, marken, wert)

        v.wertpunkte = wert
        v.punkte = max(0, min(100, punkte + wert))
        v.prioritaet = self._prioritaet(v, marken)
        v.visuell_kandidat = self._visuell_kandidat(a, v)
        v.verkaeufer_glaubt = self._verkaeufer_glaubt(a, farbe, ahnung)
        v.wichtigstes_foto = self._wichtigstes_foto(v)
        v.nachricht_an_verkaeufer = self._nachricht(v)
        return v

    # ------------------------------------------------------------------ Helfer
    @staticmethod
    def _raus(v: Vorbewertung, grund: str) -> Vorbewertung:
        v.ausgeschlossen = True
        v.ausschlussgrund = grund
        v.prioritaet = PRIO_NICHT
        return v

    @staticmethod
    def _info_luecken(a: Anzeige, v: Vorbewertung, marken: list[Markentreffer]) -> list[str]:
        l: list[str] = []
        if v.goldstatus in (GOLD_TEXT, GOLD_VERDACHT) and v.gewicht_g is None:
            l.append("kein Gewicht angegeben")
        if v.goldstatus == GOLD_VERDACHT:
            l.append("kein Feingehalt/keine Punze genannt")
        if len(a.fotos) <= 2:
            l.append(f"nur {len(a.fotos)} Foto(s) – Rückseite/Verschluss vermutlich nicht gezeigt")
        if len((a.beschreibung or "").strip()) < 60:
            l.append("sehr kurze Beschreibung")
        feld = normalisiere(a.marke)
        if (not feld or feld in ("ohne marke", "sonstige", "unbekannt", "andere", "no brand")) and (v.dna or v.epochen) and not marken:
            l.append("keine Marke angegeben, obwohl Stil/Design auffällt")
        return l

    def _preisdiskrepanz(self, a: Anzeige, v: Vorbewertung, marken: list[Markentreffer], wert: int) -> int:
        preis = a.einkaufspreis
        gp = self.e.goldpreis_eur_g
        untergrenze: float | None = None
        if v.goldstatus == GOLD_TEXT and v.feingehalt_max:
            if v.gewicht_g is not None:
                gewicht = v.gewicht_g
                v.materialwert_eur = goldmod.materialwert(gewicht, v.feingehalt_max, gp)
                v.indizien.append(
                    f"Materialwert bei {gewicht:g} g × {v.feingehalt_max:.3f} × {gp:g} €/g ≈ {v.materialwert_eur:.0f} € (Angaben ungeprüft)"
                )
            else:
                gewicht = float(self.w.wert("mindestgewicht_g", v.kategorie, standard=1.0))
            untergrenze = goldmod.ankaufswert(gewicht, v.feingehalt_max, gp)
        if untergrenze is None:
            stufen = {m.stufe for m in marken}
            if "sammler" in stufen:
                untergrenze = 60.0
            elif "goldschmied" in stufen:
                untergrenze = 80.0
            elif "designer_modeschmuck" in stufen:
                untergrenze = self.e.mindest_wiederverkauf_eur
        v.wert_untergrenze_eur = untergrenze
        if preis is None or preis <= 0:
            return 0
        if untergrenze is not None:
            v.preis_verhaeltnis = round(untergrenze / preis, 2)
            r = v.preis_verhaeltnis
            if r >= 4:
                return 25
            if r >= 3:
                return 20
            if r >= 2:
                return 12
            if r >= 1.3:
                return 6
            if r < 1:
                v.warnungen.append(f"Preis {preis:.0f} € liegt über der konservativen Untergrenze ({untergrenze:.0f} €)")
                return -12
            return 0
        if wert < WERT_SCHWELLE:
            return 0
        if preis <= 10:
            return 8
        if preis <= 20:
            return 6
        if preis <= 40:
            return 3
        if preis > 300:
            return -15
        if preis > 150:
            return -8
        return 0

    @staticmethod
    def _prioritaet(v: Vorbewertung, marken: list[Markentreffer]) -> str:
        if v.wertpunkte < WERT_SCHWELLE:
            return PRIO_NICHT
        # JACKPOT nur mit belastbarem Anker (Feingehaltsangabe oder Sammlermarke) UND deutlichem Preisfehler
        belastbar = v.goldstatus == GOLD_TEXT or any(m.stufe in ("sammler", "goldschmied") for m in marken)
        verhaeltnis = v.preis_verhaeltnis or 0
        if belastbar and ((verhaeltnis >= 3 and v.punkte >= 60) or (verhaeltnis >= 2 and v.punkte >= 75)):
            return PRIO_JACKPOT
        if v.punkte >= 55:
            return PRIO_SEHR
        if v.punkte >= 38:
            return PRIO_INTERESSANT
        return PRIO_NICHT

    @staticmethod
    def _visuell_kandidat(a: Anzeige, v: Vorbewertung) -> bool:
        """Richtung G: günstige Anzeigen mit Fotos, bei denen der Text nichts verrät."""
        preis = a.einkaufspreis or 0
        return (
            not v.ausgeschlossen
            and "G" in a.richtungen
            and bool(a.fotos)
            and 0 < preis <= 40
            and v.prioritaet == PRIO_NICHT
        )

    @staticmethod
    def _verkaeufer_glaubt(a: Anzeige, farbe: list[str], ahnung: list[str]) -> str:
        teile = [f"Titel: „{a.titel}“"]
        if a.marke:
            teile.append(f"Markenfeld: {a.marke}")
        if a.katalog_name:
            teile.append(f"Kategorie: {a.katalog_name}")
        if farbe:
            teile.append(f"beschreibt Farbe statt Material ('{farbe[0]}')")
        if ahnung:
            teile.append(f"eigene Einschätzung: '{ahnung[0]}'")
        return "; ".join(teile)

    def _wichtigstes_foto(self, v: Vorbewertung) -> str:
        foto = str(self.w.wert("punzen_orte", v.kategorie, standard="") or self.w.wert("punzen_orte", "sonstiges", standard=""))
        if v.goldstatus in (GOLD_TEXT, GOLD_VERDACHT) and v.gewicht_g is None:
            foto += " + Gewicht in Gramm (Fein-/Küchenwaage)"
        if any(m.stufe in ("sammler", "designer_modeschmuck", "luxus") for m in v.marken) or v.dna:
            foto += "; Signatur/Herstellermarke in Nahaufnahme"
        return foto

    def _nachricht(self, v: Vorbewertung) -> str:
        """Neutrale, ehrliche Nachfrage an den Verkäufer."""
        ort = str(self.w.wert("punzen_orte", v.kategorie, standard="der Rückseite"))
        text = (
            "Hallo! Das Stück gefällt mir. Könntest du bitte noch ein scharfes Nahfoto von "
            f"{_kurzer_ort(ort)} machen – falls dort Zahlen oder ein Stempel sind, gern ganz nah?"
        )
        if v.goldstatus in (GOLD_TEXT, GOLD_VERDACHT) and v.gewicht_g is None:
            text += " Und weißt du ungefähr, wie viel es wiegt?"
        return text + " Vielen Dank!"


def _kurzer_ort(ort: str) -> str:
    return ort.split(" – ")[0].split(";")[0]


def _ohne_negation(text_norm: str, treffer: list[str]) -> list[str]:
    """Entfernt Treffer wie 'nicht vergoldet' oder 'kein Doublé'."""
    rest = []
    for t in treffer:
        n = normalisiere(t)
        positionen = [m.start() for m in re.finditer(re.escape(n), text_norm)]
        if any(not _NEGATION_VOR.search(text_norm[max(0, p - 8):p]) for p in positionen) or not positionen:
            rest.append(t)
    return rest
