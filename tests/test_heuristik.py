from conftest import anzeige

from vinted_hunter.heuristik import (
    GOLD_KEIN,
    GOLD_PLATTIERT,
    GOLD_TEXT,
    GOLD_VERDACHT,
    PRIO_JACKPOT,
    PRIO_NICHT,
    PRIO_RANG,
    PRIO_SEHR,
)
from vinted_hunter.vinted import anzeige_aus_api


def rang(v):
    return PRIO_RANG[v.prioritaet]


# ---------------------------------------------------------------- Negativfilter (Abschnitt 16)
def test_massenware_wird_aussortiert(vorfilter):
    v = vorfilter.bewerte(anzeige("Pandora Armband mit Charms", 30))
    assert v.ausgeschlossen and "Massenware" in v.ausschlussgrund


def test_faelschungshinweis_wird_aussortiert(vorfilter):
    v = vorfilter.bewerte(anzeige("Armband Love Stil wie Cartier style", 15))
    assert v.ausgeschlossen and "Fälschung" in v.ausschlussgrund


def test_gewoehnliches_silber_wird_aussortiert(vorfilter):
    v = vorfilter.bewerte(anzeige("925 Silber Ring schlicht", 10, "Sterling Silber Ring Gr. 56"))
    assert v.ausgeschlossen and "Silber" in v.ausschlussgrund


def test_designersilber_bleibt(vorfilter):
    v = vorfilter.bewerte(anzeige("Georg Jensen Brosche 925 Silber", 30, "Sterling Denmark, Nummer auf Rückseite"))
    assert not v.ausgeschlossen
    assert any(m.marke == "Georg Jensen" for m in v.marken)


def test_edelstahl_mit_plattierung_raus(vorfilter):
    v = vorfilter.bewerte(anzeige("Kette 18k gold plated Edelstahl", 6))
    assert v.ausgeschlossen


def test_kein_schmuck_raus(vorfilter):
    v = vorfilter.bewerte(anzeige("Winterjacke Größe 38", 15, "geringe Gebrauchsspuren"))
    assert v.ausgeschlossen and v.ausschlussgrund == "kein Schmuck erkannt"


def test_reine_optik_ist_nie_interessant(vorfilter):
    # billig + "vintage" + Oma, aber ohne jedes konkrete Wertindiz
    v = vorfilter.bewerte(anzeige("Vintage Kette von Oma", 3, "keine Ahnung, siehe Fotos"))
    assert v.prioritaet == PRIO_NICHT


# ---------------------------------------------------------------- Gold (Abschnitte 2–4)
def test_feingehalt_mit_gewicht_ergibt_materialwert(vorfilter):
    v = vorfilter.bewerte(anzeige("Goldring 585 Gelbgold", 45, "Ring aus 585er Gold, wiegt 3,2 g. Nachlass.", fotos=3))
    assert v.goldstatus == GOLD_TEXT
    assert v.gewicht_g == 3.2
    assert v.materialwert_eur == round(3.2 * 0.585 * 100.0, 2)
    assert v.preis_verhaeltnis and v.preis_verhaeltnis > 3
    assert v.prioritaet == PRIO_JACKPOT


def test_hoher_preis_senkt_trotz_gold(vorfilter):
    v = vorfilter.bewerte(anzeige("Goldring 333", 140, "333 Gold, 1,5 g", fotos=3))
    assert v.goldstatus == GOLD_TEXT
    assert v.preis_verhaeltnis < 1
    assert rang(v) < PRIO_RANG[PRIO_SEHR]


def test_karat_plattiert_ist_kein_gold(vorfilter):
    v = vorfilter.bewerte(anzeige("Ring 18k vergoldet mit Zirkonia", 9))
    assert v.goldstatus == GOLD_PLATTIERT
    assert v.prioritaet == PRIO_NICHT


def test_nicht_vergoldet_ist_keine_plattierung(vorfilter):
    v = vorfilter.bewerte(anzeige("Ring 585 Gold", 60, "585 Gold, nicht vergoldet, 2 g", fotos=3))
    assert v.goldstatus == GOLD_TEXT
    assert not any("Widerspruch" in w for w in v.warnungen)


def test_farbe_gold_ist_kein_goldbeleg(vorfilter):
    v = vorfilter.bewerte(anzeige("Kette gold", 7, "Farbe: Gold, neu"))
    assert v.goldstatus in (GOLD_KEIN, GOLD_VERDACHT)
    assert v.prioritaet == PRIO_NICHT


def test_goldfarben_plus_konstruktion_ist_verdacht(vorfilter):
    """Abschnitt 2/3: Goldverdacht ohne Punze, über die Konstruktion."""
    v = vorfilter.bewerte(anzeige("Ohrclips vintage goldfarben", 9, "Schwere Ohrclips mit Omega-Clip, weiß nicht welches Material."))
    assert v.goldstatus == GOLD_VERDACHT
    assert any("Farbangabe" in x for x in v.asymmetrie)
    assert v.kategorie == "ohrclips"
    assert "Clipbügel" in v.wichtigstes_foto
    assert rang(v) >= 1


