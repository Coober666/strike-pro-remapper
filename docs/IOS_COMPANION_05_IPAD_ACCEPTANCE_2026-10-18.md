# Companion 0.5 iPad acceptance — October 18, 2026

This records owner-reported checks on an iPad Pro 12.9-inch (6th generation),
iPadOS 26.6. Simulator results, device launch and attended UI observations are
separate evidence. No personal kit or sound library was used.

## Development build and initial checks

Source `47f12f12ba9d471e1b8c725900814c5ecbde4a86`, version 0.5.0 (5), built with
installed Xcode 27.1 (27A9275). Programmatic checks verified its development
signature and inclusion of this iPad in the provisioning profile. Installation
succeeded; launch initially required the owner to trust the development signing
profile. After the owner enabled Developer Mode and trusted it, programmatic
launch succeeded and the owner confirmed:

- Welcome screen visible; demo opens Soundcheck, Song 1 of 4.
- Next opens Paper Satellites, Song 2 of 4.
- Kit editor welcome says “Make the kit yours.”
- Synthetic kit shows pad-zone list beside details on the iPad.
- Snare Head shows Synthetic/Snare.sin in Layer A and Synthetic/Brush Snare.sin
  in Layer B.
- Applying Layer A Level 73 shows 73 and Edited copy; Undo restores 100.

The owner reported using the minus button 27 times because direct numeric entry
was not discoverable. The 0.5.1 (6) follow-up adds a large bordered entry field,
Clear, a whole-number slider and a separate ±1 fine adjustment. Apply/Cancel and
binary validation remain required. Its simulator and installation results are
recorded separately below; attended acceptance of those new controls is pending.

## Numeric-input follow-up

The 0.5.1 follow-up is being checked in installed iPhone/iPad simulators before
installation. Its larger field owns keyboard focus and whole-value selection;
Clear, a whole-number slider and ±1 remain pending-only controls. The owner is
updating this physical iPad to iPadOS 27.0. No device query, install or launch is
performed during that update; wait for explicit completion/unlock confirmation.
The physical iPad still has the initial 0.5.0 build as of this record. New-control
acceptance and the final simulator result are not inferred from the initial checks.

## Remaining checks

Redo, new numeric controls, local Files export/reopen/cancellation, return to the
same song, rotation, Dynamic Type/VoiceOver and external provider behavior remain
attended checks. Passing the synthetic local workflow would not establish module
playback, sound availability or cloud synchronization. Kit edits remain memory-only
until exported. Original files are never save targets.

Personal account, team, device and provisioning identifiers stay in ignored local
receipts. The original checkout’s personal signing file remains unchanged. No
physical iPhone update or module/card operation was performed in this session.
