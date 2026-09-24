import json
from pathlib import Path

import pytest

from vinted_hunter.einstellungen import Einstellungen
from vinted_hunter.heuristik import Vorfilter
from vinted_hunter.modelle import Anzeige
from vinted_hunter.wissen import lade_wissen

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def wissen():
    return lade_wissen()


@pytest.fixture
def einstellungen(tmp_path):
    return Einstellungen(domain="de", goldpreis_eur_g=100.0, daten_dir=tmp_path / "daten", berichte_dir=tmp_path / "berichte", verzoegerung_s=0)


@pytest.fixture
def vorfilter(wissen, einstellungen):
    return Vorfilter(wissen, einstellungen)


@pytest.fixture
def api_items():
    return json.loads((FIXTURES / "vinted_api_items.json").read_text(encoding="utf-8"))["items"]


def anzeige(titel, preis=20.0, beschreibung="", fotos=1, **kw):
    return Anzeige(id=kw.pop("id", titel[:20]), titel=titel, preis=preis, beschreibung=beschreibung,
                   fotos=[f"https://example.invalid/{i}.jpg" for i in range(fotos)], **kw)
