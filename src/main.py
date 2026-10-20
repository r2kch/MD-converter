#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Markdown Converter
==================
A small native macOS drop-zone window (AppKit via PyObjC) that turns
Office/PDF files into Markdown.

This file is the GUI only. All file conversion is delegated to the sibling
``converters`` module (see docs/GUI_NOTES.md for the exact seam):

    from converters import convert_file, is_supported, ConversionError

The user feeds files in three ways, all funnelled into one entry point,
``Controller.start_conversion(paths)``:

  * dropping file URL(s) onto the window   (NSView drag-and-drop)
  * the "Choose files…" button             (NSOpenPanel, files + dirs)
  * pasting paths / file-URLs (Cmd-V)      (NSPasteboard general)

Conversion runs on a background ``threading.Thread``; every AppKit touch is
bounced back to the main thread (AppKit is main-thread-only). Errors never
crash the app or stop the remaining files.

Drag-and-drop note
------------------
The drop view registers for ``public.file-url`` only (see
``build_ui`` -> ``registerForDraggedTypes_``), so AppKit calls the drag
callbacks for a drag only when that type is offered. The hover callbacks
(``draggingEntered:`` / ``draggingUpdated:`` / ``prepareForDragOperation:``)
therefore accept unconditionally and do NOT touch the dragging pasteboard:
querying the *live* dragging pasteboard (``canReadObjectForClasses:`` /
``readObjectsForClasses:``) stalls the main thread during a real Finder drag,
so the drag was never accepted and the drop never fired. All pasteboard access
happens once, in ``performDragOperation:`` (on drop).

Architecture note
-----------------
PyObjC turns every Python method defined on an ``NSObject`` subclass into an
ObjC selector and validates the prototype (trailing ``_`` count == ``:`` count
== argument count). That is why the drag/action callbacks live on the ``NSView``
subclass (all single-argument, trailing-underscore) and ``AppDelegate`` is a
thin ``NSObject`` with one callback, while ALL stateful logic lives in the
plain-Python ``Controller`` (no selector synthesis, no prototype checks).
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

# --- Seam to `converters` --------------------------------------------------
# When bundled as a .app, converters.py sits next to main.py. Make it
# importable regardless of the current working directory BEFORE the import.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

try:
    from converters import convert_file, is_supported, ConversionError
except Exception as _exc:  # ImportError or a broken converters module
    # A clear diagnostic beats a bare traceback at startup: without the
    # converter the app cannot do its job.
    print(f"Markdown Converter: could not import 'converters': {_exc}",
          file=sys.stderr)
    sys.exit(1)

