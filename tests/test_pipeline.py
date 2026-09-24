import json
from types import SimpleNamespace

import pytest
from conftest import FIXTURES, anzeige

from vinted_hunter.ablage import Ablage
from vinted_hunter.bericht import Fund, Laufstatistik, erstelle_bericht, erstelle_chat_export, speichere_berichte
from vinted_hunter.jagd import Jagd, JagdOptionen, lade_anzeigen_datei
from vinted_hunter.ki import TIEF_SCHEMA, TRIAGE_SCHEMA, ClaudeAnalyst, KIFehler, lade_system_prompt
from vinted_hunter.vinted import anzeige_aus_api, anzeige_aus_html, domain_aus_url, finde_schmuck_kataloge, item_id_aus_url


# ---------------------------------------------------------------- Vinted-Parsing
def test_api_parsing_preisformate(api_items):
    a = anzeige_aus_api(api_items[0], "de", details=True)
    assert a.id == "1000001" and a.preis == 12.0 and a.gesamtpreis == 13.3
    assert a.einkaufspreis == 13.3
    assert a.fotos == ["https://images1.vinted.net/f/ring-1.jpeg"]  # Details -> große Fotos
    assert a.katalog_name == "Schmuck"
    b = anzeige_aus_api(api_items[2], "de")
    assert b.preis == 18.0 and b.url == "https://www.vinted.de/items/1000003"
    assert b.fotos == ["https://images1.vinted.net/t/brosche.jpeg"]


def test_html_fallback():
    html = (
        '<html><script type="application/ld+json">{"@type":"Product","name":"Alte Brosche",'
        '"description":"Dachbodenfund","image":["https://x/1.jpg","https://x/2.jpg"],'
        '"offers":{"price":"7.50","priceCurrency":"EUR"},"brand":{"name":"Ohne Marke"}}</script></html>'
    )
    a = anzeige_aus_html(html, "https://www.vinted.de/items/42-alte-brosche")
    assert a.id == "42" and a.preis == 7.5 and len(a.fotos) == 2 and a.details_geladen


def test_url_helfer():
    assert item_id_aus_url("https://www.vinted.fr/items/123456-bague-or") == "123456"
    assert item_id_aus_url("987") == "987"
    assert domain_aus_url("https://www.vinted.co.uk/items/1") == "uk"
    assert domain_aus_url("https://www.vinted.it/items/1") == "it"
    with pytest.raises(ValueError):
        item_id_aus_url("keine id")


def test_katalogsuche():
    baum = [{"id": 1, "title": "Damen", "catalogs": [{"id": 21, "title": "Schmuck", "catalogs": [{"id": 163, "title": "Ringe"}]}]}]
    assert finde_schmuck_kataloge(baum) == [(21, "Damen > Schmuck")]


def test_datei_import_beide_formate(tmp_path):
    api = lade_anzeigen_datei(FIXTURES / "vinted_api_items.json")
    assert len(api) == 10 and api[0].titel.startswith("Alter Ring")
    eigen = tmp_path / "eigen.json"
    eigen.write_text(json.dumps([api[0].als_dict()]), encoding="utf-8")
    assert lade_anzeigen_datei(eigen)[0].id == api[0].id


# ---------------------------------------------------------------- Ablage
def test_ablage_preissenkung_und_reanalyse(tmp_path):
    ab = Ablage(tmp_path / "t.sqlite")
    a = anzeige("Goldring", 50, id="1")
    assert ab.speichere(a) == "neu"
    assert ab.speichere(a) == "bekannt"
    ab.speichere_analyse("1", {"prioritaet": "INTERESSANT"}, 50)
    assert not ab.braucht_analyse(a)
    a.preis = 30
    assert ab.speichere(a) == "preis_gesenkt"
    assert ab.braucht_analyse(a)
    assert [p for _, p in ab.preisverlauf("1")] == [50, 30]
    ab.schliessen()


# ---------------------------------------------------------------- Bericht
def _analyse(**kw):
    basis = {
        "prioritaet": "SEHR_INTERESSANT",
        "artikel": "Ring",
        "was_der_verkaeufer_glaubt": "Modeschmuck",
        "was_verdaechtig_ist": ["Krappenfassung"],
        "goldverdacht": {"stufe": "VERDACHT", "begruendung": "Farbe an Abriebstellen"},
        "designerverdacht": {"stufe": "KEIN_HINWEIS", "kandidat": "", "begruendung": "—"},
        "historische_einordnung": "1960er",
        "warum_uebersehen": "Punze nicht fotografiert",
        "nicht_gezeigt": ["Ringinnenseite"],
        "gelesene_punzen": [],
        "einzelstuecke": [],
        "wiederverkauf_min_eur": 60,
        "wiederverkauf_max_eur": 110,
        "haendlerpreis": "90 €",
        "auktionspreis": "70–100 €",
        "risiko": "mittel",
        "urteil": "NUR_WENN_PREIS",
        "max_preis_eur": 25,
        "wichtigstes_fehlendes_foto": "Ringinnenseite",
        "begruendung_ein_satz": "Interessanter Verdacht, aber noch kein Kauf.",
    }
    basis.update(kw)
    return basis


