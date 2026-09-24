# Vinted Treasure Hunter 💎

Findet Schmuck auf Vinted, bei dem der Verkäufer wahrscheinlich **nicht erkannt hat, was er besitzt**:
Echtgold, das als „goldfarbener Modeschmuck“ verkauft wird, falsch geschriebene Designer, unsignierte
Art-Déco-Stücke, Konvolute mit einem wertvollen Einzelstück.

Die Regeln stammen aus der [Grundprompt](prompts/grundprompt.md). Die Skripte setzen sie um:
nicht nach Preis suchen, sondern nach **Fehlern**, also nach der Lücke zwischen möglichem Wert und dem, was der Verkäufer weiß.

```
Suchanfragen A–G ──► Vinted-Suche ──► Text-Vorfilter ──► Details laden ──► Vorfilter
                                           │                                   │
                                  Negativfilter (Abschn. 16)        Negativsuche: Was fehlt?
                                                                               │
                         Bericht (Abschn. 18) ◄── KI-Tiefenprüfung ◄── KI-Triage (optional)
```

## Was gegenüber einer manuellen Suche besser ist

| Grundprompt | Umsetzung |
|---|---|
| **15. Suchstrategie A–G** | Über 500 Suchanfragen in 7 Richtungen, reihum gemischt. Eine Tagesrotation verteilt sie auf mehrere Läufe. |
| **F. Fehlerbasiert** | Bekannte **und automatisch erzeugte Tippfehler** („Theodor Farner“, „George Jensen“, „Frei Wille“). Genau diese Anzeigen finden andere Käufer nicht. Unbekannte Tippfehler werden zusätzlich per Editierdistanz im Text erkannt. |
| **2./3. Gold ohne Punze** | Goldverdacht auch ohne Feingehalt, etwa „goldfarben“ **plus** Omega-Clip, Kastenschloss, Krappenfassung oder „schwer“. „Farbe: Gold“ und „18k vergoldet“ gelten dagegen nicht als Goldbeleg. |
| **4. Punzen-Forensik** | Für jede Schmuckart der typische Punzen-Ort, daraus „Wichtigstes fehlendes Foto“ und eine neutrale Nachfrage an den Verkäufer. |
| **5./6. Design-DNA, weniger bekannte Marken** | 126 Marken in 6 Stufen (u. a. Fahrner, Bengel, Henkel & Grosse, Frey Wille, Hagenauer, Georg Jensen, Lapponia, Sarpaneva). Dazu Motiv-DNA ohne Markennamen, z. B. Galalith + Chrom → Bengel, Markasit + Chrysopras → Fahrner. |
| **9. Verkäufer-Beschreibung** | Formulierungen wie „keine Ahnung“ oder „Nachlass“ zählen **nur**, wenn gleichzeitig echte Wertindizien vorliegen. |
| **10./21. Negativsuche** | Fehlendes Gewicht, fehlende Punze, 1–2 Fotos, leere Beschreibung, Stil ohne Markenangabe, falsche Kategorie. |
| **13. Preisbewertung** | Materialwert aus Feingehalt × Gewicht × Goldkurs und eine konservative Untergrenze (Altgold-Ankauf 90 %, Sammlermarken ≥ 60 €). |
| **14. Konvolute** | Nur mit Wertsignal interessant; die KI bewertet jedes Einzelstück separat. |
| **16. Negativfilter** | Massenware (Pandora, Thomas Sabo, Fast Fashion …), Fälschungshinweise, Edelstahl, Perlenimitat, gewöhnliches 925er Silber ohne Designer. |
| **17. Prioritäten** | 🔥🔥🔥 nur mit belastbarem Anker (Feingehaltsangabe oder Sammlermarke) **und** Preis ≥ 2–3× unter der Untergrenze. Standardmäßig werden nur 🔥🔥🔥 und 🔥🔥 gezeigt. |
| **Gedächtnis** | SQLite merkt sich gesehene Anzeigen und Preissenkungen. Bereits analysierte Anzeigen kosten keine zweite KI-Anfrage. |

## Installation

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Python ≥ 3.11. `curl_cffi` ist optional, wird aber empfohlen: Es imitiert einen echten Browser, und Vinted blockiert dann seltener.

## Schnellstart

```bash
# Welche Suchanfragen würden laufen? (ohne Netz)
python -m vinted_hunter anfragen --max-anfragen 40 --rotation

# Suchlauf nur mit Text-Vorfilter (kostenlos)
python -m vinted_hunter jagd

# Suchlauf mit Bildanalyse durch Claude nach der Grundprompt
export ANTHROPIC_API_KEY=sk-ant-...
python -m vinted_hunter jagd --ki

# … zusätzlich mit externer Vergleichsrecherche (Auktionen, Händler)
python -m vinted_hunter jagd --ki --recherche

# Eine einzelne Anzeige prüfen
python -m vinted_hunter pruefe https://www.vinted.de/items/1234567890 --ki
```

Berichte landen in `berichte/schatzsuche_<datum>.md` (plus `.json`), die Datenbank in `daten/hunter.sqlite`.

### Wichtige Optionen für `jagd`

