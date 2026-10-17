# Initial iPhone checks — October 17, 2026

Local development build of Strike Companion 0.3.0 (build 3), based on commit
`4428b1d`, installed on a physical iPhone 17 running iOS 26.6.2 after the
[simulator validation](IOS_COMPANION_SIMULATOR_ACCEPTANCE_2026-10-16.md).
This is limited acceptance of the steps below, not full physical-device acceptance.

## Completed

- Owner enabled Developer Mode, restarted the iPhone and completed Apple Account
  sign-in/developer trust through the native device/Xcode prompts.
- `xcodebuild build` for the connected physical iPhone succeeded with a Personal
  Team development profile. `codesign --verify --deep --strict` passed; the
  embedded profile included the connected phone. No private keys were read.
- `devicectl device install app` succeeded. The first launch was blocked by iOS
  developer trust. After the owner completed trust, the second launch succeeded.
- The owner tapped **Try demo** and confirmed **Soundcheck / Song 1 of 4**.
- The owner confirmed that **Next** and **Previous** work on the physical phone.

Ignored local evidence lives under `.build/ios-device-20261017/`: build log,
install/launch JSON and the signed development app under `DerivedData/`.
These local files include signing/device metadata and are not public artifacts.
No account names, team IDs, device IDs, certificates or profiles belong in this
public acceptance record. Owner-selected Xcode signing settings remain local and
uncommitted; no project file is included in this documentation update.

The profile inspected during installation expires October 24, 2026. This
particular development install will need a fresh signed build/profile after
expiry. It is not an App Store, TestFlight or distribution release.

## Still to check

Physical JSON import through Files/Open In, rejected-import preservation, search,
notes sizes, performance view, rotation, backgrounding and VoiceOver remain
unverified. Physical iPad behavior is also unverified. The companion is read-only,
keeps current content for the app session, and never checks kit availability or
communicates with the Strike module.

A two-song synthetic import document is prepared locally in
`.build/ios-device-20261017/import-fixtures/Strike-Companion-Import-Check.json`.
It uses the unchanged version-1 format and passes the Python setlist validator.
Preparation is not evidence that transfer or import worked.