from AppKit import (
    NSAlert,
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered,
    NSButton,
    NSColor,
    NSDragOperationCopy,
    NSFont,
    NSMakePoint,
    NSMakeRect,
    NSMakeSize,
    NSMenu,
    NSMenuItem,
    NSOKButton,
    NSOpenPanel,
    NSPasteboard,
    NSPasteboardTypeFileURL,
    NSPasteboardTypeString,
    NSScrollView,
    NSTextAlignmentCenter,
    NSTextField,
    NSTextView,
    NSView,
    NSViewHeightSizable,
    NSViewMaxXMargin,
    NSViewMinXMargin,
    NSViewMinYMargin,
    NSViewWidthSizable,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSAttributedString, NSOperationQueue, NSObject, NSURL


def file_urls_from_pasteboard(pasteboard):
    """Return the file URLs (list[NSURL]) on ``pasteboard``, else [].

    ``readObjectsForClasses:options:`` with the NSURL class is the modern way
    to pull objects off a pasteboard (we pass a *Python list* of the class —
    PyObjC bridges it to the NSSet argument). If that comes back empty, fall
    back to the property list stored under ``public.file-url`` (how Finder
    writes a file drag). We keep only file:// URLs as a defensive filter.

    NOTE: this DECODES objects. Call it only once per drop/paste, never from
    the drag-hover callbacks (they must not touch the live dragging pasteboard
    at all; see :class:`DropView`).
    """
    try:
        urls = list(pasteboard.readObjectsForClasses_options_([NSURL], None) or [])
    except Exception:
        urls = []
    if not urls:
        try:
            plist = pasteboard.propertyListForType_(NSPasteboardTypeFileURL)
        except Exception:
            plist = None
        for item in plist or []:
            if isinstance(item, NSURL):
                urls.append(item)
            elif isinstance(item, (str, bytes)):
                s = item.decode("utf-8") if isinstance(item, bytes) else item
                u = NSURL.URLWithString_(s)
                if u is not None:
                    urls.append(u)
    return [u for u in urls if (u.scheme() or "") == "file"]


def dragging_pasteboard(sender):
    """Return the dragging ``NSPasteboard`` from a drag ``sender``, else None.

    macOS exposes it as ``draggingPasteboard`` on the modern
    ``NSDragDestination`` (a zero-arg method in this build); the classic
    ``NSDraggingInfo`` name was ``pasteboard``. Probe both, tolerating
    property- or method-style access, so the drop keeps working across builds.
    Called once on drop — never in the hover path, where touching the live
    dragging pasteboard stalls the main thread (see :class:`DropView`).
    """
    for attr in ("draggingPasteboard", "pasteboard"):
        try:
            val = getattr(sender, attr, None)
        except Exception:
            val = None
        if val is None:
            continue
        if isinstance(val, NSPasteboard):
            return val
        if callable(val):
            try:
                res = val()
            except Exception:
                continue
            if isinstance(res, NSPasteboard):
                return res
    return None


class DropView(NSView):
    """The window's content view: the drag-and-drop target.

    PyObjC maps an ObjC selector to a Python method name by turning each
    trailing ``:`` into a trailing ``_``, so ``draggingEntered:`` becomes
    ``draggingEntered_`` and the zero-argument ``runModal`` stays ``runModal``.

    The view is registered for ``public.file-url`` only, so the accept/reject
    hooks (``draggingEntered:`` / ``draggingUpdated:`` /
    ``prepareForDragOperation:``) fire only for file drags and return
    ``NSDragOperationCopy`` unconditionally, without touching the dragging
    pasteboard (a live drag-pasteboard query stalls the main thread). The file
    URLs are read only once, in ``performDragOperation:`` (on drop).
    """

    # The window sets this view as first responder so the Cmd-V menu item (nil
    # target, action pasteFiles:) is routed here through the responder chain.
    # A plain NSView reports acceptsFirstResponder == NO, so we override it.
    def acceptsFirstResponder(self):
        return True

    # -- NSDraggingDestination selectors (single-arg, trailing underscore) --
    # The view is registered for NSPasteboardTypeFileURL (build_ui ->
    # registerForDraggedTypes_), so AppKit invokes these callbacks ONLY for
    # drags that offer the file-url type. We must NOT touch the dragging
    # pasteboard in the hover path: canReadObjectForClasses / readObjects
    # stall the main thread on a live Finder drag. Accept unconditionally;
    # read the pasteboard only in performDragOperation_.
    def draggingEntered_(self, sender):
        return NSDragOperationCopy

    def draggingUpdated_(self, sender):
        return NSDragOperationCopy

    def prepareForDragOperation_(self, sender):
        return True

    # Called exactly once, on drop: the ONLY place the dragging pasteboard is
    # read. Decoding happens here (a brief pause on drop is acceptable).
    def performDragOperation_(self, sender):
        pb = dragging_pasteboard(sender)
        if pb is None:
            controller = self._controller
            if controller is not None:
                controller.set_status("Drop ignored: could not read the drag.")
            return False
        try:
            urls = file_urls_from_pasteboard(pb)
        except Exception:
            return False
        controller = self._controller
        if not urls:
            if controller is not None:
                controller.set_status("Drop ignored: no files received.")
            return False
        if controller is not None:
            n = len(urls)
            controller.set_status(f"Received {n} file{'s' if n != 1 else ''}.")
            controller.start_conversion([Path(u.path()) for u in urls])
        return True

    # -- user actions (button target + Cmd-V via the responder chain) -------
    def chooseFiles_(self, sender):
        controller = self._controller
        if controller is None:
            return
        panel = NSOpenPanel.alloc().init()
        panel.setCanChooseFiles_(True)
        panel.setCanChooseDirectories_(True)
        panel.setAllowsMultipleSelection_(True)
        panel.setTitle_("Choose Files")
        panel.setMessage_("Choose files or folders (.docx, .pptx, .xlsx, .pdf)")
        panel.setPrompt_("Choose")
        if panel.runModal() == NSOKButton:
            paths = [Path(u.path()) for u in panel.URLs()]
            if paths:
                controller.start_conversion(paths)

    def pasteFiles_(self, sender):
        controller = self._controller
        if controller is None:
            return
        pasteboard = NSPasteboard.generalPasteboard()
        paths = [Path(u.path()) for u in file_urls_from_pasteboard(pasteboard)]
        if not paths:  # fall back to plain-text paths / file:// lines
            text = pasteboard.stringForType_(NSPasteboardTypeString)
            if text:
                for line in text.splitlines():
                    line = line.strip().strip('"')
                    if not line:
                        continue
                    if line.startswith("file://"):
                        paths.append(Path(NSURL.URLWithString_(line).path()))
                    else:
                        paths.append(Path(line))
        if paths:
            controller.start_conversion(paths)
        else:
            controller.set_status("No files in the clipboard.")


class Controller:
    """Plain-Python brain: owns the window and drives the background
    conversion. NOT an ``NSObject`` subclass, so its methods stay ordinary
    Python (no ObjC selector synthesis / prototype validation)."""

    def __init__(self):
        self.window = None
        self._status = None
        self._log = None
        # Conversion state, guarded by _lock (worker thread writes, main
        # thread reads at the end).
        self._lock = threading.Lock()
        self._pending = []    # supported files queued for conversion
        self._busy = False    # a worker thread is currently running
        self._worker_done = threading.Event()  # set when the worker drains
        self._ok = 0
        self._failed = 0
        self._ignored = 0

    # -- main-thread dispatch -----------------------------------------------
    def _on_main(self, fn):
        """Run ``fn`` on the main thread.

        AppKit objects must only be touched from the main thread. Worker
        threads schedule UI updates through here; ``NSOperationQueue.mainQueue()``
        drains its blocks from the main run loop (the one ``NSApp.run()``
        drives). On the main thread it runs inline, so it is safe from either
        side. This is the documented "bounce to the main thread" mechanism.
        """
        if threading.current_thread() is threading.main_thread():
            fn()
        else:
            NSOperationQueue.mainQueue().addOperationWithBlock_(fn)

    # -- UI mutators (each bounces to the main thread) ----------------------
    def set_status(self, text):
        def do():
            if self._status is not None:
                self._status.setStringValue_(text)
        self._on_main(do)

    def _append_log(self, lines):
        if isinstance(lines, str):
            lines = [lines]

        def do():
            if self._log is None:
                return
            joined = "".join(line + "\n" for line in lines)
            # Pin the foreground on the appended run (black on the white
            # background set in build_ui).
            fg, _ = self._log_colors()
            attrs = {"NSForegroundColorAttributeName": fg}
            self._log.textStorage().appendAttributedString_(
                NSAttributedString.alloc().initWithString_attributes_(joined, attrs))
            self._log.scrollToEndOfDocument_(None)

        self._on_main(do)

    def _log_tail(self, n=30):
        """Last ``n`` lines of the log (call on the main thread)."""
        if self._log is None:
            return ""
        s = self._log.string() or ""
        if not s.strip():
            return ""
        lines = s.splitlines()
        if len(lines) > n:
            lines = ["…"] + lines[-n:]
        return "\n".join(lines)

    def _log_colors(self):
        """(Foreground, background) pair for the log: black on white, in every
        appearance.

        Measured, not assumed: in this PyObjC build the NSTextView draws every
        glyph black (#000000) no matter what foreground color is requested —
        per-run NSForegroundColorAttributeName, view setTextColor_, and the
        dynamic NSColor.textColor() all render black (verified by exporting the
        view to PDF and reading each span's color). The background color, by
        contrast, IS honored. The only lever that restores readability is a
        light background under the always-black text, so the log deliberately
        does not follow the window's appearance here.
        """
        return NSColor.blackColor(), NSColor.whiteColor()

    # -- UI construction -----------------------------------------------------
    def build_ui(self):
        self._build_menu()

        rect = NSMakeRect(0, 0, 560, 400)
        style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                 | NSWindowStyleMaskMiniaturizable)
        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False)
        window.setTitle_("Markdown Converter")
        window.setReleasedWhenClosed_(False)  # we hold the only Python ref
        self.window = window

        # The Dock / Finder icon comes from the bundle's CFBundleIconFile
        # (AppIcon.icns, see build_app.sh); this build's NSWindow does not
        # expose setIcon:, so no title-bar icon is set here.

        content_rect = window.contentRectForFrameRect_(rect)
        drop = DropView.alloc().initWithFrame_(content_rect)
        drop._controller = self  # plain Python attr, read by the action methods
        drop.registerForDraggedTypes_([NSPasteboardTypeFileURL])  # accept file drags
        window.setContentView_(drop)
        cw = content_rect.size.width

        # Drop hint (top, horizontally centered, sticks to the top edge).
        hint = NSTextField.labelWithString_(
            "Drop files here (.docx, .pptx, .xlsx, .pdf)")
        hint.setFont_(NSFont.boldSystemFontOfSize_(15))
        hint.setAlignment_(NSTextAlignmentCenter)
        hint.setFrame_(NSMakeRect(12, 336, cw - 24, 22))
        hint.setAutoresizingMask_(
            NSViewMinYMargin | NSViewMinXMargin | NSViewMaxXMargin)
        drop.addSubview_(hint)

        # "Choose files…" button (top, centered) -> DropView.chooseFiles_
        button = NSButton.buttonWithTitle_target_action_(
            "Choose files…", drop, "chooseFiles:")
        button.sizeToFit()
        bw = button.frame().size.width
        button.setFrameOrigin_(NSMakePoint((cw - bw) / 2.0, 300))
        button.setAutoresizingMask_(
            NSViewMinYMargin | NSViewMinXMargin | NSViewMaxXMargin)
        drop.addSubview_(button)

        # Status line (just above the log).
        status = NSTextField.labelWithString_("Ready.")
        status.setFont_(NSFont.systemFontOfSize_(12))
        status.setTextColor_(NSColor.secondaryLabelColor())
        status.setFrame_(NSMakeRect(12, 272, cw - 24, 18))
        status.setAutoresizingMask_(NSViewMinYMargin)
        drop.addSubview_(status)
        self._status = status

        # Read-only, scrolling log (bottom, stretches with the window).
        scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(12, 12, cw - 24, 252))
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)
        scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)

        log = NSTextView.alloc().initWithFrame_(scroll.contentView().bounds())
        log.setMinSize_(NSMakeSize(0, 0))
        log.setMaxSize_(NSMakeSize(10000, 10000))
        # The setters are setVerticallyResizable:/setHorizontallyResizable:
        # (the isVerticallyResizable property is read-only in PyObjC).
        log.setVerticallyResizable_(True)
        log.setHorizontallyResizable_(False)
        log.textContainer().setContainerSize_(
            NSMakeSize(scroll.contentView().bounds().size.width, 10000))
        log.textContainer().setWidthTracksTextView_(True)
        log.setAutoresizingMask_(NSViewWidthSizable)
        log.setRichText_(False)
        log.setEditable_(False)
        log.setSelectable_(True)  # copyable; Cmd-V still reaches DropView
        log.setFont_(NSFont.userFixedPitchFontOfSize_(11))
        # The log view renders its text black in every appearance in this
        # build (see _log_colors), so it gets a white background to stay
        # readable in both light and dark mode.
        fg, bg = self._log_colors()
        log.setTextColor_(fg)
        log.setBackgroundColor_(bg)
        log.setDrawsBackground_(True)
        scroll.setDocumentView_(log)
        drop.addSubview_(scroll)
        self._log = log

        window.center()
        window.makeKeyAndOrderFront_(None)
        window.makeFirstResponder_(drop)  # so Cmd-V reaches DropView directly

    def _build_menu(self):
        # Minimal main menu: app menu (Cmd-Q) + Edit menu (Cmd-V). The Cmd-V
        # item uses a nil target so AppKit walks the responder chain and finds
        # DropView.pasteFiles: (the window's first responder).
        main_menu = NSMenu.alloc().init()

        app_item = NSMenuItem.alloc().init()
        app_menu = NSMenu.alloc().initWithTitle_("Markdown Converter")
        app_menu.addItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit Markdown Converter", "terminate:", "q"))
        app_item.setSubmenu_(app_menu)
        main_menu.addItem_(app_item)

        edit_item = NSMenuItem.alloc().init()
        edit_menu = NSMenu.alloc().initWithTitle_("Edit")
        paste = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Paste", "pasteFiles:", "v")
        paste.setTarget_(None)
        edit_menu.addItem_(paste)
        edit_item.setSubmenu_(edit_menu)
        main_menu.addItem_(edit_item)

        NSApplication.sharedApplication().setMainMenu_(main_menu)

    # -- conversion entry point ---------------------------------------------
    def start_conversion(self, paths):
        """Filter ``paths`` to supported files and queue them for conversion.

        Called from the main thread by all three input paths. Directories are
        expanded to their TOP-LEVEL supported files only (no recursion);
        unsupported items are counted and logged, never raised.
        """
        files, ignored = self._collect(paths)
        if not files and not ignored:
            return
        if ignored:
            self._append_log(
                [f"⚠  Ignored (not supported): {p.name}" for p in ignored])
        if not files:
            # Defer to the main queue (not inline) so the modal alert is not
            # nested inside the drag session / open-panel callback that led here.
            n = len(ignored)
            NSOperationQueue.mainQueue().addOperationWithBlock_(
                self._alert_no_supported(n))
            return

        with self._lock:
            self._pending.extend(files)
            self._ignored += len(ignored)
            should_start = not self._busy
            if should_start:
                self._busy = True
                self._worker_done.clear()
        if should_start:
            self.set_status("Preparing conversion…")
            threading.Thread(target=self._run_worker, daemon=True).start()

    def _collect(self, paths):
        """Expand directories (top level only) and split into supported
        (files) / unsupported (ignored). Deduplicates by resolved path."""
        files, ignored = [], []
        seen = set()

        def add(p):
            rp = p.resolve()
            if rp in seen:
                return
            seen.add(rp)
            (files if is_supported(p) else ignored).append(p)

        for raw in paths:
            p = Path(raw)
            if p.is_dir():
                try:
                    children = sorted(p.iterdir(), key=lambda c: c.name.lower())
                except OSError:
                    children = []
                top_level_files = 0
                for c in children:
                    if c.is_file():  # nested dirs are NOT recursed
                        add(c)
                        top_level_files += 1
                if top_level_files == 0:
                    ignored.append(p)  # empty/unreadable dir counts as ignored
            else:
                add(p)
        return files, ignored

    # -- background worker ---------------------------------------------------
    def _run_worker(self):
        """Drains the pending queue on the worker thread; AppKit is only
        touched through _on_main."""
        while True:
            with self._lock:
                if not self._pending:
                    self._busy = False
                    break
                batch = self._pending
                self._pending = []
            self._process_batch(batch)
        self._worker_done.set()  # all queued files processed
        self._on_main(self._finish)

    def _process_batch(self, batch):
        total = len(batch)
        for i, path in enumerate(batch, 1):
            self.set_status(f"Converting {i} of {total} … ({path.name})")
            try:
                outputs = convert_file(path)
            except ConversionError as exc:
                self._note_result(path, False, str(exc))
            except Exception as exc:  # one bad file must not stop the rest
                self._note_result(path, False, f"Unexpected error: {exc!r}")
            else:
                self._note_result(path, True, [Path(o) for o in outputs])

    def _note_result(self, path, ok, detail):
        if ok:
            lines = ([f"✓  {path.name} → {o}" for o in detail]
                     if detail else [f"✓  {path.name}"])
        else:
            lines = [f"✗  {path.name}: {detail}"]
        self._append_log(lines)
        with self._lock:
            if ok:
                self._ok += 1
            else:
                self._failed += 1

    # -- completion (main thread) -------------------------------------------
    def _finish(self):
        with self._lock:
            ok, failed, ignored = self._ok, self._failed, self._ignored
            self._ok = self._failed = self._ignored = 0
        self.set_status("Done.")
        self._show_alert(ok, failed, ignored)

    def _show_alert(self, ok, failed, ignored):
        def do():
            alert = NSAlert.alloc().init()
            alert.setMessageText_("Conversion finished")
            summary = f"{ok} converted successfully, {failed} failed"
            if ignored:
                summary += f", {ignored} ignored"
            info = summary
            tail = self._log_tail()
            if tail:
                info += "\n\n" + tail
            alert.setInformativeText_(info)
            alert.runModal()  # blocks until dismissed; must be on the main thread
            if self.window is not None:
                self.window.makeKeyAndOrderFront_(None)

        self._on_main(do)

    def _alert_no_supported(self, n):
        def do():
            alert = NSAlert.alloc().init()
            alert.setMessageText_("No supported files")
            alert.setInformativeText_(
                f"{n} item{'s' if n != 1 else ''} ignored "
                "(only .docx, .pptx, .xlsx, .pdf).")
            alert.runModal()
            if self.window is not None:
                self.window.makeKeyAndOrderFront_(None)

        return do


class AppDelegate(NSObject):
    """Thin ObjC app delegate: quit when the last window closes. Kept free of
    argument-taking Python methods (PyObjC would synthesize selectors for
    them); all logic lives on the plain-Python ``Controller``."""

    def applicationShouldTerminateAfterLastWindowClosed_(self, sender):
        return True


# Strong references so the (weakly held) delegate / controller / window are
# not reclaimed: NSApplication.delegate is weak in modern AppKit.
_DELEGATE = None
_CONTROLLER = None


def main():
    global _DELEGATE, _CONTROLLER
    app = NSApplication.sharedApplication()
    # Running from a script: become a regular (menu-bar) app, not an agent.
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)

    controller = Controller()
    _CONTROLLER = controller
    controller.build_ui()

    delegate = AppDelegate.alloc().init()
    _DELEGATE = delegate
    app.setDelegate_(delegate)

    app.activateIgnoringOtherApps_(True)
    app.run()


if __name__ == "__main__":
    main()