def test_bericht_zeigt_nur_hohe_prioritaeten(vorfilter, einstellungen):
    hoch = Fund(anzeige("Goldring 585", 45, "585 Gold 3,2 g Nachlass", fotos=3, id="a"), None)
    hoch.vorbewertung = vorfilter.bewerte(hoch.anzeige)
    niedrig = Fund(anzeige("Kette gold", 7, "Farbe: Gold", id="b"), None)
    niedrig.vorbewertung = vorfilter.bewerte(niedrig.anzeige)
    text = erstelle_bericht([hoch, niedrig], Laufstatistik(goldpreis=100))
    assert "Goldring 585" in text and "Kette gold" not in text
    assert "noch kein Kauf" in text  # ohne KI nie ein Kaufurteil
    assert "KAUFEN" not in text.replace("NICHT KAUFEN", "")


def test_bericht_mit_ki_analyse(vorfilter, tmp_path):
    f = Fund(anzeige("Ring goldfarben", 9, "Krappenfassung", id="c"), None)
    f.vorbewertung = vorfilter.bewerte(f.anzeige)
    f.analyse = _analyse()
    text = erstelle_bericht([f], Laufstatistik(goldpreis=100))
    assert "🔥🔥 SEHR INTERESSANT" in text
    assert "🟡 NUR WENN PREIS ≤ 25 €" in text
    assert "🟠 VERDACHT" in text
    pfade = speichere_berichte([f], Laufstatistik(goldpreis=100), tmp_path, chat_export=True)
    assert pfade["markdown"].exists() and pfade["json"].exists() and pfade["chat"].exists()
    assert "Grundprompt" in erstelle_chat_export([f])


def test_leerer_bericht(vorfilter):
    text = erstelle_bericht([], Laufstatistik())
    assert "Keine belastbaren Verdachtsfälle" in text


# ---------------------------------------------------------------- KI (ohne echte API)
class FakeMessages:
    def __init__(self, antworten):
        self.antworten = list(antworten)
        self.aufrufe = []

    def create(self, **params):
        self.aufrufe.append(params)
        return self.antworten.pop(0)


def _antwort(daten, stop="end_turn"):
    return SimpleNamespace(
        stop_reason=stop,
        stop_details=None,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=json.dumps(daten))],
        usage=SimpleNamespace(input_tokens=100, output_tokens=50, cache_read_input_tokens=0, cache_creation_input_tokens=0),
    )


def _fake_client(antworten):
    msgs = FakeMessages(antworten)
    return SimpleNamespace(messages=msgs, beta=SimpleNamespace(messages=msgs)), msgs


def test_systemprompt_enthaelt_grundprompt_und_modus():
    s = lade_system_prompt()
    assert "Vinted Treasure Hunter" in s and "NEGATIVSUCHE" in s and "MODUS: TRIAGE" in s


def test_schemas_sind_strikt():
    for schema in (TRIAGE_SCHEMA, TIEF_SCHEMA):
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])


