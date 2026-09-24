# Vinted Treasure Hunter

Werkzeug zur Suche nach unterschätztem Vintage- und Designer-Schmuck auf Vinted.
Die fachlichen Regeln stehen in `prompts/grundprompt.md` und gelten für jede Bewertung von Funden.

## Aufbau

- `vinted_hunter/wissen/*.toml` – editierbare Wissensbasis (Marken inkl. Tippfehler, Begriffe, Suchrichtungen A–G, Design-DNA)
- `vinted_hunter/suchanfragen.py` – erzeugt Suchanfragen für die Richtungen A–G inkl. Tippfehler-Varianten und Tagesrotation
- `vinted_hunter/vinted.py` – Client für die inoffizielle Vinted-Web-API (Suche, Details, HTML-Fallback)
- `vinted_hunter/heuristik.py` – Text-Vorfilter: Gold-/Marken-/Epochenindizien, Informationsasymmetrie, Negativsuche, Negativfilter
- `vinted_hunter/ki.py` – Claude-Analyse (Triage → optional Recherche → Tiefenprüfung) mit der Grundprompt als System-Prompt
- `vinted_hunter/jagd.py` – Pipeline; `vinted_hunter/bericht.py` – Berichte im Ausgabeformat (Abschnitt 18)
- `vinted_hunter/ablage.py` – SQLite (gesehene Anzeigen, Preisverlauf, gespeicherte Analysen)

## Konventionen

- Sprache für Nutzertexte, Kommentare und Wissensbasis: Deutsch.
- Fachwissen gehört in die TOML-Dateien, nicht in den Code.
- Der Vorfilter spricht nie ein Kaufurteil aus – nur die KI-Tiefenprüfung oder ein Mensch.
- Tests: `python -m pytest -q` (laufen offline, keine Vinted- oder API-Aufrufe).
- Für eine Suchrunde mit Bildbegutachtung durch Claude Code: Skill `/schatzsuche`.
