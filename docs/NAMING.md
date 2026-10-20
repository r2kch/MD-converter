# NAMING — Output-Namingspezifikation (MDConverter)

Diese Datei ist die **verbindliche** Spezifikation dafür, wie und wohin
`converters.py` die `.md`-Dateien benennt und schreibt. Alle anderen
Komponenten (GUI, Build, README) bauen auf diesem Verhalten auf.

Kurzprinzip: **Eine Quelldatei liegt → ihre `.md`-Ausgabe(en) landen im selben
Verzeichnis. Nie überschreiben, nie andernorts schreiben.**

---

## 1. Stiel (basename) ableiten

Der *Stiel* ist der Dateiname **ohne die letzte Erweiterung**.

- Die letzte Erweiterung = alles ab dem letzten `.` an — **außer** einem
  führender Punkt (denn eine Datei wie `.docx` hat keinen sichtbaren Stiel).
- Beispiel:

| Quelldatei          | Stiel         |
|---------------------|---------------|
| `report.docx`       | `report`      |
| `my.file.docx`      | `my.file`     |
| `data.xlsx`         | `data`        |
| `Übersicht 2026.pdf`| `Übersicht 2026` |

- **Sonderfall leerer Stiel** (Datei heißt nur wie `.docx`): Stiel := `document`.
- Der Stiel wird **1:1 übernommen** (Groß-/Kleinschreibung, Leerzeichen,
  Non-ASCII wie `Ü`, `ß`, CJK etc.) — APFS/HFS+ können Unicode.

---

## 2. Ausgabe-Verzeichnis

- **Immer das Elternverzeichnis der Quelldatei** (der Ort, an dem die Datei
  liegt bzw. abgelegt wurde). Nie ein anderer Ort, nie das Home-Verzeichnis.
- Bei einem **abgelegten Ordner**: Jede Datei wird in *eigenem*
  Elternverzeichnis ausgegeben; nur die **Top-Level**-Dateien des Ordners
  werden verarbeitet (nicht rekursiv).

---

## 3. Suffix-Suche — nie überschreiben

Für einen gewünschten Namen `N` im Ausgabe-Verzeichnis wird der erste freie
Name gesucht:

```
Kandidat = N
i = 1
solange (Kandidat existiert IM Ausgabe-Verzeichnis
          ODER ist in diesem Lauf bereits reserviert):
    i = i + 1
    Kandidat = <N mit -i-Suffix>
```

- Für **Single-File-Ausgaben** (`docx`, `pdf`, `pptx`):
  `base.md`, dann `base.1.md`, `base.2.md`, …
  (d. h. `<N mit Suffix>` = `<Stiel>.<i>.md`).
- **„existiert"** = eine Datei *oder ein Ordner* mit genau diesem Namen
  (Groß/Klein-Schreibung wird unterschieden, APFS-Default).
- **In-Memory-Reservierung:** Alle Namen, die *in diesem einen Lauf* bereits
  zugeteilt wurden, zählen als belegt — auch *bevor* die erste davon auf
  Platte liegt. So bleiben z. B. gleichnamige Sheets in einem Workbook
  deterministisch eindeutig (siehe §4).

Die reservierten Namen jedes Laufs sammeln sich in einer Menge
`reserved: set[str]`, die vor jeder Prüfung auch noch den Kandidaten enthält.

---

## 4. Excel: eine `.md` pro Blatt

Für `.xlsx` gibt es **pro Blatt eine eigene Datei**:

```
<Stiel>-<SheetSan>.md
```

wobei `SheetSan = sanitize(<Blattname>)`, verarbeitet **in Workbook-Reihenfolge**.

### Sanitize-Algorithmus

1. Jeder Charakter, der **nicht** in `[A-Za-z0-9-]` ist, wird zu `-`
   (also Leerzeichen, `&`, Umlaute, Satzzeichen — alles → `-`).
2. Aufeinanderfolgende `-` werden zu einem einzelnen `-` zusammengefasst.
3. Leitende/abschließende `-` werden entfernt.
4. Ist das Ergebnis leer → `Sheet`.

| Blattname            | SheetSan      |
|----------------------|---------------|
| `Q1`                 | `Q1`          |
| `Notes & More`       | `Notes-More`  |
| `Übersicht`          | `bersicht`    |
| `   ` (nur Leerzeichen)| `Sheet`     |
| `a--b`               | `a-b`         |