def test_triage_anfrage_aufbau(einstellungen, vorfilter):
    client, msgs = _fake_client([_antwort({"vertiefen": True, "prioritaet": "SEHR_INTERESSANT", "hypothese": "Gold", "begruendung": "x", "wichtigstes_fehlendes_foto": "y"})])
    analyst = ClaudeAnalyst(einstellungen, foto_lader=lambda url: (b"\xff\xd8bild", "image/jpeg"), client=client)
    a = anzeige("Ring goldfarben", 9, "Krappenfassung", fotos=5)
    ergebnis = analyst.triage(a, vorfilter.bewerte(a))
    assert ergebnis["vertiefen"] is True
    p = msgs.aufrufe[0]
    assert p["model"] == "claude-opus-5"
    assert p["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert p["output_config"]["effort"] == "low"
    assert p["output_config"]["format"]["schema"] is TRIAGE_SCHEMA
    assert p["fallbacks"] == "default" and p["betas"] == ["server-side-fallback-2026-07-01"]
    bilder = [b for b in p["messages"][0]["content"] if b["type"] == "image"]
    assert len(bilder) == einstellungen.max_fotos_triage
    assert bilder[0]["source"]["type"] == "base64"
    assert p["messages"][0]["content"][-1]["text"].endswith("MODUS: TRIAGE")
    assert analyst.verbrauch.anfragen == 1


def test_foto_url_fallback_und_kein_fallback_bei_anderem_modell(einstellungen):
    einstellungen.modell = "claude-sonnet-5"
    client, msgs = _fake_client([_antwort(_analyse())])
    analyst = ClaudeAnalyst(einstellungen, foto_lader=lambda url: None, client=client)
    analyst.tiefenpruefung(anzeige("Ring", 9, fotos=2), None)
    p = msgs.aufrufe[0]
    assert "fallbacks" not in p
    assert p["output_config"]["effort"] == "high"
    assert [b["source"]["type"] for b in p["messages"][0]["content"] if b["type"] == "image"] == ["url", "url"]


def test_ablehnung_wird_gemeldet(einstellungen):
    client, _ = _fake_client([_antwort({}, stop="refusal")])
    analyst = ClaudeAnalyst(einstellungen, client=client)
    with pytest.raises(KIFehler):
        analyst.triage(anzeige("Ring", 9), None)


# ---------------------------------------------------------------- Pipeline mit Fake-Vinted
class FakeVinted:
    def __init__(self, items):
        self.items = items
        self.suchen = []

    def suche(self, text, **kw):
        self.suchen.append(text)
        return [anzeige_aus_api({k: v for k, v in r.items() if k != "description"}, "de") for r in self.items]

    def details(self, item_id):
        roh = next(r for r in self.items if str(r["id"]) == item_id)
        return anzeige_aus_api(roh, "de", details=True)

    def lade_foto(self, url):
        return b"bild", "image/jpeg"


def test_jagd_lauf_ohne_ki(einstellungen, api_items, tmp_path):
    einstellungen.max_anfragen = 3
    ablage = Ablage(tmp_path / "j.sqlite")
    jagd = Jagd(einstellungen, JagdOptionen(richtungen="AB", details_top=20), client=FakeVinted(api_items), ablage=ablage, melde=lambda t: None)
    funde = jagd.lauf()
    assert jagd.stat.anfragen == 3 and jagd.stat.eindeutig == 10
    nach_id = {f.anzeige.id: f for f in funde}
    assert nach_id["1000002"].anzeige.details_geladen
    assert nach_id["1000002"].prioritaet == "JACKPOT"
    assert "Massenware" in jagd.stat.ausgeschlossen
    # zweiter Lauf: alles bekannt -> mit --nur-neue nichts mehr zu berichten
    jagd2 = Jagd(einstellungen, JagdOptionen(richtungen="AB", nur_neue=True), client=FakeVinted(api_items), ablage=ablage, melde=lambda t: None)
    assert jagd2.lauf() == []
    ablage.schliessen()


def test_jagd_mit_ki(einstellungen, api_items):
    einstellungen.max_anfragen = 1
    einstellungen.tiefen_anzahl = 1
    triage_ja = {"vertiefen": True, "prioritaet": "SEHR_INTERESSANT", "hypothese": "Gold", "begruendung": "b", "wichtigstes_fehlendes_foto": "f"}
    triage_nein = dict(triage_ja, vertiefen=False, prioritaet="NICHT_INTERESSANT")
    antworten = [_antwort(triage_ja)] + [_antwort(triage_nein)] * 20 + [_antwort(_analyse(prioritaet="JACKPOT", urteil="KAUFEN"))]

    class Reihenfolge(FakeMessages):
        def create(self, **params):
            self.aufrufe.append(params)
            modus = params["messages"][0]["content"][-1]["text"].rsplit("MODUS: ", 1)[1]
            if modus == "TIEFENPRÜFUNG":
                return antworten[-1]
            return antworten[0] if len(self.aufrufe) == 1 else antworten[1]

    msgs = Reihenfolge([])
    client = SimpleNamespace(messages=msgs, beta=SimpleNamespace(messages=msgs))
    fake = FakeVinted(api_items)
    analyst = ClaudeAnalyst(einstellungen, foto_lader=fake.lade_foto, client=client)
    jagd = Jagd(einstellungen, JagdOptionen(richtungen="A", ki=True), client=fake, analyst=analyst, melde=lambda t: None)
    funde = jagd.lauf()
    analysiert = [f for f in funde if f.analyse]
    assert len(analysiert) == 1 and analysiert[0].prioritaet == "JACKPOT"
    assert "KI-Anfragen" in jagd.stat.ki_verbrauch