# ---------------------------------------------------------------- Marken / Design-DNA (Abschnitte 5/6, Richtung F)
def test_tippfehler_marke_wird_erkannt(vorfilter):
    v = vorfilter.bewerte(anzeige("Brosche Theodor Farner Markasit", 20, "alte Brosche mit Markasit und Chrysopras, gestempelt", fotos=2))
    treffer = {m.marke: m for m in v.marken}
    assert treffer["Theodor Fahrner"].art == "tippfehler"
    assert any("Theodor Fahrner" in d for d in v.dna)
    assert rang(v) >= PRIO_RANG[PRIO_SEHR]


def test_unbekannter_tippfehler_per_editierdistanz(vorfilter):
    v = vorfilter.bewerte(anzeige("Brosche Lapponnia Silber", 25, "Skulpturale Brosche"))
    assert any(m.marke == "Lapponia" and m.art == "tippfehler" for m in v.marken)


def test_fahrer_ist_nicht_fahrner(vorfilter):
    v = vorfilter.bewerte(anzeige("Ring vom LKW Fahrer gefunden", 10, "Ring aus Messing"))
    assert not any(m.marke == "Theodor Fahrner" for m in v.marken)


def test_marke_nur_als_vergleich(vorfilter):
    v = vorfilter.bewerte(anzeige("Armreif ähnlich Hermes", 12, "Emaille Armreif"))
    assert all(m.art == "vergleich" for m in v.marken if m.marke == "Hermès")


def test_luxusmarke_billig_ist_kein_jackpot(vorfilter):
    v = vorfilter.bewerte(anzeige("Cartier Love Armband", 25, "Schönes Armband"))
    assert v.prioritaet != PRIO_JACKPOT
    assert any("Fälschung" in w for w in v.warnungen)


def test_design_dna_ohne_markenname(vorfilter):
    v = vorfilter.bewerte(anzeige("Art Deco Kette Chrom Galalith", 15, "alt, vom Flohmarkt", fotos=2))
    assert any("Bengel" in d for d in v.dna)
    assert "keine Marke angegeben, obwohl Stil/Design auffällt" in v.info_luecken


def test_grosse_brosche_ist_nicht_henkel_grosse(vorfilter):
    v = vorfilter.bewerte(anzeige("Große Brosche alt", 10, "Eine große Brosche"))
    assert not any("Grosse" in m.marke for m in v.marken)


# ---------------------------------------------------------------- Negativsuche / Konvolut / Kategorie
def test_info_luecken_werden_benannt(vorfilter):
    v = vorfilter.bewerte(anzeige("Goldring", 15, "", fotos=1))
    assert "kein Gewicht angegeben" in v.info_luecken
    assert any("Foto" in l for l in v.info_luecken)
    assert "sehr kurze Beschreibung" in v.info_luecken


def test_konvolut_ohne_wertsignal_wird_abgewertet(vorfilter):
    v = vorfilter.bewerte(anzeige("Schmuck Konvolut 30 Teile", 10, "Modeschmuck, Ketten und Ringe"))
    assert v.kategorie == "konvolut"
    assert v.prioritaet == PRIO_NICHT


def test_konvolut_mit_goldverdacht(vorfilter):
    v = vorfilter.bewerte(anzeige("Schmuck Konvolut 25 Teile Nachlass", 20, "Alter Modeschmuck vom Dachboden. Evtl. ist auch Gold dabei, ungeprüft.", fotos=2))
    assert v.kategorie == "konvolut"
    assert v.goldstatus == GOLD_VERDACHT
    assert rang(v) >= 1


def test_konvolut_mit_massenware_wird_nicht_pauschal_aussortiert(vorfilter):
    v = vorfilter.bewerte(anzeige("Schmuck Konvolut 20 Teile", 25, "u.a. Pandora, Thomas Sabo und ein alter Ring 585 Gold", fotos=4))
    assert not v.ausgeschlossen
    assert v.goldstatus == GOLD_TEXT
    assert any("Massenware" in w for w in v.warnungen)


def test_falsche_kategorie_ist_asymmetrie(vorfilter):
    a = anzeige("Brosche alt Emaille", 8, "Emaille Brosche mit Scharnier", katalog_name="Dekoration")
    v = vorfilter.bewerte(a)
    assert any("Falsche Kategorie" in x for x in v.asymmetrie)


def test_gering_ist_kein_ring(vorfilter):
    v = vorfilter.bewerte(anzeige("Brosche", 10, "geringe Gebrauchsspuren"))
    assert v.kategorie == "brosche"


def test_nachricht_verraet_verdacht_nicht(vorfilter):
    v = vorfilter.bewerte(anzeige("Ring goldfarben schwer", 8, "Krappenfassung, keine Ahnung"))
    n = v.nachricht_an_verkaeufer.lower()
    assert "ringinnenseite" in n
    assert "gold" not in n and "wert" not in n


def test_fixture_datei_end_to_end(vorfilter, api_items):
    ergebnisse = {str(r["id"]): vorfilter.bewerte(anzeige_aus_api(r, "de", details=True)) for r in api_items}
    assert ergebnisse["1000004"].ausgeschlossen  # Pandora
    assert ergebnisse["1000005"].ausgeschlossen  # Edelstahl
    assert ergebnisse["1000008"].ausgeschlossen  # Silber schlicht
    assert ergebnisse["1000010"].ausgeschlossen  # Jacke
    assert ergebnisse["1000002"].prioritaet == PRIO_JACKPOT
    assert rang(ergebnisse["1000003"]) >= PRIO_RANG[PRIO_SEHR]
    assert ergebnisse["1000006"].prioritaet != PRIO_JACKPOT
