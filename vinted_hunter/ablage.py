"""SQLite-Ablage: merkt sich gesehene Anzeigen, Preisänderungen und Analysen.

So werden Anzeigen nicht doppelt (und kostenpflichtig) analysiert, und
Preissenkungen bei bereits bekannten Verdachtsfällen fallen auf.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .modelle import Anzeige

_SCHEMA = """
CREATE TABLE IF NOT EXISTS anzeige (
    id TEXT PRIMARY KEY,
    domain TEXT,
    titel TEXT,
    url TEXT,
    preis REAL,
    erstmals TEXT,
    zuletzt TEXT,
    daten TEXT,
    punkte INTEGER,
    prioritaet TEXT,
    vorbewertung TEXT,
    analyse TEXT,
    analysiert_am TEXT,
    analysiert_preis REAL
);
CREATE TABLE IF NOT EXISTS preisverlauf (
    id TEXT,
    zeit TEXT,
    preis REAL
);
CREATE INDEX IF NOT EXISTS idx_preisverlauf_id ON preisverlauf(id);
"""


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Ablage:
    def __init__(self, pfad: Path):
        pfad.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(pfad)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)

    def schliessen(self) -> None:
        self.db.close()

    def bekannt(self, anzeige_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM anzeige WHERE id = ?", (anzeige_id,)).fetchone()

    def speichere(self, a: Anzeige, punkte: int | None = None, prioritaet: str | None = None, vorbewertung: dict | None = None) -> str:
        """Speichert/aktualisiert eine Anzeige. Rückgabe: 'neu', 'preis_gesenkt', 'preis_erhoeht' oder 'bekannt'."""
        jetzt = _jetzt()
        alt = self.bekannt(a.id)
        status = "neu"
        if alt is None:
            self.db.execute(
                "INSERT INTO anzeige (id, domain, titel, url, preis, erstmals, zuletzt, daten, punkte, prioritaet, vorbewertung) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (a.id, a.domain, a.titel, a.url, a.preis, jetzt, jetzt, json.dumps(a.als_dict(), ensure_ascii=False),
                 punkte, prioritaet, json.dumps(vorbewertung, ensure_ascii=False) if vorbewertung else None),
            )
            self.db.execute("INSERT INTO preisverlauf (id, zeit, preis) VALUES (?,?,?)", (a.id, jetzt, a.preis))
        else:
            status = "bekannt"
            if a.preis is not None and alt["preis"] is not None and a.preis != alt["preis"]:
                status = "preis_gesenkt" if a.preis < alt["preis"] else "preis_erhoeht"
                self.db.execute("INSERT INTO preisverlauf (id, zeit, preis) VALUES (?,?,?)", (a.id, jetzt, a.preis))
            self.db.execute(
                "UPDATE anzeige SET titel=?, url=?, preis=?, zuletzt=?, daten=?, punkte=COALESCE(?, punkte), "
                "prioritaet=COALESCE(?, prioritaet), vorbewertung=COALESCE(?, vorbewertung) WHERE id=?",
                (a.titel, a.url, a.preis, jetzt, json.dumps(a.als_dict(), ensure_ascii=False), punkte, prioritaet,
                 json.dumps(vorbewertung, ensure_ascii=False) if vorbewertung else None, a.id),
            )
        self.db.commit()
        return status

    def speichere_analyse(self, anzeige_id: str, analyse: dict, preis: float | None) -> None:
        self.db.execute(
            "UPDATE anzeige SET analyse=?, analysiert_am=?, analysiert_preis=? WHERE id=?",
            (json.dumps(analyse, ensure_ascii=False), _jetzt(), preis, anzeige_id),
        )
        self.db.commit()

    def analyse(self, anzeige_id: str) -> dict | None:
        zeile = self.bekannt(anzeige_id)
        if zeile is None or not zeile["analyse"]:
            return None
        return json.loads(zeile["analyse"])

    def braucht_analyse(self, a: Anzeige) -> bool:
        """Neu analysieren, wenn noch nie analysiert oder der Preis seitdem gefallen ist."""
        zeile = self.bekannt(a.id)
        if zeile is None or not zeile["analyse"]:
            return True
        alt = zeile["analysiert_preis"]
        return a.preis is not None and alt is not None and a.preis < alt

    def preisverlauf(self, anzeige_id: str) -> list[tuple[str, float]]:
        return [(r["zeit"], r["preis"]) for r in self.db.execute("SELECT zeit, preis FROM preisverlauf WHERE id=? ORDER BY zeit", (anzeige_id,))]
