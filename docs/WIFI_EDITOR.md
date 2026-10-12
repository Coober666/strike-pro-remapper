# Full editor over Wi-Fi

Keep the Strike's USB cable connected to your Mac, Windows PC, or Linux computer.
The iPad is the browser; the computer owns the library, SD access, and factory activation.
This mode adds remote access to the existing editor, including its normal explicit save
and deployment actions. It is separate from the activation-only controller on port 8766.

## Start and pair

With Python 3.10 or newer, run from the repository folder:

```sh
python3 -m strike_remapper.wifi_editor --bind 192.168.1.239 --library-root /path/to/strike-library
```

Replace the address with your computer's private LAN IPv4 address and the library folder
with its persistent library location. Windows may use `python` instead of `python3`.
Port 8765 is the default; use `--port` if occupied. On macOS use the newer Python installation,
not an old `/usr/bin/python3`. The normal `python strike_remap.py` remains localhost-only.

Open the printed **private pairing link** on the iPad on the same network. Keep `http://`:
this server does not speak HTTPS. If Brave upgrades it, allow HTTP for this LAN address.
Pairing automatically opens the editor and removes the secret from the address bar.
You can also paste the link into the pairing page. Keep the link private: anyone with it
on the LAN has full editor access, including host files and deliberate Deploy actions.

Choose a mounted kit in Kits, or use Start to sync the cards into the computer's library.
**Save to library** saves a host copy. **Deploy** is separate and uses the existing preview
and confirmation workflow for the writable user card. The factory card remains read-only.
To expose it after a fresh module boot, choose **Activate factory card**, then find the
Strike and activate it in the new controller tab. Return to the editor and refresh if needed.
This does not make kit edits live on the module; deploy and reload the kit there as usual.

## Session and platform limits

- Use one editing browser at a time: all browsers share one active kit and undo history.
- **Disconnect** revokes that browser's session. Sessions expire after 12 hours; reopening
  the pairing link pairs again. Stopping the host process revokes every session and link.
- Keep the computer awake and connected. This command does not install an auto-start service.
- Use only a trusted LAN. HTTP is unencrypted; exact Host/Origin checks and pairing are
  access controls, not encryption. Do not port-forward this server or expose it publicly.
- iPad file editing, library browsing, and HTTP audio use the host APIs. Existing Web MIDI
  features such as live pad input and trigger SysEx backup still require a supported
  local browser. Wi-Fi forwards only the verified factory activation command through MIDI.
- Native activation is verified on the Intel MacBook/Monterey with the Strike. Windows
  and Linux adapters remain hardware-unverified. Chromium and simulated iPad WebKit tests
  cover pairing, actual synthetic-kit edit/save/reload, logout, and host activation routing;
  they do not establish physical iPad or non-Mac hardware validation.
- Direct USB from iPad to Strike needs the paused native iPad app and is not included here.

The earlier “Read-only factory library detected” result confirms the host found a mounted,
read-only volume with the factory content shape after activation. It is not a general
live-editing protocol or a raw USB capture, and content shape alone is not proof of USB identity.
