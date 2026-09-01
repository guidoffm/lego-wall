# legowall — Bilder als LEGO-Wandbild

Nimmt ein Bild (PNG/JPG), rechnet es auf ein LEGO-Stud-Raster der gewünschten
Größe herunter, ordnet jedem Stud die am besten passende LEGO-Farbe zu und
liefert alles, was zum Bestellen und Bauen nötig ist: Stückliste, BrickLink-
Wanted-List, Vorschau und eine plattenweise Bauanleitung.

Es gibt zwei Wege: eine **Web-Oberfläche** mit Datei-Upload und ein
**Kommandozeilen-Tool** für Batch-Betrieb.

## Installation

```sh
git clone git@github.com:guidoffm/lego-wall.git && cd lego-wall
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[web]"        # ohne [web] nur die CLI
```

Abhängigkeiten: Pillow und numpy für den Kern, FastAPI/uvicorn/Jinja2 für die
Web-Oberfläche.

## Web-Oberfläche

```sh
legowall serve                 # http://127.0.0.1:8000
```

Bild hochladen, Breite (und optional Höhe) in Studs angeben, Palette wählen —
die Ergebnisseite zeigt Vorschau und Stückliste und bietet alle Dateien als
Download an, einzeln oder als ZIP.

Die App ist zustandslos: ein Request rechnet das Mosaik und hängt alle Dateien
als Data-URI in die Antwortseite mit — nichts wird zwischengespeichert oder auf die
Platte geschrieben. Uploads sind auf 25 MB begrenzt, das Raster auf 256 Studs je
Kante und 40 000 Studs insgesamt.

Damit die Antwort klein bleibt, gilt ein Budget von 3 MB für die eingebetteten
Dateien. Das ZIP steht vorn, weil es komprimiert alles enthält (auch bei
200x200 Studs nur rund 270 KB). Was nicht mehr hineinpasst — bei großen Rastern
die knapp 5 MB große `bauanleitung.html` — bleibt nur im ZIP, die Seite weist
darauf hin.

Im Container:

```sh
docker build -t legowall .
docker run --rm -p 8000:8000 legowall
```

Auf Vercel (Python/FastAPI-Runtime) läuft dieselbe App ohne Anpassung; den
Einstiegspunkt findet die Plattform über `[tool.vercel]` in `pyproject.toml`.
Der Docker-Build ist bislang nicht ausprobiert.

## Kommandozeile

```sh
legowall build foto.jpg --size 48x48
legowall build foto.jpg --width 96 --palette grayscale-5 --dither none
legowall build portrait.png --size 48x64 --palette art-16 --max-colors 12
legowall palettes                       # mitgelieferte Paletten anzeigen
```

Geschrieben wird nach `--out-dir` (Standard `legowall-out/`):

| Datei | Inhalt |
|---|---|
| `vorschau.png` | Vorschau mit sichtbaren Studs, rote Linien = Plattengrenzen |
| `mosaik.png` | Mosaik mit 1 Pixel pro Stud (für eigene Weiterverarbeitung) |
| `stueckliste.csv` | Stückliste mit Farbnamen, Hex, LEGO-/BrickLink-ID, Anzahl |
| `stueckliste.json` | dieselben Daten maschinenlesbar, plus Maße und Plattenbedarf |
| `bricklink-wanted-list.xml` | Massenupload für BrickLink → Wanted List → Upload |
| `bauanleitung.html` | druckbare Anleitung: Legende, Rasterplan und Reihen je Platte |

### Wichtige Optionen

**Abmessungen** — `--size 48x48` oder `--width`/`--height`. Wird nur eine Kante
angegeben, ergibt sich die andere aus dem Seitenverhältnis des Bildes. Ein Stud
ist 8 mm breit, 48 Studs sind also 38,4 cm.

`--fit` bestimmt, was mit abweichenden Seitenverhältnissen passiert:
`cover` beschneidet mittig (Standard), `contain` passt das ganze Bild ein und
füllt den Rand mit `--background`, `stretch` verzerrt.

**Farben** — `--palette` nimmt eine mitgelieferte Palette oder den Pfad zu
einer eigenen JSON-Datei (Format siehe unten):

| Palette | Farben | gedacht für |
|---|---|---|
| `pab-full` | 46 | Standard — breite Auswahl einzeln erhältlicher Farben |
| `art-16` | 16 | Portraits und Motive mit Hauttönen |
| `grayscale-5` | 5 | Schwarz-Weiß-Motive, günstig zu beschaffen |

`--max-colors N` begrenzt die Farbanzahl auf die N häufigsten — praktisch, wenn
nicht 40 verschiedene Farben bestellt werden sollen. Dabei wird zweistufig
gerechnet: erst mit der vollen Palette quantisieren, dann mit der reduzierten
Palette erneut, damit die Fehlerdiffusion die Beschränkung berücksichtigt.

