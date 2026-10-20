# MDConverter

**MDConverter** is a small macOS app (arm64) that converts Office and PDF
files to **Markdown**. Drop files into the window — drag & drop, the
"Choose files" button, or paste with ⌘V — and the app converts them and
writes the `.md` result **directly next to the original file**.

> The app is **unsigned** (no Apple Developer certificate), built
> **locally**, and runs on its **own Python venv** that is **bundled inside
> the `.app`**. No Apple account is required.

---

## Requirements

- **macOS** (arm64; tested here on macOS 26).
- **Homebrew** and **Homebrew Python**:
  ```sh
  brew install python3
  ```
  The build uses `/opt/homebrew/bin/python3` by default (here: Python 3.14).
  Which Python the library stack actually needs is noted as a comment in
  `requirements.txt` — the build accepts the Python pinned there (see
  "Building" → `PYTHON_BIN`).
- **No** Apple Developer account, **no** signing, **no** notarization.

---

## Repository layout

```
MDConverter/
  src/main.py           # PyObjC GUI (window, drop, log/alert)
  src/converters.py     # conversion logic + naming/output
  requirements.txt      # pinned dependencies
  build_app.sh          # builds MDConverter.app (this file)
  README.md             # this file
  MDConverter.app/      # built artifact (can be gitignored)
```

---

## Building

```sh
./build_app.sh
```

The script is **idempotent**: every run rebuilds `MDConverter.app` from
scratch (venv in the bundle + libraries + launcher). It:

1. creates a **venv in the bundle** at
   `MDConverter.app/Contents/Frameworks/.venv`,
2. installs `requirements.txt` **into that venv**,
3. copies `src/main.py` + `src/converters.py` into `Contents/Resources/`
   (they sit side by side there so `main.py` can import `converters`),
4. generates an `Info.plist` + a small **launcher**
   (`Contents/MacOS/MDConverter`).

**Use a different Python** (if `requirements.txt` pins another):

```sh
./build_app.sh /path/to/python3        # as the 1st argument
# or
PYTHON_BIN=/path/to/python3 ./build_app.sh
```

**Also install to `~/Applications`:**

```sh
./build_app.sh --install
```

---

## Launching

- **Double-click** `MDConverter.app` (or `open MDConverter.app`). Because the
  app is **built locally**, it carries **no quarantine attribute** — so it
  launches **directly**, without macOS asking.
- **If macOS still warns** (e.g. a copy that was quarantined during an
  AirDrop/network/download transfer): **right-click** the `.app` →
  **"Open"** → **"Open"**. *Why:* the app is unsigned. macOS reports
  "developer cannot be verified" for a **quarantined, unsigned** app. A
  locally built `.app` is not quarantined, so this warning usually does not
  appear on a normal double-click.
- **See console output** (helpful for debugging):
  ```sh
  ./MDConverter.app/Contents/MacOS/MDConverter
  ```

> **After a Homebrew Python update** (e.g. `brew upgrade python@3.14`)
> rebuild: `./build_app.sh`. The venv symlinks into the Homebrew
> interpreter; if the Python path changes, the old build is broken.

---

## Usage

1. Launch the app (double-click).
2. Feed files — **drag & drop** into the window, via the **"Choose files"
   button**, or by **pasting (⌘V)**.
3. The app converts and writes the `.md` **next to the original file**.

**Supported inputs:** `.docx`, `.xlsx`, `.pptx`, `.pdf` (text PDFs only).
**Not supported:** legacy formats `.doc`, `.xls`, `.ppt`, and images/`.md`.

### Where output lands + naming rule

- Output **always in the same folder** as the source file.
- Word/PowerPoint/PDF: `<name>.md`. If `<name>.md` already exists,
  `<name>.1.md`, then `<name>.2.md`, … — **never overwritten**.
- Excel: **one file per sheet** → `<name>-<Sheet>.md` (the sheet name is
  sanitized: only `A-Za-z0-9-` kept, everything else → `-`, runs collapsed,
  edges trimmed; empty → `Sheet`).
- Details + examples: see `NAMING.md`.

Examples:

| Input | Output |
|---------|--------|
| `report.docx` | `report.md` |
| `report.docx`, `report.md` exists | `report.1.md` |
| `data.xlsx` with sheets `Q1`, `Notes & More` | `data-Q1.md`, `data-Notes-More.md` |

### Limitations (important)

- **Text PDFs only, no OCR** — an image-only PDF fails with
  "No extractable text - OCR is not supported".
- **Modern formats only** `.docx` / `.xlsx` / `.pptx`; **no**
  `.doc`/`.xls`/`.ppt`.
- **Excel → one file per sheet** (not a single combined file).
- **PowerPoint without speaker notes** (notes are not carried over).
- The app is **unsigned** and intended for **local use only**.

---

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| **Wrong Python version** at build | Use the Python pinned by `requirements.txt`: `./build_app.sh /path/to/python3` or `PYTHON_BIN=…`. Rebuild after a `brew upgrade`. |
| **Venv in bundle missing / launcher reports "venv missing"** | Re-run `./build_app.sh`. |
| **Missing wheel / pip error** | Usually a version mismatch: set the Python version from `requirements.txt` (`PYTHON_BIN=…`). Possibly `brew install python@3.14`. |
| **Target folder not writable** | Output sits next to the source; the directory must be writable (e.g. not read-only / not `/System`). See `EDGE_CASES.md`. |
| **Encrypted / password-protected `.docx`** | Remove the protection in the source document and re-drop. The file is skipped, the rest continues. |
| **Image PDF (scans only)** | **Not** supported (no OCR) — clear message, file skipped. |
| **macOS: "can't be opened"** | Right-click → **"Open"** → **"Open"** (occurs when a copy was quarantined). |
| **Only legacy formats (`.doc`/`.xls`/`.ppt`)** | Not supported — save as `.docx`/`.xlsx`/`.pptx` first. |

---

## Security & unsigned

- The app is built **locally, unsigned** — there is **no** Apple
  certificate and **no** notarization.
- For the normal local double-click that is unproblematic (no quarantine
  attribute).
- Do **not** use it to "force through" foreign/quarantined copies of the app
  from other machines; for a quarantined copy: right-click → Open.
- All conversion/naming errors are shown in the app log + as a summary
  (details: `EDGE_CASES.md`).
