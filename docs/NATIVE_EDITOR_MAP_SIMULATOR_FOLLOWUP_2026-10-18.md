# Native drum-map prototype check — October 18, 2026

At `a81b3d2c816e7551182768bfe8d0c3cccbbaf636`, the focused map-selection UI test
passed on the installed iOS 27.0 iPad Pro 13-inch (M5) and iPhone 17e simulators.
The receipt covers all 31 native/build inputs, unchanged through both runs, with
exit code zero for each. Evidence remains in ignored
`.build/native-map-selection-acceptance/`.

The test selects Drum map, opens Snare Head, switches to Snare Rim, returns to the
setlist, reopens the inspector and selects that rim through Zones. Editing remains
available, while selection alone retains Original imported status. Exported
screenshots were inspected for the wide iPad and compact phone arrangements.
The map scrolls horizontally when its standard arrangement exceeds the available
width; the complete Zones list remains the alternative.

This is two focused synthetic UI checks, not a full regression run or physical
map acceptance. The 0.5.1 companion checks are documented separately. The prototype
has not been installed on a physical iPad. Direct native MIDI input remains the
next development gate before broadening editor features; this result establishes
no MIDI, sound-library, audio, storage-deployment or module-playback behavior.
