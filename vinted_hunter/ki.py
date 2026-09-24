"""Bild- und Textanalyse mit Claude nach der Grundprompt.

Zweistufig, damit die Kosten im Rahmen bleiben:

1. TRIAGE       – wenige Fotos, niedriger Denkaufwand: lohnt sich ein genauer Blick?
2. TIEFENPRÜFUNG – alle Fotos, hoher Denkaufwand, vollständiges Ausgabeformat
   (Abschnitt 18), optional mit externer Vergleichsrecherche (Abschnitt 12).

Die Grundprompt steht unverändert als System-Prompt (mit Prompt-Caching), der
Modus steht in der Nutzernachricht.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from .einstellungen import ANALYSE_DATEI, PROMPT_DATEI, Einstellungen
from .heuristik import GOLD_BESCHREIBUNG, PRIO_SYMBOL, Vorbewertung
from .modelle import Anzeige

log = logging.getLogger(__name__)

PRIORITAETEN = ["JACKPOT", "SEHR_INTERESSANT", "INTERESSANT", "NICHT_INTERESSANT"]
EVIDENZ = ["IDENTIFIZIERT", "SEHR_WAHRSCHEINLICH", "PLAUSIBEL", "VERDACHT", "KEIN_HINWEIS"]

# Modelle, die den serverseitigen Refusal-Fallback ("default") unterstützen
_FALLBACK_MODELLE = {"claude-opus-5", "claude-fable-5-1"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Richtpreise in USD pro Mio. Tokens (Eingabe, Ausgabe) für die Kostenanzeige
_PREISE = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-fable-5-1": (10.0, 50.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or list(props), "additionalProperties": False}


_STR = {"type": "string"}
_ZAHL = {"type": "number"}

TRIAGE_SCHEMA = _obj(
    {
        "vertiefen": {"type": "boolean"},
        "prioritaet": {"type": "string", "enum": PRIORITAETEN},
        "hypothese": _STR,
        "begruendung": _STR,
        "wichtigstes_fehlendes_foto": _STR,
    }
)

TIEF_SCHEMA = _obj(
    {
        "prioritaet": {"type": "string", "enum": PRIORITAETEN},
        "artikel": _STR,
        "was_der_verkaeufer_glaubt": _STR,
        "was_verdaechtig_ist": {"type": "array", "items": _STR},
        "goldverdacht": _obj({"stufe": {"type": "string", "enum": EVIDENZ}, "begruendung": _STR}),
        "designerverdacht": _obj({"stufe": {"type": "string", "enum": EVIDENZ}, "kandidat": _STR, "begruendung": _STR}),
        "historische_einordnung": _STR,
        "warum_uebersehen": _STR,
        "nicht_gezeigt": {"type": "array", "items": _STR},
        "gelesene_punzen": {
            "type": "array",
            "items": _obj({"text": _STR, "foto_nr": {"type": "integer"}, "stufe": {"type": "string", "enum": EVIDENZ}}),
        },
        "einzelstuecke": {
            "type": "array",
            "items": _obj({"beschreibung": _STR, "auffaelligkeit": _STR, "prioritaet": {"type": "string", "enum": PRIORITAETEN}}),
        },
        "wiederverkauf_min_eur": _ZAHL,
        "wiederverkauf_max_eur": _ZAHL,
        "haendlerpreis": _STR,
        "auktionspreis": _STR,
        "risiko": {"type": "string", "enum": ["niedrig", "mittel", "hoch"]},
        "urteil": {"type": "string", "enum": ["KAUFEN", "NUR_WENN_PREIS", "NICHT_KAUFEN"]},
        "max_preis_eur": _ZAHL,
        "wichtigstes_fehlendes_foto": _STR,
        "begruendung_ein_satz": _STR,
    }
)


class KIFehler(RuntimeError):
    pass


@dataclass
class Verbrauch:
    eingabe: int = 0
    ausgabe: int = 0
    cache_gelesen: int = 0
    cache_geschrieben: int = 0
    anfragen: int = 0

    def addiere(self, usage: Any) -> None:
        self.anfragen += 1
        self.eingabe += getattr(usage, "input_tokens", 0) or 0
        self.ausgabe += getattr(usage, "output_tokens", 0) or 0
        self.cache_gelesen += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_geschrieben += getattr(usage, "cache_creation_input_tokens", 0) or 0

    def kosten_usd(self, modell: str) -> float | None:
        preis = _PREISE.get(modell)
        if not preis:
            return None
        ein, aus = preis
        return (
            self.eingabe * ein + self.cache_geschrieben * ein * 1.25 + self.cache_gelesen * ein * 0.1 + self.ausgabe * aus
        ) / 1_000_000

    def zusammenfassung(self, modell: str) -> str:
        k = self.kosten_usd(modell)
        kosten = f", ca. {k:.2f} USD" if k is not None else ""
        return (
            f"{self.anfragen} KI-Anfragen, {self.eingabe + self.cache_gelesen + self.cache_geschrieben:,} Eingabe-Tokens "
            f"(davon {self.cache_gelesen:,} aus Cache), {self.ausgabe:,} Ausgabe-Tokens{kosten}"
        ).replace(",", ".")


def lade_system_prompt() -> str:
    grund = PROMPT_DATEI.read_text(encoding="utf-8").strip()
    auftrag = ANALYSE_DATEI.read_text(encoding="utf-8").strip() if ANALYSE_DATEI.exists() else ""
    return f"{grund}\n\n{auftrag}".strip()


def anzeige_als_text(a: Anzeige, v: Vorbewertung | None) -> str:
    preis = f"{a.preis:.2f} {a.waehrung}" if a.preis is not None else "unbekannt"
    gesamt = f" (inkl. Käuferschutz {a.gesamtpreis:.2f} {a.waehrung})" if a.gesamtpreis else ""
    zeilen = [
        "ANZEIGE",
        f"Titel: {a.titel}",
        f"Preis: {preis}{gesamt}",
        f"Markenfeld: {a.marke or '—'}",
        f"Kategorie: {a.katalog_name or '—'}",
        f"Zustand: {a.zustand or '—'}",
        f"Anzahl Fotos in der Anzeige: {len(a.fotos)}",
        f"Link: {a.url}",
        "Beschreibung:",
        (a.beschreibung or "—").strip(),
    ]
    if v is not None:
        zeilen += [
            "",
            "AUTOMATISCHER TEXT-VORFILTER (Stichwortheuristik ohne Bildverständnis, kann irren):",
            f"Vorfilter-Priorität: {PRIO_SYMBOL[v.prioritaet]} ({v.punkte}/100)",
            f"Erkannte Schmuckart: {v.kategorie}",
            f"Goldstatus laut Text: {GOLD_BESCHREIBUNG[v.goldstatus]}",
        ]
        if v.gewicht_g:
            zeilen.append(f"Gewicht laut Text: {v.gewicht_g:g} g")
        for titel, liste in (("Indizien", v.indizien), ("Asymmetrie-Signale", v.asymmetrie), ("Informationslücken", v.info_luecken), ("Warnungen", v.warnungen)):
            if liste:
                zeilen.append(f"{titel}:")
                zeilen += [f"- {x}" for x in liste]
    return "\n".join(zeilen)


FotoLader = Callable[[str], "tuple[bytes, str] | None"]


@dataclass
class ClaudeAnalyst:
    einstellungen: Einstellungen
    foto_lader: FotoLader | None = None
    client: Any = None
    fallbacks: bool = True
    verbrauch: Verbrauch = field(default_factory=Verbrauch)
    _system: str | None = None

    def __post_init__(self) -> None:
        if self.client is None:
            try:
                import anthropic
            except ImportError as e:  # pragma: no cover - abhängig von der Installation
                raise KIFehler("Paket 'anthropic' fehlt: pip install anthropic") from e
            self.client = anthropic.Anthropic()

    @property
    def modell(self) -> str:
        return self.einstellungen.modell

    @property
    def system(self) -> str:
        if self._system is None:
            self._system = lade_system_prompt()
        return self._system

    # ------------------------------------------------------------ Bausteine
    def _foto_bloecke(self, fotos: list[str], max_anzahl: int) -> list[dict]:
        bloecke: list[dict] = []
        for i, url in enumerate(fotos[:max_anzahl], start=1):
            bloecke.append({"type": "text", "text": f"Foto {i}:"})
            geladen = self.foto_lader(url) if self.foto_lader else None
            if geladen:
                daten, mime = geladen
                quelle = {"type": "base64", "media_type": mime, "data": base64.standard_b64encode(daten).decode("ascii")}
            else:
                quelle = {"type": "url", "url": url}
            bloecke.append({"type": "image", "source": quelle})
        return bloecke

    def _parameter(self, inhalt: list[dict], schema: dict | None, effort: str, max_tokens: int, tools: list | None = None) -> dict:
        p: dict[str, Any] = {
            "model": self.modell,
            "max_tokens": max_tokens,
            "system": [{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": inhalt}],
        }
        output_config: dict[str, Any] = {}
        if "haiku" not in self.modell:
            p["thinking"] = {"type": "adaptive"}
            output_config["effort"] = effort
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        if output_config:
            p["output_config"] = output_config
        if tools:
            p["tools"] = tools
        if self.fallbacks and self.modell in _FALLBACK_MODELLE:
            p["betas"] = [_FALLBACK_BETA]
            p["fallbacks"] = "default"
        return p

    def _sende(self, params: dict) -> Any:
        import anthropic

        try:
            if "betas" in params:
                antwort = self.client.beta.messages.create(**params)
            else:
                antwort = self.client.messages.create(**params)
        except anthropic.BadRequestError as e:
            raise KIFehler(f"Ungültige Anfrage an Claude: {e.message}") from e
        except anthropic.AuthenticationError as e:
            raise KIFehler("Kein gültiger API-Schlüssel (ANTHROPIC_API_KEY setzen oder `ant auth login`).") from e
        except anthropic.RateLimitError as e:
            raise KIFehler("Rate-Limit erreicht – später erneut versuchen oder --ki-top verkleinern.") from e
        except anthropic.APIStatusError as e:
            raise KIFehler(f"Claude-API-Fehler {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise KIFehler("Keine Verbindung zur Claude-API.") from e
        self.verbrauch.addiere(antwort.usage)
        return antwort

    @staticmethod
    def _json_aus(antwort: Any) -> dict:
        if antwort.stop_reason == "refusal":
            details = getattr(antwort, "stop_details", None)
            grund = getattr(details, "explanation", None) or "ohne Begründung"
            raise KIFehler(f"Claude hat die Analyse abgelehnt ({grund})")
        if antwort.stop_reason == "max_tokens":
            raise KIFehler("Antwort abgeschnitten (max_tokens erreicht)")
        text = next((b.text for b in antwort.content if getattr(b, "type", "") == "text"), None)
        if not text:
            raise KIFehler("Keine Textantwort erhalten")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise KIFehler(f"Antwort ist kein gültiges JSON: {text[:200]}") from e

    # ------------------------------------------------------------ Stufen
    def triage(self, a: Anzeige, v: Vorbewertung | None) -> dict:
        inhalt = self._foto_bloecke(a.fotos, self.einstellungen.max_fotos_triage)
        inhalt.append({"type": "text", "text": anzeige_als_text(a, v) + "\n\nMODUS: TRIAGE"})
        antwort = self._sende(self._parameter(inhalt, TRIAGE_SCHEMA, effort="low", max_tokens=4000))
        return self._json_aus(antwort)

    def recherche(self, a: Anzeige, hypothese: str) -> str:
        """Abschnitt 12: externe Vergleichsstücke per Websuche (separater Schritt)."""
        auftrag = (
            "Recherchiere Vergleichsstücke für diese Vinted-Anzeige. Suche nach dem IDENTISCHEN Modell oder der "
            "IDENTISCHEN Designfamilie – nicht nach 'ähnlichem Schmuck'. Bevorzugt: abgeschlossene Auktionen, seriöse "
            "Händler, Herstellerarchive, Museumssammlungen. Aktuelle Vinted-Angebote nur ergänzend.\n"
            "Gib 3–6 Vergleiche als Liste: Objekt, Preis (Euro), Datum, Quelle (URL), Ähnlichkeitsgrad "
            "(identisch/gleiche Familie/nur ähnlich). Schreibe ausdrücklich, wenn nichts Belastbares zu finden ist.\n\n"
            f"Arbeitshypothese: {hypothese}\n\n{anzeige_als_text(a, None)}\n\nMODUS: RECHERCHE (Freitext, kein JSON)"
        )
        inhalt = self._foto_bloecke(a.fotos, 2) + [{"type": "text", "text": auftrag}]
        params = self._parameter(inhalt, None, effort="medium", max_tokens=8000,
                                 tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 6}])
        antwort = self._sende(params)
        texte = [b.text for b in antwort.content if getattr(b, "type", "") == "text"]
        # Serverseitige Suche kann pausieren – dann denselben Zug ohne neue Nutzernachricht fortsetzen
        for _ in range(3):
            if antwort.stop_reason != "pause_turn":
                break
            params["messages"] = params["messages"][:1] + [{"role": "assistant", "content": antwort.content}]
            antwort = self._sende(params)
            texte += [b.text for b in antwort.content if getattr(b, "type", "") == "text" and b.text not in texte]
        return "\n".join(texte).strip()

    def tiefenpruefung(self, a: Anzeige, v: Vorbewertung | None, recherche: str | None = None, triage: dict | None = None) -> dict:
        inhalt = self._foto_bloecke(a.fotos, self.einstellungen.max_fotos_tief)
        text = anzeige_als_text(a, v)
        if triage:
            text += f"\n\nERSTSICHTUNG (Triage): {triage.get('hypothese', '')} – {triage.get('begruendung', '')}"
        if recherche:
            text += f"\n\nVERGLEICHSRECHERCHE (ungeprüft):\n{recherche}"
        inhalt.append({"type": "text", "text": text + "\n\nMODUS: TIEFENPRÜFUNG"})
        antwort = self._sende(self._parameter(inhalt, TIEF_SCHEMA, effort="high", max_tokens=16000))
        return self._json_aus(antwort)