> **Achtung / bewusste Abweichung:** Die ursprüngliche Aufgabenstellung
> nannte die zu behaltende Zeichengruppe `[A-Za-z0-9 _-]` (Leerzeichen
> behalten). Der dort **gelockte** Worked-Example
> `Notes & More` → `data-Notes-More.md` verlangt aber, dass Leerzeichen zu
> `-` werden. **Diese Spezifikation folgt dem Worked-Example** (es ist
> normativ). Konsequenz: Leerzeichen im Blattnamen werden zu `-`.

### Duplikate nach Sanitize

Zwei verschiedene Blätter können auf denselben Namen laufen (z. B. `Q1 `
und `Q1`, oder `Notes & More` und `Notes, More` → beide `Notes-More`).
Dann greift **die gewöhnliche Suffix-Suche** aus §3 in der Reihenfolge des
Workbooks:

- 1. Blatt → `data-Notes-More.md`
- 2. Blatt → `data-Notes-More.1.md`

### Suffix-Regel bei Excel

Die Suffix-Suche wirkt auf den **gesamten** Excel-Ausgabenamen:
`data-Q1.md`, `data-Q1.1.md`, `data-Q1.2.md`, … (die `-Q1`-Teil bleibt,
nur der numerische Kollisions-Suffix wird hochgezählt).

---

## 5. Beispiel: sehr lange Dateinamen

APFS erlaubt max. **255 Bytes pro Pfad-Componente** (Dateiname inkl.
`.md`). Verhält sich so:

- Das End-`File`-Komponente muss ≤ 255 Bytes bleiben.
- Ist sie länger, wird der **Stiel am Ende verkürzt** — an einer
  **Charakter-Grenze** (niemals mitten in einem UTF-8-Sequenz) — so weit,
  dass `<Stiel>[.Suffix][-SheetSan].md` ≤ 255 Bytes ist.
- Danach läuft die gewöhnliche Suffix-Suche (§3) wie immer.
- Kein Crash, keine stillschweigende Ablehnung — die Datei wird (verkürzt)
  ausgegeben; die Verkürzung ist im App-Log sichtbar.

---

## 6. Fehlverhalten (Rechte / schreibgeschützt)

- **Ausgabe-Verzeichnis nicht schreibbar** (read-only Ort): Die Datei wird
  **übersprungen** — mit klarer `ConversionError`-Meldung
  („Zielordner ist nicht schreibbar: `<pfad>`“), die im App-Log + Alert
  erscheint. Die **übrigen** Dateien werden weiterverarbeitet.
- **Nie** wird eine bestehende Datei überschrieben, **nie** in ein anderes
  Verzeichnis ausgelichen, **nie** stillschweigend ein vorhandenes `.md`
  ersetzt.
- Der Fehler ist pro Datei isoliert: ein einzelner Defekt stoppt nie den
  ganzen Lauf.

---

## 7. Worked Examples (verbindlich)

| Ausgang                                             | Ergebnis(en)                                   |
|-----------------------------------------------------|------------------------------------------------|
| `report.docx` (keine `.md` vorhanden)               | `report.md`                                    |
| `report.docx`, `report.md` existiert                | `report.1.md`                                  |
| `report.docx`, `report.md` + `report.1.md` existieren | `report.2.md`                                |
| `data.xlsx`, Sheets `Q1`, `Notes & More`            | `data-Q1.md`, `data-Notes-More.md`             |
| `data.xlsx`, Sheets `Q1`, `Q1` (Duplikat)           | `data-Q1.md`, `data-Q1.1.md`                   |
| `data.xlsx`, Sheets `Q1`, `Notes & More`, `Notes, More` | `data-Q1.md`, `data-Notes-More.md`, `data-Notes-More.1.md` |
| `presentation.pptx`                                 | `presentation.md`                              |
| `scan.pdf` (nur Text)                               | `scan.md`                                      |
| `scan.pdf` (nur Bild, kein Text)                    | **FAIL**: „Kein Text extrahierbar – OCR nicht unterstützt“ |
| `report.md` (als *Input* abgelegt)                  | wird **ignoriert** (`.md` ist kein Quellsformat) |

Alle `.md` erscheinen **im selben Verzeichnis** wie die jeweilige Quelldatei.