| Option | Bedeutung |
|---|---|
| `--richtungen ABF` | Nur bestimmte Suchrichtungen (A Material, B Beschreibung, C Kategorie, D Design, E Marke, F Fehler, G Visuell) |
| `--max-anfragen 40` | Suchanfragen pro Lauf (Standard 40, ca. 2–3 Minuten) |
| `--max-preis 60` | Preisobergrenze (Standard 150 €) |
| `--goldpreis 118` | **Aktuellen Goldkurs in €/g eintragen** (Standard 110, oder Umgebungsvariable `VH_GOLDPREIS`) |
| `--domain fr` | Anderes Vinted-Land (de, at, fr, be, nl, it, es, …); Suchbegriffe passen sich der Sprache an |
| `--nur-neue` | Nur neue oder im Preis gesenkte Anzeigen berichten (ideal für regelmäßige Läufe) |
| `--auch-interessant` | Auch 🔥-Funde zeigen |
| `--ki-triage 25 --ki-tief 8` | Wie viele Anzeigen die KI sichtet bzw. vollständig prüft |
| `--chat-export` | Kandidatenliste zum Einfügen in einen Claude-Chat, falls kein API-Schlüssel vorhanden ist |
| `--bilder` | Fotos der Kandidaten nach `daten/bilder/<id>/` laden (für Claude Code) |
| `--katalog-ids …` | Auf Vinted-Kategorien einschränken (IDs über `python -m vinted_hunter kataloge`) |

## Drei Arten, die Fotos prüfen zu lassen

Der Text-Vorfilter entscheidet nur, **welche** Anzeigen genauer angesehen werden. Er spricht nie ein Kaufurteil aus.
Die eigentliche Fotoforensik läuft auf einem von drei Wegen:

1. **`--ki` (Claude-API)**: zweistufig, damit die Kosten gering bleiben.
   - *Triage* (bis zu 3 Fotos, geringer Denkaufwand): Lohnt sich ein genauer Blick?
   - *Tiefenprüfung* (bis zu 8 Fotos, hoher Denkaufwand): vollständiges Ausgabeformat nach Abschnitt 18 mit
     Evidenzstufen, gelesenen Punzen samt Fotonummer, Negativsuche und Kaufurteil.
   - Die Grundprompt ist der System-Prompt und wird per Prompt-Caching wiederverwendet. Die Antworten
     sind per JSON-Schema strukturiert. Die Kosten stehen am Ende jedes Berichts.
   - Modell: `claude-opus-5`, änderbar per `--modell` oder `VH_MODELL`.
2. **Claude Code, Skill `/schatzsuche`**: Claude Code führt `jagd --bilder` aus, sieht sich die Fotos selbst an und
   bewertet sie nach der Grundprompt. Dafür ist kein API-Schlüssel nötig.
3. **Claude-Chat**: `--chat-export` erzeugt eine Kandidatenliste mit Links, die du zusammen mit der Grundprompt in
   einen Chat einfügst.

## Regelmäßig laufen lassen

```bash
# crontab -e: jeden Tag um 7:30 und 19:30, nur Neues, mit KI
30 7,19 * * * cd /pfad/zu/clatest && .venv/bin/python -m vinted_hunter jagd --ki --nur-neue >> daten/cron.log 2>&1
```

Durch die Tagesrotation laufen an jedem Tag andere Suchanfragen. Nach etwa zwei Wochen ist der gesamte Suchraum einmal abgedeckt.

## Wenn Vinted blockiert (403 / Captcha)

Vinted hat keine offizielle API. Der Client nutzt dieselben Endpunkte wie die Website und wartet zwischen den Anfragen.
Wenn trotzdem blockiert wird:

1. `pip install curl_cffi` (Browser-Imitation)
2. `--verzoegerung 4` (langsamer suchen)
3. Den Cookie aus dem eigenen Browser übernehmen: vinted.de öffnen → Entwicklerwerkzeuge (F12) → Netzwerk → eine
   Anfrage an `vinted.de` anklicken → Request-Header `Cookie` kopieren, dann:
   ```bash
   export VINTED_COOKIE='…kopierter Wert…'
   ```

Bitte maßvoll nutzen: wenige Läufe pro Tag, nur für den privaten Gebrauch. Automatisierte Abfragen können gegen die
Nutzungsbedingungen von Vinted verstoßen.

## Die Wissensbasis erweitern

Das Fachwissen steht in editierbaren TOML-Dateien, nicht im Code:

- [`vinted_hunter/wissen/marken.toml`](vinted_hunter/wissen/marken.toml): Marken, Aliase, Tippfehler, Wertstufe
  (`luxus`, `sammler`, `goldschmied`, `designer_modeschmuck`, `neutral`, `massenware`)
- [`vinted_hunter/wissen/begriffe.toml`](vinted_hunter/wissen/begriffe.toml): Gold-, Konstruktions-, Stein-, Epochen-,
  Verkäufer- und Ausschlussbegriffe, Punzen-Orte, Mindestgewichte
- [`vinted_hunter/wissen/suche.toml`](vinted_hunter/wissen/suche.toml): Suchbegriffe pro Richtung und Sprache, Design-DNA

Nach Änderungen: `python -m pytest -q`.

## Offline testen

```bash
python -m pytest -q                                                  # läuft ohne Netz und ohne API
python -m vinted_hunter datei tests/fixtures/vinted_api_items.json   # Beispielbericht aus Testdaten
```

Mit `datei` lassen sich auch eigene JSON-Exporte bewerten (Vinted-API-Format oder das JSON aus `berichte/`).

## Grenzen

- Der Vorfilter liest nur Text. Ein „🔥🔥🔥“ ohne `--ki` bedeutet: *genau hinsehen*, nicht *kaufen*.
- Feingehalte im Text sind Behauptungen des Verkäufers. Belegt sind sie erst durch eine lesbare Punze, und
  auch Punzen können gefälscht sein.
- Bei Luxusmarken zu Niedrigpreisen ist eine Fälschung fast immer wahrscheinlicher als ein Preisfehler.
- Alte Edelkoralle, Elfenbein und Schildpatt unterliegen Handelsbeschränkungen, bitte vor einem Weiterverkauf prüfen.
