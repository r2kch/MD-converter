# VERDICT — Office/PDF → Markdown converter library choices

Self-tested end-to-end on this machine. All four formats convert to clean
GitHub-Flavored Markdown; `converters.py` + `requirements.txt` are ready to
integrate.

## (a) Python to pin: **3.14** (verified 3.14.4)

- Interpreter: `/opt/homebrew/bin/python3` → **Python 3.14.4**, macOS 26.6.2
  arm64.
- The "3.14 is too new for wheels" risk **did not materialize**: every key
  C-extension dependency has a prebuilt **arm64** wheel for 3.14, confirmed
  with `pip install --only-binary :all:`. No `brew install python@3.13`
  fallback was needed.
- Wheels that installed cleanly on 3.14: `pymupdf 2.0`, `pymupdf4llm 2.0`
  (+ `pymupdf_layout 2.0`), `lxml 6.1.3`, `python-pptx 1.0.2`, `mammoth
  1.13.0`, `python-docx 1.2.0` (samples only), `openpyxl 3.1.5`, `reportlab
  5.0.1` (samples only), `markdownify 1.2.3`, `html2text 2025.4.15`,
  `pandas 3.0.6`, `pyobjc-core 12.2.2`, `pyobjc-framework-Cocoa 12.2.2`.
- Recommendation: pin the app venv to **CPython 3.14** (`>=3.14,<3.15`). If
  the team later wants a longer-lived baseline, 3.13 would also work (all the
  same libs carry 3.13 wheels), but there is no need to drop down — 3.14 is
  green here.

## (b) Chosen library per format (+ version)

| Format | Chosen toolchain | Version(s) | Why |
|--------|------------------|-----------|-----|
| `.docx` | **mammoth → markdownify** | mammoth 1.13.0, markdownify 1.2.3 | mammoth gives clean *semantic* HTML (headings, `<strong>/<em>`, `<ul>/<ol>`, `<table>`); markdownify gives correct ATX headings, `-` bullets, `1.` lists, and **GFM tables** with `table_infer_header=True`. A small style map `p[style-name='Title'] => h1` turns the Word *Title* into an `h1`. Rejected: html2text (renders lists indented with `*`, trailing spaces) and python-docx alone (no table→markdown helper). |
| `.pptx` | **python-pptx** (direct) | python-pptx 1.0.2 | Only sane choice. Iterate `slide.shapes`; title placeholder (`placeholder_format.type == PP_PLACEHOLDER.TITLE`) → `#` heading; other placeholders → `-` bullets; other text boxes → plain paragraphs. No speaker notes (per spec). Note: python-pptx returns fresh wrappers each access, so `sh is slide.shapes.title` is *not* reliable — match on the placeholder `type` instead. |
| `.xlsx` | **openpyxl** (`data_only=True`) | openpyxl 3.1.5 | Direct worksheet access → one `.md` per sheet, GFM table per sheet, first data row as header. `data_only=True` returns cached values. Rejected pandas (heavier, no per-sheet control, still needs openpyxl under the hood for xlsx). |
| `.pdf` | **pymupdf4llm** (+ `pymupdf`) | pymupdf4llm 2.0, PyMuPDF 2.0 | Purpose-built PDF→markdown: detects headings/structure from font size & layout, text layer only (no OCR). `pymupdf.set_messages(stream=io.StringIO())` silences its "Document parser messages" block (which here includes a "RapidOCR is missing" note). Rejected raw `pymupdf` text (no heading/structure detection). |
| GUI | **pyobjc-core + pyobjc-framework-Cocoa** | 12.2.2 / 12.2.2 | For the other agent. See (e). |

## (c) Sample markdown excerpts (from the generated samples, proving it works)

`doc.docx` → `doc.md`:
```
# Quarterly Report

# Overview

This is **bold insight** and *italic detail*.

## Details

Revenue grew in every region this quarter.

- Unordered points:
- North
- South
- East

1. Ordered steps:
2. Plan
3. Execute
4. Review

| Region | Q1 | Q2 |
| --- | --- | --- |
| North | 100 | 120 |
```

`deck.pptx` → `deck.md`:
```
# Intro

- Welcome
- Agenda

# Results

- Growth
- Profit
- Reach

# Next Steps

- Plan
- Ship
```

`book.xlsx` (sheet "Revenue") → `book-Revenue.md` (one file per sheet; also
`book-Costs.md`):
```
# Revenue

| Region | Q1 | Q2 |
| --- | --- | --- |
| North | 100 | 120 |
| South | 80 | 95 |
| East | 60 | 70 |
```

`paper.pdf` → `paper.md` (heading detected from the larger font):
```
# Quarterly Report

Revenue grew in every region this quarter. Bold regions: North, South, East.
```

## (d) Caveats

- **docx / nested tables:** GFM cannot express nested tables; mammoth flattens
  cell content and markdownify emits a single flat GFM table. Deeply nested
  docx tables lose their nesting.
- **docx / Title style:** the Word *Title* paragraph is mapped to `h1` via the
  style map `p[style-name='Title'] => h1`; custom/unknown paragraph styles fall
  back to mammoth's defaults.
- **docx / list lead-ins:** a paragraph styled as a list item is rendered as a
  bullet. (In the sample the lead-in lines were themselves `List Bullet`
  styled, so they show as bullets — a sample artifact, not a converter bug.)
- **pdf / heading heuristics:** headings are *inferred* from font size and
  layout by pymupdf4llm; they are not guaranteed to match intent. Lines that
  are close together vertically can be merged into one paragraph (see the two
  sentences merging in `paper.md`).
- **pdf / no OCR:** scanned or image-only PDFs (no text layer) raise
  `ConversionError` ("no extractable text layer"). Text PDFs only, per spec.
- **pdf / console notice:** pymupdf4llm emits a "Document parser messages"
  block to its message stream; this is redirected to a throwaway buffer. At
  most one stray blank line can reach `stdout` from an internal `print()` —
  it never reaches the `.md` file content.
- **xlsx / formula cells:** `data_only=True` shows the **cached value**, not
  the formula; cells never opened/calculated by Excel may be empty.
- **xlsx / naming:** sheet names are sanitized for the filename exactly per
  NAMING.md — replace every char NOT in `[A-Za-z0-9-]` (spaces included) with a
  single `-`, collapse consecutive `-` runs to one, trim leading/trailing `-`,
  else `Sheet` (e.g. `Notes & More` → `Notes-More`, `  a  b  ` → `a-b`,
  `###` → `Sheet`). The in-file `#` heading uses the raw sheet name. Ragged
  rows are padded and fully-empty rows dropped; `|` in cells is escaped.
- **pptx:** per spec, speaker notes are not exported.

## (e) pyobjc (GUI) confirmation

On Python 3.14.4, both import cleanly:

```
objc 12.2.2
AppKit import OK: True
Foundation import OK: True
```

`pyobjc-core==12.2.2` and `pyobjc-framework-Cocoa==12.2.2` — confirmed
importable (`import objc, AppKit, Foundation`; `NSString`, `NSBundle` resolve).

## Self-test result

`self_test.py` (run in the venv) is **GREEN**: `is_supported` accept/reject,
all four samples convert to non-empty `.md` next to the original, xlsx yields
one file per sheet, re-converting creates `doc.1.md` without overwriting
`doc.md`, `unique_md_path` returns the next free name, and corrupt
docx/xlsx, blank (textless) pdf, missing file, and unsupported `.txt` each
raise `ConversionError`. See the passing run in the agent log.
