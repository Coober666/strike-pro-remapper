# Windows beta acceptance record — 2026-10-13

## Verified locally

Windows 10 x64, bundled Python 3.11.9, python-rtmidi 1.5.8 and Tk 8.6.
The development package is approximately 17 MB compressed.

- Fresh extraction: every packaged file matched its SHA-256 manifest.
- Helper ran with PATH limited to Windows System32 and Python/Tcl/Tk environment
  variables removed. Its reported Python prefix was inside the extracted bundle.
- Bundled Tk created a window; bundled RtMidi loaded the Windows MIDI backend.
- Native input enumeration succeeded; no MIDI input was opened or data sent.
- Editor, toolkit and metadata assets loaded; a synthetic kit saved outside the
  application and recovery persisted on Stop. The bundled hex utility ran.
- The actual windowed executable was driven with browser opening intercepted:
  Try a demo started the host, Open editor opened its URL, and Stop saved recovery.
- Application payload hashes were unchanged after execution.
- Source regression suites and format round trips passed (29 suites plus 2
  fixture suites). Launcher recovery and source ZIP extraction remained working.
- 119 existing browser cases passed. Four new launcher-demo cases passed in
  Chromium and iPad WebKit, including paired redirect without starting capture.
  An initial test selected the state badge instead of the status message; the
  corrected assertions passed. No product fix was required for that mismatch.

The local tool sandbox blocked Tcl file access; the same fresh-extraction test
passed outside that sandbox. Build and smoke checks run automatically in CI.

## Still needed before a broad release

- Another Windows machine with no Python installed (the local test removed Python
  from the process environment; it did not uninstall Python from this computer).
- Physical Strike and generic-module MIDI capture, factory activation, and SD
  deployment through the packaged build. Existing hardware evidence applies to
  the earlier source implementation, not automatically to this package.
- User acceptance of first launch, manual upgrade/rollback, and firewall prompts.
- Signing/reputation and a public downloadable release. Current distribution is
  an unsigned beta ZIP, with manual updates and CI artifacts requiring sign-in.

Mac packaging, native iOS apps and automatic updates remain deferred.
