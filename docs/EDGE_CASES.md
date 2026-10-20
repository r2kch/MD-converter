# EDGE_CASES — Expected behavior for special cases (MDConverter)

Ground rule for **every** case below: a defect is isolated to **one file**. A
clear `ConversionError` message appears in the **app log** (and in the run
summary/alert), that file is **skipped**, and the **remaining** files continue
to be processed. The app never **crashes** because of a single bad file.

See `NAMING.md` for naming/output details.

---

## 1. Password-protected / encrypted `.docx`

- **Expected:** `ConversionError`, file skipped, rest continues.
- **Message (actual):** `Could not read '<name>': not a readable DOCX (it may
  be corrupt or password-protected). Details: ...`
- The converter maps the `BadZipFile` / `OSError` / XML errors raised on an
  encrypted part into this clean message — never a raw stacktrace in the GUI.

## 2. `.pdf` with no text layer (image-only) — no OCR

- **Expected:** **FAIL** (no OCR in this project), file skipped, rest continues.
- **Message (actual, normative):** `PDF '<name>' has no extractable text layer
  (scanned/image-only). OCR is not supported by this tool.`
- Detection: extracted text is empty/whitespace (after trim). No silent empty
  `.md`, no 0-byte output.

## 3. Zero-byte / corrupt file

- **Expected:** `ConversionError`, file skipped, rest continues.
- **Message (actual):** for a truncated zip (docx/xlsx/pptx) → `Could not read
  '<name>': not a readable <DOCX|XLSX|PPTX> (it may be corrupt or
  password-protected). Details: ...`; for an unparseable PDF → `Could not read
  '<name>': not a readable PDF (...)`. A missing / non-regular path → `File not
  found or not a regular file: <path>`.

## 4. Non-ASCII / very long file names

- **Non-ASCII:** the stem is taken **1:1** (`Übersicht 2026.docx` →
  `Übersicht 2026.md`). No "unreadable" behavior, no crash.
- **Very long:** the output path component must stay ≤ **255 bytes** (APFS).
  If it is longer, the stem is shortened **at a character boundary** (never
  mid-UTF-8-sequence) so that `<stem>[….N][-sheet].md` ≤ 255 bytes, then the
  usual suffix search runs. **Expected:** the (shortened) file is written and
  the shortening is visible in the app log. No crash, no silent rejection.
  (If the OS refuses the write, it surfaces as `Could not write '<path>' ...`.)

## 5. Output directory not writable (read-only location)

- **Expected:** `ConversionError`, file skipped, rest continues.
- **Message (actual):** `Could not write '<path>' (target directory not
  writable?): ...`
- The app does **not** try to write elsewhere or to overwrite.

## 6. Duplicate sheet names in one workbook

- Two sheets with an identical name (or identical after sanitizing, see
  `NAMING.md` §4) → the **suffix rule** applies in workbook order:
  `data-Q1.md`, `data-Q1.1.md`, …
- **Expected:** no collision, no overwrite, deterministic.
- App log: one `✓  <file> → <path>` line per produced sheet file.

## 7. A dropped folder

- **Expected:** only the **top-level** files of the folder are processed,
  **not recursively**. Subdirectories are ignored.
- Each processed file writes into **its own** parent directory (here: the
  folder).

## 8. Mixed batch (supported + unsupported)

- **Expected:** supported files (`docx/xlsx/pptx/pdf`) are converted;
  **unsupported** ones (`.doc`, `.xls`, `.ppt`, `.md`, images, …) are
  **ignored** and only **counted**.
- Log line per ignored name: `⚠  Ignored (not supported): <name>`.
- Run summary (alert): `<n> converted successfully, <m> failed, <k> ignored`.

## 9. `.md` dropped as input

- **Expected:** treated as an **unsupported format** and ignored (counted in
  the summary), not used as a source.
- Important for the collision rule: a pre-existing `<stem>.md` (e.g. made by
  the user) counts as **taken** for the suffix search → the new output becomes
  `<stem>.1.md`.

---

## Error-message style (normative)

- Language: **English**.
- Channel: **app log** (one line per file) + a **run summary/alert** at the end
  (e.g. "3 converted successfully, 1 failed, 1 ignored").
- Exactly **one** line per skipped file with the file name + reason.
- **Never** a raw stacktrace in the GUI; **never** a crash from a single
  file; **never** silent disappearance.
