---
name: schatzsuche
description: Vinted-Schatzsuche nach unterschätztem Vintage-/Designer-Schmuck ausführen und die Kandidaten-Fotos selbst nach der Grundprompt begutachten. Verwenden, wenn nach Vinted-Schmuckfunden, Goldverdacht, Punzen oder einer neuen Suchrunde gefragt wird.
---

# Vinted-Schatzsuche (Claude Code)

Maßgeblich sind die Regeln in `prompts/grundprompt.md` – lies die Datei vollständig, bevor du bewertest.
Die Skripte übernehmen Suche und Vorfilter; **du** übernimmst die Bildforensik.

## Ablauf

1. **Suche + Vorfilter + Fotos laden**

   ```bash
   python -m vinted_hunter jagd --bilder --auch-interessant --max-anfragen 40
   ```

   Nützliche Optionen (siehe `python -m vinted_hunter jagd --help`):
   `--richtungen ABF` (nur bestimmte Suchrichtungen), `--max-preis 60`, `--nur-neue`,
   `--domain fr`, `--goldpreis <aktueller €/g-Kurs>`.

   Wenn Vinted blockiert (403), dem Nutzer den Abschnitt „Wenn Vinted blockiert“ aus der README nennen.

2. **Bericht lesen**: Der Pfad steht am Ende der Ausgabe (`berichte/schatzsuche_*.md`).
   Die JSON-Datei daneben enthält alle nicht aussortierten Kandidaten mit Vorbewertung.

3. **Fotos begutachten**: Für jeden Kandidaten liegen die Fotos unter `daten/bilder/<id>/foto_NN.jpg`
   und die Anzeigendaten in `daten/bilder/<id>/anzeige.json`. Sieh dir **jedes** Foto mit dem Read-Tool an.
   Prüfe besonders:
   - indirekte Goldindizien (Abschnitt 3): Farbe an Abrieb- und geschützten Stellen, Lötstellen, Scharniere,
     Kastenschloss, Omega-Clip, Fassungen, Materialstärke
   - Punzen-Forensik (Abschnitt 4): Wo säße die Punze bei genau diesem Stück – und wurde diese Stelle fotografiert?
   - Design-DNA ohne Markennamen (Abschnitt 5)
   - Negativsuche (Abschnitt 21): Was fehlt auf den Fotos?

4. **Ausgabe** im Format von Abschnitt 18, standardmäßig nur 🔥🔥🔥 und 🔥🔥.
   Evidenzstufen strikt trennen (🟢 IDENTIFIZIERT … 🔴 KEIN AUSREICHENDER HINWEIS).
   Nie eine Punze „lesen“, die auf dem Foto nicht wirklich lesbar ist.
   Bei unzureichender Evidenz: „Interessanter Verdacht, aber noch kein Kauf.“

5. Optional für Top-Kandidaten: externe Vergleiche (Abschnitt 12) per Websuche – identisches Modell oder
   identische Designfamilie, bevorzugt abgeschlossene Auktionen und seriöse Händler.

## Einzelne Anzeige prüfen

```bash
python -m vinted_hunter pruefe https://www.vinted.de/items/<id>
```

Danach wie in Schritt 3/4 bewerten. Mit API-Schlüssel analysiert `--ki` die Fotos direkt über die Claude-API.

## Wissensbasis erweitern

Neue Marken, Tippfehler, Design-DNA oder Begriffe gehören in `vinted_hunter/wissen/*.toml`
(nicht in den Python-Code). Nach Änderungen `python -m pytest -q` ausführen.
