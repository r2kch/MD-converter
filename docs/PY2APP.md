# PY2APP — kurzes Assessment (Python 3.14.4, macOS 26.6.2 arm64)

Aufgabe: prüfen, ob `py2app` auf **diesem** Python läuft (Venv +
`pip install py2app` + import + deklarierte 3.14-Support). **Kein** voller
py2app-Build. Empfehlung: Hand-Built-Bundle vs py2app.

## Gemacht

Wegwerf-Venv unter `/tmp/mdconv/packaging/.venv_py2app`:

```sh
/opt/homebrew/bin/python3 -m venv .venv_py2app
.venv_py2app/bin/pip install py2app
```

Ergebnisse:

| Check | Ergebnis |
|-------|----------|
| `pip install py2app` | **OK** — `py2app-0.28.10` installiert (Deps: `altgraph 0.17.5`, `macholib 1.16.4`, `modulegraph 0.19.7`, `packaging 26.3`, `setuptools 84.2.0` — alle reines Python, **kein** pyobjc nötig zum Installieren) |
| `import py2app` | **OK** auf Python 3.14.4 |
| `from py2app import build_app` | **OK** |
| `Requires-Python` (Metadata) | `>=3.10` (keine Obergrenze → 3.14 erlaubt) |
| Changelog | **0.28.9 „Add support for python 3.14“**; dazu „py2app does not support free-threaded python“ |
| Free-threaded? | `Py_GIL_DISABLED = 0` → **GIL-aktiviert**, die Free-threaded-Sperre greift hier nicht |
| pyobjc 3.14-Wheels (Dry-Run) | `pip install --dry-run pyobjc` → „Would install pyobjc-12.2.2 …“ → **3.14-Wheels vorhanden**, ein PyObjC-py2app-Build ist also nicht durch fehlende Wheels blockiert |

## Korrektur zur Erwartung

Die Aufgabenstellung erwartete, **Hand-Built gewinne auf einer 3.14-Basis,
weil py2app 3.14 nicht unterstützt.** Das ist **nicht** der Fall: py2app
**0.28.9+ unterstützt 3.14 explizit**, installiert und importiert sauber auf
3.14.4, und pyobjc liefert 3.14-Wheels. py2app ist hier also **nicht**
Python-versions-geblockt.

## Empfehlung

**Hand-Built-Bundle** (Launcher + Venv im Bundle, wie in `build_app.sh`).

**Einzeilige Begründung:** Nicht weil py2app 3.14 nicht kann (es kann),
sondern weil die App winzig ist (`main.py` + `converters.py`) und ein
transparenter Venv-Launcher `requirements.txt` als einzige Wahrheit nutzt,
während py2app statische Import-Analyse + Rezepte über einem PyObjC-
und Converter-Stack (openpyxl/python-docx/python-pptx/pdf) laufen müsste —
größerer, schwerer zu debuggender Build, mehr Versions-Sensitivität, ohne
Nutzen für eine App dieser Größe.
