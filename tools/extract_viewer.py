#!/usr/bin/env python3
"""extract_viewer.py — regenerate web/viewer/{index.html,app.css,app.js} from
strike_remap.py's embedded HTML, deterministically.

The web viewer reuses the editor's UI verbatim (see AGENTS.md § Web viewer).
Historically that extraction was a manual discipline ("re-extract if the Python
UI changes") and it drifted twice. This tool makes it mechanical:

    python tools/extract_viewer.py            # rewrite the three files in place
    python tools/extract_viewer.py --check    # exit non-zero if files differ
                                              #   from a fresh extraction (CI gate)

Extraction rules (the ONLY permitted divergences from the embedded HTML):
  app.css    = embedded <style> contents + the appended viewer-mode override
               block (everything from VIEWER_CSS_MARKER to EOF is preserved
               from the existing file — it is viewer-authored, not extracted).
  app.js     = embedded <script> contents + the three window.VIEWER guard
               lines inserted at the top of the functions in VIEWER_GUARDS.
  index.html = embedded HTML with the <style> block replaced by a <link> to
               app.css, the <script> block replaced by the engine.js module
               tag, and the <title> suffixed with " — Viewer".

If strike_remap.py changes in a way these rules can't handle (a guard function
renamed, a second <style>/<script> block, the CSS marker deleted), this tool
fails loudly instead of writing something wrong — update the rules here in the
same commit as the UI change.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "web" / "viewer"

# Everything from this exact line to EOF in web/viewer/app.css is preserved
# verbatim across re-extractions (the documented viewer-only CSS block).
VIEWER_CSS_MARKER = "/* ── viewer-mode overrides (added, not extracted) ── */"

# function-name → guard line inserted as its first statement. The match is on a
# top-level `function NAME(` / `async function NAME(` declaration line.
VIEWER_GUARDS = {
    "previewInstrument": "  if (window.VIEWER) return;  // viewer-mode: no audio in v1 (/api/wav 404s)",
    "setParam": "  if (window.VIEWER) return;  // viewer-mode: pad detail is read-only display",
    "assignInstrument": "  if (window.VIEWER) return;  // viewer-mode: read-only, no pad assignment",
    "openStartScreen": "  if (window.VIEWER) return;  // viewer-mode: no server session to start from",
}

HEAD_COMMENT = """<!-- Extracted from strike_remap.py's HTML string by tools/extract_viewer.py —
     DO NOT hand-edit index.html/app.css/app.js; edit strike_remap.py and re-run
     the extractor. engine.js (viewer-authored) provides a client-side read-only
     replacement for the Python /api server via fetch interception. -->"""

ENGINE_BLOCK = """<!-- engine.js installs the /api fetch interceptor and sets window.VIEWER BEFORE
     app.js runs, then dynamically injects app.js as a classic script so the
     extracted frontend (global funcs + inline onclick) works unchanged. -->
<script type="module" src="engine.js"></script>"""

TITLE_SRC = "<title>Strike Pro Remapper</title>"
TITLE_DST = "<title>Strike Pro Remapper — Viewer</title>"


class ExtractError(RuntimeError):
    pass


def load_embedded_html() -> str:
    spec = importlib.util.spec_from_file_location("sr", ROOT / "strike_remap.py")
    sr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sr)
    return sr.HTML


def split_embedded(html: str) -> tuple[str, str]:
    """Return (style_contents, script_contents); fail unless exactly one of each."""
    styles = re.findall(r"<style>(.*?)</style>", html, re.S)
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    if len(styles) != 1 or len(scripts) != 1:
        raise ExtractError(
            f"expected exactly one <style> and one <script> block in the embedded "
            f"HTML, found {len(styles)} / {len(scripts)} — update extract_viewer.py"
        )
    return styles[0], scripts[0]


def make_app_css(style: str, existing_css: str) -> str:
    idx = existing_css.find(VIEWER_CSS_MARKER)
    if idx == -1:
        raise ExtractError(
            "web/viewer/app.css is missing the viewer-mode marker line "
            f"({VIEWER_CSS_MARKER!r}) — the appended override block must be "
            "preserved; restore the marker before re-extracting"
        )
    viewer_block = existing_css[idx:]
    return style.rstrip("\n") + "\n\n" + viewer_block


def make_app_js(script: str) -> str:
    lines = script.splitlines(keepends=True)
    out = []
    inserted: dict[str, int] = {name: 0 for name in VIEWER_GUARDS}
    decl_re = re.compile(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(")
    for line in lines:
        out.append(line)
        m = decl_re.match(line)
        if m and m.group(1) in VIEWER_GUARDS:
            name = m.group(1)
            if not line.rstrip().endswith("{"):
                raise ExtractError(
                    f"guard target function {name!r} no longer opens its brace on "
                    "the declaration line — update extract_viewer.py's insertion rule"
                )
            out.append(VIEWER_GUARDS[name] + "\n")
            inserted[name] += 1
    bad = {n: c for n, c in inserted.items() if c != 1}
    if bad:
        raise ExtractError(
            f"guard insertion expected exactly one match per function, got {bad} — "
            "a guarded function was renamed/removed in strike_remap.py; update "
            "VIEWER_GUARDS (and web/viewer/engine.js if routes changed)"
        )
    return "".join(out)


def make_index_html(html: str, style: str, script: str) -> str:
    if TITLE_SRC not in html:
        raise ExtractError(f"embedded HTML is missing {TITLE_SRC!r}")
    out = html.replace(TITLE_SRC, TITLE_DST, 1)
    out = out.replace(
        f"<style>{style}</style>",
        HEAD_COMMENT + '\n<link rel="stylesheet" href="app.css">',
        1,
    )
    out = out.replace(f"<script>{script}</script>", ENGINE_BLOCK, 1)
    return out


def extract() -> dict[Path, str]:
    html = load_embedded_html()
    style, script = split_embedded(html)
    existing_css = (VIEWER / "app.css").read_text(encoding="utf-8")
    return {
        VIEWER / "app.css": make_app_css(style, existing_css),
        VIEWER / "app.js": make_app_js(script),
        VIEWER / "index.html": make_index_html(html, style, script),
    }


def main() -> int:
    check = "--check" in sys.argv[1:]
    try:
        files = extract()
    except ExtractError as e:
        print(f"extract_viewer.py: ERROR: {e}", file=sys.stderr)
        return 1

    stale = []
    for path, content in files.items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current != content:
            stale.append(path)
            if not check:
                path.write_text(content, encoding="utf-8", newline="\n")

    rel = [p.relative_to(ROOT).as_posix() for p in stale]
    if check:
        if stale:
            print(
                "extract_viewer.py --check: STALE viewer extraction: "
                + ", ".join(rel)
                + "\nstrike_remap.py's embedded UI changed without re-extracting. "
                "Run: python tools/extract_viewer.py  (then commit the result)",
                file=sys.stderr,
            )
            return 1
        print("OK: web/viewer extraction matches strike_remap.py")
        return 0

    print("rewrote: " + (", ".join(rel) if rel else "nothing (already in sync)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
