# Installation and accessibility review

This follow-up updates the download handoff to merged main `45c210d`, tests the
source package in an isolated Linux environment, and fixes observed accessibility
problems. It does not establish physical mobile, hardware or screen-reader acceptance.

## Installation evidence

The exact [merged-main source artifact](https://github.com/Coober666/strike-pro-remapper/actions/runs/38628752928/artifacts/11924419832)
was checked in a fresh Python 3.13 slim Debian container, unprivileged UID 65534,
with no network, a read-only image and read-only artifact/script mounts. Only a
temporary filesystem was writable. No project checkout, virtual environment or
host site-packages were available to the application.

- ZIP SHA-256 and all 73 payload hashes matched.
- Extracted paired editor/toolkit assets loaded.
- A disposable kit saved; a later unsaved change produced a distinct recovery copy
  on normal Stop. Application payload files were unchanged.
- Missing Tk produced the documented terminal alternative, without a traceback.
- The Linux image is pinned to
  `python@sha256:8d9d0b8bcf6506481eae4907c18f5e3e7902e629f5f6d684f9e7c32e85e3ddf0`.

`tools/check_source_package.py` repeats these checks against an actual source ZIP
and its `.sha256.txt` sidecar using only the standard library. CI runs it inside
the same offline container before uploading source beta artifacts. This is
headless Linux software evidence, not a Linux desktop or Pi USB acceptance test.

The [Windows artifact](https://github.com/Coober666/strike-pro-remapper/actions/runs/38628752928/artifacts/11924998329)
also passed the new `tools/check_windows_clean.ps1` harness locally: checksum,
1,045 payload hashes, bundled-runtime probe, save/recovery/import/export/report,
windowed launcher/demo and unchanged payload after use. The harness invokes no
Python, Node or Git command and restricts child PATH to System32. All writes use
a newly created temporary library. No MIDI port is opened or message sent.

**Clean Windows OS acceptance remains open.** Windows Sandbox is unavailable on
the test computer; the local harness run does not remove development software or
prove behavior on a fresh installation. Get `tools/check_windows_clean.ps1` from
this revision's GitHub source tree (it is not inside the application ZIP). The
next tester can run it without installing a development environment:

```powershell
powershell -NoProfile -File .\tools\check_windows_clean.ps1 -Archive "C:\Downloads\strike-remapper-windows-x64-45c210d5a0772f5c5ad34be73becec968e88e924.zip" -ResultPath "C:\Users\Public\strike-check.json"
```

Keep the matching checksum sidecar beside the inner application ZIP. The result
records runtime/build identity; temporary evidence is retained at the printed
path. Record Windows version, whether this was a clean VM/computer, first-launch
prompts, and the result using [H6](HANDS_ON_ACCEPTANCE.md). The scripted test does
not replace manually opening the editor and checking normal startup/Stop.

## Accessibility changes and verification

An axe-core 4.14.0 audit with WCAG 2 A/AA and 2.1 AA rules found unnamed pad
controls and insufficient secondary-text contrast on Start, Pad and Sounds.
Keyboard inspection additionally found focus lost after parameter rerenders,
Space intercepted before button activation, and an FX overlay without native
dialog keyboard behavior. The changes:

- Associate generated pad/FX controls with visible row names, including distinct
  filter mode/cutoff names and FX section names; label map customization and copy/swap.
- Preserve the currently focused parameter through its rerender, including layer
  rack controls. Another control focused while a request settles stays selected.
- Keep Space available to focused buttons/links and use native kit-list buttons.
- Use a named native Kit FX dialog for focus containment, Escape from inputs and
  return to the keyboard opener; maintain the existing kit mutation/Undo behavior.
- Raise secondary-text contrast and Start keyboard-focus visibility.
- Announce action/error feedback in a polite status region; per-hit MIDI updates
  remain visual so incoming notes do not continually interrupt reading.

The final automated audit reported no violations in the eight inspected states:
Start, Pad, expanded map customization, Kit FX, Sounds, Kit Balance, Setlists and
MIDI toolkit. Twelve focused Chromium/WebKit cases cover keyboard edits, delayed
responses after moving focus, button
Space, FX focus/closing, failed-download announcements and a 640×450 CSS viewport
(the layout equivalent of 200% zoom on a 1280×900 window). Desktop FX and narrow
layout screenshots were visually inspected. This is a bounded audit, not a full
WCAG certification or a real screen-reader test; unvisited dialogs and OS/browser
zoom behavior still require acceptance.

The handoff deliberately pins the verified merged build. Accessibility changes
in this follow-up need their own passing PR/package build before being described
as included in those downloads.
