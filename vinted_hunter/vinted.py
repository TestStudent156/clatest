"""Schlanker Client für die (inoffizielle) Vinted-Web-API.

Vinted hat keine öffentliche API. Dieser Client nutzt dieselben Endpunkte wie
die Website und verhält sich bewusst zurückhaltend (Pausen, Backoff bei 429).
Wenn Vinted Anfragen blockiert (403/Captcha), kann ein Cookie aus dem eigenen
Browser über die Umgebungsvariable ``VINTED_COOKIE`` übergeben werden.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from html import unescape
from typing import Any, Iterable

from .einstellungen import DOMAINS
from .modelle import Anzeige

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
_ACCEPT_LANGUAGE = {"de": "de-DE,de;q=0.9", "at": "de-AT,de;q=0.9", "fr": "fr-FR,fr;q=0.9", "it": "it-IT,it;q=0.9", "nl": "nl-NL,nl;q=0.9"}


class VintedFehler(RuntimeError):
    pass


def _neue_session():
    """curl_cffi imitiert einen echten Browser-TLS-Fingerabdruck (hilft gegen Bot-Sperren)."""
    try:
        from curl_cffi import requests as cffi_requests  # type: ignore

        return cffi_requests.Session(impersonate="chrome"), True
    except ImportError:
        import requests

        return requests.Session(), False


def _betrag(wert: Any) -> float | None:
    if wert is None:
        return None
    if isinstance(wert, dict):
        wert = wert.get("amount")
    try:
        return float(str(wert).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _foto_urls(roh: dict, gross: bool = False) -> list[str]:
    fotos = roh.get("photos") or ([roh["photo"]] if roh.get("photo") else [])
    urls = []
    for f in fotos:
        if not isinstance(f, dict):
            continue
        url = (f.get("full_size_url") if gross else None) or f.get("url") or f.get("full_size_url")
        if url:
            urls.append(url)
    return urls


def anzeige_aus_api(roh: dict, domain: str = "de", details: bool = False) -> Anzeige:
    """Wandelt ein Vinted-API-Objekt (Suche oder Detail) in eine Anzeige um."""
    host = DOMAINS.get(domain, f"www.vinted.{domain}")
    item_id = str(roh.get("id", ""))
    url = roh.get("url") or f"https://{host}/items/{item_id}"
    if url.startswith("/"):
        url = f"https://{host}{url}"
    user = roh.get("user") or {}
    katalog = roh.get("catalog") or {}
    zeit = ""
    foto = roh.get("photo") or {}
    if isinstance(foto, dict) and isinstance(foto.get("high_resolution"), dict):
        ts = foto["high_resolution"].get("timestamp")
        if ts:
            zeit = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(int(ts)))
    preis_roh = roh.get("price")
    waehrung = preis_roh.get("currency_code", "EUR") if isinstance(preis_roh, dict) else (roh.get("currency") or "EUR")
    marke = roh.get("brand_title") or ""
    marke_obj = roh.get("brand_dto") or roh.get("brand")
    if not marke and isinstance(marke_obj, dict):
        marke = marke_obj.get("title", "")
    return Anzeige(
        id=item_id,
        titel=roh.get("title") or "",
        preis=_betrag(preis_roh),
        waehrung=waehrung,
        gesamtpreis=_betrag(roh.get("total_item_price")),
        url=url,
        beschreibung=roh.get("description") or "",
        marke=marke,
        zustand=roh.get("status") or "",
        groesse=roh.get("size_title") or "",
        katalog_id=roh.get("catalog_id") or (katalog.get("id") if isinstance(katalog, dict) else None),
        katalog_name=katalog.get("title", "") if isinstance(katalog, dict) else "",
        fotos=_foto_urls(roh, gross=details),
        verkaeufer=user.get("login", "") if isinstance(user, dict) else "",
        favoriten=roh.get("favourite_count"),
        aufrufe=roh.get("view_count"),
        erstellt=zeit,
        domain=domain,
        details_geladen=details,
    )


def anzeige_aus_html(html: str, url: str, domain: str = "de") -> Anzeige | None:
    """Notfall-Parser: liest JSON-LD (schema.org/Product) aus der Artikelseite."""
    for block in re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        try:
            daten = json.loads(unescape(block))
        except json.JSONDecodeError:
            continue
        for d in daten if isinstance(daten, list) else [daten]:
            if not isinstance(d, dict) or d.get("@type") != "Product":
                continue
            angebot = d.get("offers") or {}
            if isinstance(angebot, list):
                angebot = angebot[0] if angebot else {}
            bilder = d.get("image") or []
            if isinstance(bilder, str):
                bilder = [bilder]
            marke = d.get("brand")
            m = re.search(r"/items/(\d+)", url)
            return Anzeige(
                id=m.group(1) if m else url,
                titel=d.get("name", ""),
                preis=_betrag(angebot.get("price")),
                waehrung=angebot.get("priceCurrency", "EUR"),
                url=url,
                beschreibung=d.get("description", ""),
                marke=marke.get("name", "") if isinstance(marke, dict) else (marke or ""),
                fotos=list(bilder),
                domain=domain,
                details_geladen=True,
            )
    return None


class VintedClient:
    def __init__(self, domain: str = "de", verzoegerung_s: float = 2.0, cookie: str | None = None):
        if domain not in DOMAINS:
            raise ValueError(f"Unbekannte Domain '{domain}'. Erlaubt: {', '.join(DOMAINS)}")
        self.domain = domain
        self.basis = f"https://{DOMAINS[domain]}"
        self.verzoegerung_s = verzoegerung_s
        self.session, self.browser_imitation = _neue_session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": _ACCEPT_LANGUAGE.get(domain, "en-GB,en;q=0.8"),
                "Referer": self.basis + "/",
            }
        )
        self._cookie_manuell = cookie or os.environ.get("VINTED_COOKIE")
        if self._cookie_manuell:
            self.session.headers["Cookie"] = self._cookie_manuell
        self._bereit = bool(self._cookie_manuell)
        self._letzte_anfrage = 0.0

    # ------------------------------------------------------------ Transport
    def _warte(self) -> None:
        pause = self.verzoegerung_s + random.uniform(0, self.verzoegerung_s / 2)
        rest = self._letzte_anfrage + pause - time.monotonic()
        if rest > 0:
            time.sleep(rest)
        self._letzte_anfrage = time.monotonic()

    def _http_get(self, url: str, **kwargs: Any) -> Any:
        """GET mit einheitlicher Fehlerbehandlung (requests und curl_cffi haben eigene Ausnahmen)."""
        try:
            return self.session.get(url, timeout=30, **kwargs)
        except Exception as e:
            raise VintedFehler(f"Netzwerkfehler bei {url}: {e}") from e

    def _starte_sitzung(self) -> None:
        """Holt die Session-Cookies (u. a. access_token_web) von der Startseite."""
        self._warte()
        antwort = self._http_get(self.basis + "/", headers={"Accept": "text/html"})
        if antwort.status_code >= 400:
            raise VintedFehler(
                f"Vinted-Startseite antwortet mit {antwort.status_code}. "
                "Tipp: Cookie aus dem Browser als VINTED_COOKIE setzen (siehe README)."
            )
        self._bereit = True

    def _get(self, pfad: str, params: dict | None = None, versuche: int = 4) -> Any:
        if not self._bereit:
            self._starte_sitzung()
        neu_angemeldet = False
        for versuch in range(versuche):
            self._warte()
            antwort = self._http_get(self.basis + pfad, params=params)
            code = antwort.status_code
            if code == 200:
                try:
                    return antwort.json()
                except ValueError as e:
                    raise VintedFehler(f"Keine JSON-Antwort von {pfad} (evtl. Captcha-Seite)") from e
            if code == 401 and not neu_angemeldet and not self._cookie_manuell:
                log.info("Session abgelaufen – hole neue Cookies")
                self.session.cookies.clear()
                self._starte_sitzung()
                neu_angemeldet = True
                continue
            if code in (429, 500, 502, 503, 504):
                warte = min(60, (2 ** versuch) * 5)
                log.warning("Vinted %s bei %s – warte %ss", code, pfad, warte)
                time.sleep(warte)
                continue
            if code == 404:
                return None
            raise VintedFehler(f"Vinted antwortet mit {code} auf {pfad}")
        raise VintedFehler(f"Vinted: zu viele Fehlversuche für {pfad}")

    # ------------------------------------------------------------ Endpunkte
    def suche(
        self,
        text: str,
        seite: int = 1,
        pro_seite: int = 96,
        preis_bis: float | None = None,
        preis_ab: float | None = None,
        katalog_ids: Iterable[int] = (),
        sortierung: str = "newest_first",
    ) -> list[Anzeige]:
        params: dict[str, Any] = {
            "search_text": text,
            "page": seite,
            "per_page": pro_seite,
            "order": sortierung,
            "currency": "EUR",
        }
        if preis_bis is not None:
            params["price_to"] = f"{preis_bis:g}"
        if preis_ab is not None:
            params["price_from"] = f"{preis_ab:g}"
        ids = list(katalog_ids)
        if ids:
            params["catalog_ids"] = ",".join(str(i) for i in ids)
        daten = self._get("/api/v2/catalog/items", params) or {}
        return [anzeige_aus_api(r, self.domain) for r in daten.get("items", []) if isinstance(r, dict)]

    def details(self, item_id: str) -> Anzeige | None:
        """Beschreibung und alle Fotos. Probiert mehrere Endpunkte und zuletzt die HTML-Seite."""
        for pfad in (f"/api/v2/items/{item_id}/details", f"/api/v2/items/{item_id}"):
            try:
                daten = self._get(pfad, versuche=2)
            except VintedFehler as e:
                log.debug("Detail-Endpunkt %s fehlgeschlagen: %s", pfad, e)
                continue
            if isinstance(daten, dict):
                roh = daten.get("item", daten)
                if isinstance(roh, dict) and roh.get("id"):
                    return anzeige_aus_api(roh, self.domain, details=True)
        return self.details_aus_html(f"{self.basis}/items/{item_id}")

    def details_aus_html(self, url: str) -> Anzeige | None:
        self._warte()
        antwort = self._http_get(url, headers={"Accept": "text/html"})
        if antwort.status_code != 200:
            return None
        return anzeige_aus_html(antwort.text, url, self.domain)

    def kataloge(self) -> list[dict]:
        daten = self._get("/api/v2/catalogs") or {}
        return daten.get("catalogs", [])

    def lade_foto(self, url: str) -> tuple[bytes, str] | None:
        """Lädt ein Foto (für die Bildanalyse). Gibt (Bytes, MIME-Typ) zurück."""
        self._warte()
        try:
            antwort = self._http_get(url, headers={"Accept": "image/*"})
        except VintedFehler as e:  # einzelne Fotos sind nicht fatal – dann bekommt Claude die URL
            log.warning("Foto nicht ladbar: %s", e)
            return None
        if antwort.status_code != 200:
            return None
        mime = antwort.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        if mime not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            mime = "image/jpeg"
        return antwort.content, mime


def item_id_aus_url(eingabe: str) -> str:
    m = re.search(r"/items/(\d+)", eingabe)
    if m:
        return m.group(1)
    if eingabe.isdigit():
        return eingabe
    raise ValueError(f"Keine Vinted-Artikel-ID in '{eingabe}' gefunden")


def domain_aus_url(eingabe: str, standard: str = "de") -> str:
    m = re.search(r"vinted\.(co\.uk|[a-z]{2})", eingabe)
    if not m:
        return standard
    return "uk" if m.group(1) == "co.uk" else m.group(1)


def finde_schmuck_kataloge(kataloge: list[dict], pfad: tuple[str, ...] = ()) -> list[tuple[int, str]]:
    """Durchsucht den Katalogbaum nach Schmuck-Kategorien (für --katalog-ids)."""
    treffer = []
    for k in kataloge:
        titel = k.get("title", "")
        neuer_pfad = pfad + (titel,)
        if re.search(r"schmuck|jewel|bijou|gioiell|sieraden|joyer", titel, re.I):
            treffer.append((k.get("id"), " > ".join(neuer_pfad)))
        treffer.extend(finde_schmuck_kataloge(k.get("catalogs") or [], neuer_pfad))
    return treffer
