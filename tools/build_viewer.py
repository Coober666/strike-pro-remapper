#!/usr/bin/env python3
"""build_viewer.py — deterministic, stdlib-only bundler for the single-file web viewer.

Assembles dist/strike_viewer.html: a SINGLE self-contained file that works opened
directly from file:// (double-click). Inlines app.css, the factory catalog +
fingerprints JSON as global assignments, a flattened/de-modularized concatenation
of the JS parser modules + engine.js, and app.js — replacing the <link>/<script
type=module> pair in web/viewer/index.html.

Why: file:// blocks fetch() and ES-module imports, so everything must be inlined
and de-modularized. engine.js prefers window.FACTORY_CATALOG / window.FACTORY_
FINGERPRINTS globals over dev fetches, and contains `// [bundle-strip-begin]` /
`// [bundle-strip-end]` marker comments around blocks that only make sense in the
dev (multi-file, module) build and must be removed here.

Usage:
    python tools/build_viewer.py            # writes dist/strike_viewer.html
    python tools/build_viewer.py --check     # build + validate, exit non-zero on failure
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
VIEWER = WEB / "viewer"
DIST = ROOT / "dist"
OUT_PATH = DIST / "strike_viewer.html"

MAX_SIZE_BYTES = 8 * 1024 * 1024  # 8 MB cap enforced by --check

# JS files concatenated (in order) into the single flattened <script>.
JS_MODULE_ORDER = [
    WEB / "bytes.js",
    WEB / "skt.js",
    WEB / "sin.js",
    WEB / "similar.js",
    VIEWER / "engine.js",
]

STRIP_BEGIN = "[bundle-strip-begin]"
STRIP_END = "[bundle-strip-end]"

IMPORT_LINE_RE = re.compile(r"^\s*import\s")
EXPORT_PREFIX_RE = re.compile(r"^(\s*)export\s+(const|function|class|let|var)\b")
# Top-level (unindented) declarations, post-export-stripping — used to detect name
# collisions once every module shares one flattened scope. Matches `async function`
# and `function*` too (a plain `function\s` prefix check would miss those).
TOPLEVEL_DECL_RE = re.compile(
    r"^(?:async\s+)?(const|let|var|function\*?|class)\s+([A-Za-z_$][\w$]*)"
)

# After stripping, any of these patterns remaining means a module changed shape
# in a way this bundler doesn't know how to flatten — fail loudly rather than
# silently ship broken output.
LEFTOVER_MODULE_SYNTAX_RE = re.compile(
    r"^\s*export\s*\{|^\s*export\s+default\b|^\s*import\s*\(|^\s*import\s"
)


class BuildError(RuntimeError):
    """Raised when the bundler detects output that would be broken."""


def strip_bundle_markers(text: str, source_name: str) -> str:
    """Remove all `// [bundle-strip-begin]` ... `// [bundle-strip-end]` blocks
    (inclusive of both marker lines)."""
    lines = text.splitlines(keepends=True)
    out = []
    depth = 0
    for i, line in enumerate(lines):
        has_begin = STRIP_BEGIN in line
        has_end = STRIP_END in line
        if has_begin and has_end:
            raise BuildError(
                f"{source_name}:{i + 1}: begin and end markers on the same line "
                "— bundler expects them on separate lines"
            )
        if has_begin:
            depth += 1
            continue
        if has_end:
            if depth == 0:
                raise BuildError(
                    f"{source_name}:{i + 1}: stray end marker with no matching begin"
                )
            depth -= 1
            continue
        if depth == 0:
            out.append(line)
    if depth != 0:
        raise BuildError(f"{source_name}: unbalanced bundle-strip markers (depth={depth})")
    return "".join(out)


def flatten_module(path: Path) -> tuple[str, list[tuple[str, int]]]:
    """De-modularize one JS file: drop import lines, strip export prefixes,
    remove bundle-strip-marked blocks. Returns (transformed source, [(name, lineno)]
    for each top-level const/let/var/function/class declaration found)."""
    text = path.read_text(encoding="utf-8")
    text = strip_bundle_markers(text, path.name)

    out_lines = []
    decls = []
    for lineno, line in enumerate(text.splitlines(keepends=True), start=1):
        if IMPORT_LINE_RE.match(line):
            # Drop the whole import line — flattening puts every module in one
            # scope, so cross-module references already resolve directly.
            continue
        line = EXPORT_PREFIX_RE.sub(r"\1\2", line)
        m = TOPLEVEL_DECL_RE.match(line)
        if m:
            decls.append((m.group(2), lineno))
        out_lines.append(line)
    return "".join(out_lines), decls


def scan_toplevel_decls(text: str) -> list[tuple[str, int]]:
    decls = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        m = TOPLEVEL_DECL_RE.match(line)
        if m:
            decls.append((m.group(2), lineno))
    return decls


def build_flattened_script() -> tuple[str, list[tuple[str, Path, int]]]:
    """Returns (flattened source, [(name, path, lineno)] top-level decls) — the
    decls are returned (not just checked here) because app.js also lands in the
    same runtime global scope as this script (sibling classic <script> tags share
    one `window`), so the collision check must span both; see build_html()."""
    parts = []
    all_decls = []  # (name, path, lineno)
    for path in JS_MODULE_ORDER:
        if not path.exists():
            raise BuildError(f"missing expected source module: {path}")
        transformed, decls = flatten_module(path)
        parts.append(f"// ==== {path.relative_to(ROOT).as_posix()} ====\n")
        parts.append(transformed)
        parts.append("\n")
        for name, lineno in decls:
            all_decls.append((name, path, lineno))
    flattened = "".join(parts)

    # Fail loudly if any other import/export syntax survived the transform —
    # that means a module changed shape and the bundler needs updating.
    for i, line in enumerate(flattened.splitlines(), start=1):
        if LEFTOVER_MODULE_SYNTAX_RE.match(line):
            raise BuildError(
                "leftover module syntax after flattening at flattened-script "
                f"line {i}: {line.strip()!r} — a source module changed shape; "
                "update tools/build_viewer.py's transform"
            )

    if "</script" in flattened.lower():
        raise BuildError(
            "flattened JS modules contain a literal '</script' sequence — "
            "cannot safely inline without breaking out of the <script> tag"
        )

    return flattened, all_decls


def check_no_declaration_collisions(all_decls: list[tuple[str, Path, int]]) -> None:
    """Sibling classic <script> tags all share one global `window` scope, so a
    top-level const/let/var/function/class name declared in more than one of the
    bundle's scripts is a real collision — at best a silent shadow-and-break (the
    JS_MODULE_ORDER flattened script and app.js), at worst a SyntaxError (two
    `const`/`let`/`class` of the same name within the SAME flattened script).
    Catch it here with a clear message instead of shipping broken output."""
    seen: dict[str, tuple[Path, int]] = {}
    for name, path, lineno in all_decls:
        if name in seen:
            prev_path, prev_lineno = seen[name]
            raise BuildError(
                f"duplicate top-level declaration '{name}' would collide once "
                f"bundled: {prev_path.relative_to(ROOT).as_posix()}:{prev_lineno} "
                f"and {path.relative_to(ROOT).as_posix()}:{lineno} — a source "
                "module changed shape; rename one or de-duplicate before bundling"
            )
        seen[name] = (path, lineno)


def load_app_js() -> str:
    app_js_path = VIEWER / "app.js"
    text = app_js_path.read_text(encoding="utf-8")
    # app.js was originally embedded inside a <script> tag in strike_remap.py's
    # Python HTML string, so by construction it can't contain a literal
    # "</script" sequence — but verify rather than assume, per the same
    # fail-loudly rule as the flattened modules.
    if "</script" in text.lower():
        raise BuildError("web/viewer/app.js contains a literal '</script' sequence")
    return text


def js_string_safe_json(obj) -> str:
    """Serialize obj as compact JSON safe to embed inside a <script> tag.

    `</script` (or `<!--`) must never appear unescaped inside inlined <script>
    content. The JSON is emitted as a JS object-literal assignment, so `</` can
    only occur inside a JSON string value — `<\\/` is a byte-identical escape
    there (both in JSON string-literal syntax and, once parsed, produces the
    same JS string), so replacing `</` -> `<\\/` is always safe and never
    changes the decoded value.
    """
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    raw = raw.replace("</", "<\\/")
    raw = raw.replace("<!--", "<\\!--")
    return raw


def load_catalog_instruments() -> dict:
    path = ROOT / "factory_catalog.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    instruments = data.get("instruments")
    if not isinstance(instruments, dict):
        raise BuildError(
            "factory_catalog.json missing an 'instruments' dict — "
            "engine.js expects window.FACTORY_CATALOG to be that dict directly"
        )
    return instruments


def load_fingerprints() -> dict:
    path = ROOT / "factory_fingerprints.json"
    return json.loads(path.read_text(encoding="utf-8"))


def build_html() -> tuple[str, dict]:
    """Returns (html, size_breakdown_bytes)."""
    index_html = (VIEWER / "index.html").read_text(encoding="utf-8")
    app_css = (VIEWER / "app.css").read_text(encoding="utf-8")

    if "<link rel=\"stylesheet\" href=\"app.css\">" not in index_html:
        raise BuildError("index.html: expected <link> tag for app.css not found")
    if "<script type=\"module\" src=\"engine.js\"></script>" not in index_html:
        raise BuildError("index.html: expected <script type=module> tag for engine.js not found")
    if "</style>" in app_css.lower() or "</script" in app_css.lower():
        raise BuildError("app.css contains a literal '</style' or '</script' sequence")

    catalog_instruments = load_catalog_instruments()
    fingerprints = load_fingerprints()

    catalog_js = js_string_safe_json(catalog_instruments)
    fingerprints_js = js_string_safe_json(fingerprints)

    flattened_script, flattened_decls = build_flattened_script()
    app_js = load_app_js()
    app_js_path = VIEWER / "app.js"

    # app.js joins the SAME global scope as the flattened script (sibling classic
    # <script> tags share one `window`), so a name declared at top level in both
    # silently shadows-and-breaks (e.g. engine.js's internal checkPaths() helper
    # vs. app.js's global checkPaths() — the router would recurse into itself).
    all_decls = list(flattened_decls)
    for name, lineno in scan_toplevel_decls(app_js):
        all_decls.append((name, app_js_path, lineno))
    check_no_declaration_collisions(all_decls)

    style_block = f"<style>\n{app_css}\n</style>"
    data_block = (
        "<script>\n"
        f"window.FACTORY_CATALOG = {catalog_js};\n"
        f"window.FACTORY_FINGERPRINTS = {fingerprints_js};\n"
        "</script>"
    )
    libs_block = f"<script>\n{flattened_script}\n</script>"
    app_block = f"<script>\n{app_js}\n</script>"

    html = index_html.replace(
        '<link rel="stylesheet" href="app.css">', style_block
    )
    html = html.replace(
        '<script type="module" src="engine.js"></script>',
        f"{data_block}\n{libs_block}\n{app_block}",
    )

    sizes = {
        "css": len(style_block.encode("utf-8")),
        "data": len(data_block.encode("utf-8")),
        "libs": len(libs_block.encode("utf-8")),
        "app": len(app_block.encode("utf-8")),
    }
    sizes["total"] = len(html.encode("utf-8"))
    return html, sizes


def fmt_bytes(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.2f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def run_check(html: str, sizes: dict) -> None:
    """--check: validate the flattened script with node --check, re-verify no
    leftover module syntax, and enforce the total-size cap. Raises BuildError
    (caller exits non-zero) on any failure."""
    # Re-extract the flattened <script> block (the "libs" block: the 3rd of the
    # 3 <script> tags we inserted) to run it through node --check in isolation.
    m = re.search(
        r"<script>\n(// ==== web/bytes\.js ====.*?)\n</script>", html, re.S
    )
    if not m:
        raise BuildError("--check: could not locate flattened script block in output for validation")
    flattened_script = m.group(1)

    for i, line in enumerate(flattened_script.splitlines(), start=1):
        if LEFTOVER_MODULE_SYNTAX_RE.match(line):
            raise BuildError(
                f"--check: leftover module syntax survived into final output at line {i}: {line.strip()!r}"
            )

    with tempfile.TemporaryDirectory(prefix="strike_viewer_check_") as tmp:
        js_path = Path(tmp) / "flattened.js"
        js_path.write_text(flattened_script, encoding="utf-8")
        try:
            proc = subprocess.run(
                ["node", "--check", str(js_path)],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except FileNotFoundError:
            raise BuildError("--check: 'node' executable not found on PATH")
        if proc.returncode != 0:
            raise BuildError(
                "--check: node --check reported a syntax error in the flattened script:\n"
                + proc.stdout + proc.stderr
            )

    if sizes["total"] >= MAX_SIZE_BYTES:
        raise BuildError(
            f"--check: total size {fmt_bytes(sizes['total'])} exceeds the "
            f"{fmt_bytes(MAX_SIZE_BYTES)} cap"
        )


def main() -> int:
    check_mode = "--check" in sys.argv[1:]

    try:
        html, sizes = build_html()
    except BuildError as e:
        print(f"build_viewer.py: ERROR: {e}", file=sys.stderr)
        return 1

    if check_mode:
        try:
            run_check(html, sizes)
        except BuildError as e:
            print(f"build_viewer.py --check: ERROR: {e}", file=sys.stderr)
            return 1
        # --check builds to a temp location only — does not touch dist/.
        with tempfile.TemporaryDirectory(prefix="strike_viewer_check_") as tmp:
            tmp_out = Path(tmp) / "strike_viewer.html"
            tmp_out.write_text(html, encoding="utf-8")
            print(f"OK: built + validated at {tmp_out} ({fmt_bytes(sizes['total'])})")
    else:
        DIST.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(html, encoding="utf-8")
        print(f"wrote {OUT_PATH.relative_to(ROOT)}")

    print("size breakdown:")
    for key in ("css", "data", "libs", "app", "total"):
        print(f"  {key:<6} {fmt_bytes(sizes[key]):>10}  ({sizes[key]:,} bytes)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