`--dither floyd-steinberg` (Standard) verteilt den Quantisierungsfehler auf die
Nachbarstuds und erzeugt so weiche Verläufe aus wenigen Farben; `--dither none`
gibt harte Farbflächen — ruhiger bei grafischen Motiven und Logos.

`--brightness`, `--contrast`, `--saturation` (jeweils `1.0` = unverändert)
helfen, wenn das Motiv im Raster zu flach wirkt. Etwas mehr Kontrast und
Sättigung tut kleinen Rastern meist gut.

**Teile** — `--element` wählt das 1x1-Element für die Fläche:

| Wert | Teil | Bemerkung |
|---|---|---|
| `tile-round-1x1` | 98138 | Standard, wie bei LEGO Art — glatt, keine sichtbaren Noppen |
| `plate-round-1x1` | 6141 | günstiger, Noppe bleibt sichtbar |
| `plate-1x1` | 3024 | eckiges Raster, sehr breit verfügbar |
| `tile-1x1` | 3070b | eckig und glatt, geschlossene Fläche |

`--panel-size` ist die Kantenlänge der Trägerplatten (Standard 16 — Teil 91405,
wie bei LEGO Art). Das Raster muss nicht glatt aufgehen; wenn nicht, weist die
Zusammenfassung darauf hin, dass Randplatten teilweise unbelegt bleiben.

## Als Bibliothek

```python
from PIL import Image
from legowall import build_mosaic, build_plan, load_palette, parts_csv

with Image.open("foto.jpg") as image:
    mosaic = build_mosaic(image, 48, 48, load_palette("art-16"), max_colors=12)

plan = build_plan(mosaic, panel_size=16)
print(mosaic.size_cm)                                  # (38.4, 38.4)
print(plan.parts[0].color.name, plan.parts[0].count)   # häufigste Farbe
print(parts_csv(plan))
```

`mosaic.indices` ist ein `(Höhe, Breite)`-Array mit Indizes in
`mosaic.palette` — damit lässt sich jede weitere Ausgabe selbst bauen.

## Eigene Palette

Nützlich, wenn nur bestimmte Farben vorrätig sind oder eigene Preise/IDs
gepflegt werden sollen:

```json
{
  "id": "meine-kiste",
  "name": "Was ich zuhause habe",
  "colors": [
    { "name": "White", "name_de": "Weiß", "hex": "#FFFFFF", "lego_id": 1, "bricklink_id": 1 },
    { "name": "Black", "name_de": "Schwarz", "hex": "#05131D", "lego_id": 26, "bricklink_id": 11 }
  ]
}
```

`name` und `hex` sind Pflicht, alles andere optional. Farben ohne
`bricklink_id` landen nicht in der Wanted-List, sondern als Kommentar am
Anfang der XML-Datei — damit sie beim Bestellen nicht untergehen.

## Wie die Farbzuordnung funktioniert

1. Bild wird per Lanczos auf das Stud-Raster verkleinert; jeder Stud ist damit
   der Mittelwert seines Bildbereichs und nicht ein herausgegriffener Pixel.
2. Zuordnung passiert in **CIE Lab** (D65), nicht in RGB — dort entsprechen
   euklidische Abstände deutlich besser der wahrgenommenen Farbdifferenz.
   Sonst wandern z. B. dunkle Blautöne gern nach Schwarz.
3. Für die Suche wird einmalig eine 64³-Nachschlagetabelle über den RGB-Raum
   gebaut. Dadurch bleibt auch die pixelweise Fehlerdiffusion schnell:
   48x48 in unter einer Sekunde, 160x160 in etwa zwei.

## Tests

```sh
pip install -e ".[web,dev]"
pytest
```

## Genauigkeit der Farb- und Teiledaten

Die RGB-Werte der Palette folgen den öffentlich dokumentierten LDraw-/
Rebrickable-Näherungen für LEGO-Farben. Sie sind gut genug für die
Farbzuordnung, aber keine Messwerte — echte Steine weichen je nach Charge und
Lichtsituation ab. Farb-IDs und Teilenummern sind nach demselben Stand
eingetragen.

**Vor dem Bestellen** bei BrickLink oder Pick a Brick prüfen, ob es das
gewählte Element in der gewünschten Farbe tatsächlich gibt: die Verfügbarkeit
von 1x1-Rundfliesen unterscheidet sich je Farbe erheblich, und einzelne
Farben sind zeitweise gar nicht zu bekommen. `stueckliste.csv` enthält dafür
alle IDs in einer Spalte.
