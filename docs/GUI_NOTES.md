# GUI_NOTES — Markdown-Umwandler (native macOS, PyObjC/AppKit)

Environment verified against: **pyobjc-core 12.2.2** + **pyobjc-framework-Cocoa
12.2.2**, **Python 3.14.4** (Homebrew, arm64), macOS 26.6.2. All selector
names / return types below were confirmed by running
`NSView.instanceMethodSignatureForSelector_(b"…")` and `.methodReturnType()`
in a throwaway venv, and by constructing the real window in `smoke.py`.

## Files
- `main.py` — the complete GUI (runs standalone given `converters` + PyObjC).
- `smoke.py` — best-effort smoke test (imports + instantiates, no event loop).
- `.venv/` — throwaway venv used only to verify the API; not a deliverable.

## Architecture (the one non-obvious decision)
PyObjC turns **every** Python method defined on an `NSObject` subclass into an
ObjC selector and **validates its prototype at class-definition (import)
time**: a method whose name has no trailing `_` maps to a 0-argument selector,
so a Python function that takes arguments on an ObjC subclass raises
`BadPrototypeError` on import (e.g. `_collect(self, paths)` → "expects 0
arguments, has 1"). This killed the first design (all logic on `AppDelegate`).

Fix: split by ObjC-ness.
- `DropView(NSView)` — only single-argument drag/action callbacks
  (`draggingEntered_`, `performDragOperation_`, `chooseFiles_`, …).
- `AppDelegate(NSObject)` — one 0-context callback
  (`applicationShouldTerminateAfterLastWindowClosed_`).
- `Controller` (plain Python, **not** an `NSObject` subclass) — all stateful
  logic (`build_ui`, `start_conversion`, `_collect`, `_run_worker`, …). No
  selector synthesis, no prototype checks.

`DropView._controller` is an ordinary Python attribute (PyObjC objects keep a
Python `__dict__`); the drag/action methods call it with plain Python calls.

## PyObjC selector conventions used
- Trailing `:` in a selector → trailing `_` in the Python method name, one per
  colon: `performDragOperation:` → `performDragOperation_`,
  `readObjectsForClasses:options:` → `readObjectsForClasses_options_`.
- 0-argument selectors keep the bare name (no `_`): `runModal`, `center`,
  `firstResponder`, `title`, `string`, `pasteboard`, `URLs`, `contentView`,
  `textContainer`, `textStorage`, `mainMenu`, `activateIgnoringOtherApps_`
  (that last one *is* 1-arg → `_`).
- Return types come from the SDK metadata; verified encodings:
  - `draggingEntered:` / `draggingUpdated:` → `Q` (NSUInteger = `NSDragOperation`)
  - `prepareForDragOperation:` / `performDragOperation:` → `B` (BOOL)
  - `draggingExited:` / `registerForDraggedTypes:` → `v` (void)
  - `acceptsFirstResponder` → `B` (0-arg)

## Drag-and-drop (the `validateDraggedTypes:proposedLocation:` correction)
`validateDraggedTypes:proposedLocation:` is **not** an AppKit selector
(confirmed: `instanceMethodSignatureForSelector_` returns `None`; even
`validateDrop:` is absent from NSView's PyObjC metadata). The real accept/reject
hooks are `draggingEntered:` / `draggingUpdated:` / `prepareForDragOperation:`
(they return an `NSDragOperation`). `DropView` returns `NSDragOperationCopy`
(=1) only when the dragging pasteboard carries file URLs, else `0`
(`NSDragOperationNone`) to reject. It registers once, in `build_ui`:
`drop.registerForDraggedTypes_([NSPasteboardTypeFileURL])`.

Reading the dragging pasteboard (in `performDragOperation_`):
```
urls = sender.pasteboard().readObjectsForClasses_options_([NSURL], None) or []
paths = [Path(u.path()) for u in urls if u.scheme() == "file"]
```
Gotchas, all verified:
- The classes argument must be a **Python list** `[NSURL]`. A Python set
  `{NSURL}` or `NSSet.setWithArray_([NSURL])` / `NSSet.setWithObject_(NSURL)`
  raise `NSInvalidArgumentException: objectAtIndex: unrecognized` — only the
  plain list bridges to the `NSSet` parameter correctly.
- `NSURL.isFileURL_` does **not** exist; filter with `u.scheme() == "file"`.
- `u.path()` returns the POSIX filesystem path (handles spaces).

## File inputs — all funnel into `Controller.start_conversion(paths)`
1. **Drop** → `DropView.performDragOperation_` (above).
2. **Button** "Dateien wählen…" → `NSButton.buttonWithTitle_target_action_(
   "Dateien wählen…", drop, "chooseFiles:")` → `DropView.chooseFiles_` opens an
   `NSOpenPanel` with `setCanChooseFiles_(True)`, `setCanChooseDirectories_(True)`,
   `setAllowsMultipleSelection_(True)`, reads `panel.URLs()` after
   `panel.runModal() == NSOKButton` (=1; `NSCancelButton`=0).
3. **⌘V paste** → main-menu item `Einfügen` / action `pasteFiles:` / key `v` /
   **nil target**. `DropView.pasteFiles_` reads the general pasteboard:
   file URLs via `readObjectsForClasses_options_([NSURL], None)`; else plain
   text via `stringForType_(NSPasteboardTypeString)`, one path per line
   (`file://…` → `NSURL.URLWithString_(line).path()`, bare path → `Path(line)`).

### Why ⌘V reaches DropView
The menu item has a **nil target**, so AppKit walks the responder chain from the
first responder. Two things make that reliable:
- `DropView` overrides `acceptsFirstResponder` → `True` (a plain `NSView`
  reports `NO`; confirmed empirically), and `build_ui` calls
  `window.makeFirstResponder_(drop)`. `makeFirstResponder_` is an **NSWindow**
  method (not on NSView).
- The log `NSTextView` is a descendant of the scroll view, which is a descendant
  of `drop`, so even when the text view grabs first responder, `drop` stays in
  the chain and still receives `pasteFiles:` (the text view responds to
  `paste:`, not `pasteFiles:`).

## Directory expansion & filtering (`Controller._collect`)
- A directory expands to its **top-level** files only — no recursion
  (nested dirs are skipped; their files are not collected).
- Supported children → conversion queue; unsupported children → counted as
  `ignored` and logged (`⚠  Ignoriert …`). An empty/unreadable dir counts as
  one ignored item.
- Dedup by `Path.resolve()` (a file reached via both an explicit drop and a
  dir is converted once).
- Supported = `converters.is_supported(path)`.

## Threading model (AppKit is main-thread-only)
- Conversion runs on `threading.Thread(target=self._run_worker, daemon=True)`.
- Every UI touch from the worker goes through `Controller._on_main(fn)`:
  - on the main thread → `fn()` inline;
  - off-main → `NSOperationQueue.mainQueue().addOperationWithBlock_(fn)`.
  The main queue drains on the main run loop that `NSApp.run()` drives — this is
  the "bounce to the main thread" mechanism (documented in `main.py`).
- A `threading.Lock` guards `_pending`, `_busy`, and the ok/failed/ignored
  counters (worker writes, main thread reads at `_finish`).
- Drops/selections arriving while a worker runs are appended to `_pending`; the
  worker drains in a loop, so later files are not dropped and the run is not
  double-started.
- **Errors never crash or stop the run**: `_process_batch` catches
  `converters.ConversionError` and a defensive `Exception`, logs a `✗` line,
  and continues to the next file.

## The `converters` seam
At the top of `main.py`, before importing:
```
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
```
then `from converters import convert_file, is_supported, ConversionError`.
If that fails, the app prints a one-line German diagnostic to stderr and
`sys.exit(1)` (a clean message beats a traceback — the app cannot work without
the converter). Contract: `is_supported(path)->bool`;
`convert_file(path)->list[Path]` (the created `.md` path(s); xlsx → one per
sheet) raising `ConversionError`. The `.md` is written next to the original —
the converters module's job, not the GUI's. `smoke.py` injects a stub
`converters` into `sys.modules` before importing `main` to exercise the seam.

## App lifecycle & other AppKit gotchas
- `NSApplication.delegate` is **weak** in modern AppKit → module-level strong
  refs `_DELEGATE` / `_CONTROLLER` keep the delegate, controller, and window
  (referenced by the controller) alive.
- `app.setActivationPolicy_(NSApplicationActivationPolicyRegular)` so a
  script-run app gets a menu bar (not an agent).
- Window: `initWithContentRect_styleMask_backing_defer_` with
  `Titled|Closable|Miniaturizable` (=1|2|4), `setReleasedWhenClosed_(False)`.
- **Alerts and `NSOpenPanel.runModal()` must run on the main thread** —
  `_show_alert` / `_alert_no_supported` are dispatched via `_on_main`;
  `chooseFiles_` is invoked from the button (already main thread).
- `NSTextView` in `NSScrollView`: the resizable setters are
  `setVerticallyResizable_` / `setHorizontallyResizable_` (the
  `isVerticallyResizable` property is **read-only** in PyObjC); log appends use
  `textStorage().appendAttributedString_(…)` + `scrollToEndOfDocument_(None)`.
- `AppKit.NSApp` is a *distinct* proxy from `NSApplication.sharedApplication()`;
  `main.py` uses the local `app` instance throughout, never `NSApp`.
- `NSObject` is imported from **Foundation** (not `objc`; `from objc import
  NSObject` raises ImportError).

## Layout (content 560×400, y from the bottom)
hint 560-wide centered at y=336; button centered at y=300; status at y=272;
scrolling log 536×252 at y=12 (width/height sizable). Autoresizing masks keep
the hint/button/status pinned to the top edge and the log stretching. The window
is the whole drop zone; note a drop landing exactly on the button/hint/log
subview is hit-tested to that subview and (not being a file drag destination)
rejected — drops on the surrounding area work. (AppKit hit-tests the topmost
view and does not bubble a rejected drag to the parent.)

## smoke.py
Runs in the venv: `.venv/bin/python3 smoke.py`. It (1) imports `main` (validates
every AppKit import / constant / class def), (2) checks the drag selector
return-type encodings and that `validateDraggedTypes:proposedLocation:` is
absent, (3) instantiates `DropView`, (4) unit-checks `_collect` (top-level-only
expansion, no recursion, dedupe, unsupported/empty-dir counting) on real temp
files, (5) builds the full app + window (verifies title, content view,
first-responder wiring, menu), and (6) drives `start_conversion` end-to-end on a
temp `.docx` with the stub converter (worker thread converts, `_ok == 1`, not
left busy). **It does not** run `NSApp.run()` and cannot simulate a real
`NSDraggingInfo` drag, so the actual drop event path is exercised only at the
method/signature level. Result: **SMOKE: PASS**.
