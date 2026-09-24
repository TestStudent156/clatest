from datetime import date

import pytest

from vinted_hunter import gold
from vinted_hunter.suchanfragen import ALLE_RICHTUNGEN, Suchgenerator, tippfehler_varianten
from vinted_hunter.text import damerau_levenshtein, endet_mit_begriff, finde, normalisiere


# ---------------------------------------------------------------- Text
@pytest.mark.parametrize(
    "roh,erwartet",
    [("Anhänger", "anhanger"), ("Anhaenger", "anhanger"), ("Art-Déco", "art deco"), ("Weißgold", "weissgold"), ("  A  B ", "a b")],
)
def test_normalisiere(roh, erwartet):
    assert normalisiere(roh) == erwartet


def test_finde_wortgrenzen_und_komposita():
    t = normalisiere("Schöner Weißgoldring mit Brillanten, Goldfarbe")
    assert finde(t, ["weissgold"]) == ["weissgold"]  # lang -> Kompositum erlaubt
    assert finde(t, ["brillant"]) == ["brillant"]
    assert finde(t, ["gold"]) == []  # kurz -> nur ganzes Wort
    assert endet_mit_begriff(normalisiere("Siegelring"), ["ring"])
    assert not endet_mit_begriff(normalisiere("Ringelsocken"), ["ring"])


def test_damerau():
    assert damerau_levenshtein("fahrner", "farhner") == 1
    assert damerau_levenshtein("lapponia", "laponia") == 1
    assert damerau_levenshtein("cartier", "chanel") > 2


# ---------------------------------------------------------------- Gold
@pytest.mark.parametrize(
    "text,gewicht",
    [("wiegt 3,2 g", 3.2), ("Gewicht: 4.1g", 4.1), ("ca. 12 Gramm schwer", 12.0), ("Größe 56", None), ("0,1 g", None)],
)
def test_gewicht(text, gewicht):
    assert gold.finde_gewicht(text) == gewicht


def test_feingehalte():
    werte = {g.feingehalt for g in gold.finde_feingehalte(normalisiere("585er Gold und 18 Karat, 333"), True)}
    assert werte == {0.585, 0.75, 0.333}
    assert gold.finde_feingehalte(normalisiere("999 Feinsilber"), gold_erwaehnt=False) == []
    assert gold.finde_feingehalte(normalisiere("Preis 1585 Euro"), True) == []


def test_materialwert():
    assert gold.materialwert(10, 0.585, 100) == 585.0
    assert gold.ankaufswert(10, 0.585, 100) == pytest.approx(526.5)


# ---------------------------------------------------------------- Suche (Abschnitt 15)
def test_alle_richtungen_vertreten(wissen):
    gen = Suchgenerator(wissen, "de")
    anfragen = gen.erzeuge(ALLE_RICHTUNGEN, max_anfragen=14)
    assert {q.richtung for q in anfragen} == set(ALLE_RICHTUNGEN)


def test_keine_doppelten_anfragen(wissen):
    anfragen = Suchgenerator(wissen, "de").erzeuge()
    schluessel = [q.schluessel for q in anfragen]
    assert len(schluessel) == len(set(schluessel))


def test_rotation_ist_tagesstabil(wissen):
    gen = Suchgenerator(wissen, "de")
    a = gen.erzeuge(max_anfragen=20, rotation=True, stichtag=date(2026, 9, 24))
    b = gen.erzeuge(max_anfragen=20, rotation=True, stichtag=date(2026, 9, 24))
    c = gen.erzeuge(max_anfragen=20, rotation=True, stichtag=date(2026, 9, 25))
    assert a == b and a != c


def test_fehlerrichtung_enthaelt_tippfehler_aber_keine_luxusmarken(wissen):
    f = Suchgenerator(wissen, "de").richtung("F")
    gruende = " ".join(q.grund for q in f)
    assert "Tippfehler von Theodor Fahrner" in gruende
    assert "Cartier" not in gruende


def test_fremdsprache_faellt_auf_englisch_zurueck(wissen):
    anfragen = Suchgenerator(wissen, "pl").richtung("A")
    assert any("gold" in q.text.lower() for q in anfragen)


def test_tippfehler_varianten():
    v = tippfehler_varianten("Georg Jensen")
    assert v and all(x != "georg jensen" for x in v)
    assert len(v) == len(set(v))


def test_unbekannte_richtung(wissen):
    with pytest.raises(ValueError):
        Suchgenerator(wissen).erzeuge("AX")
