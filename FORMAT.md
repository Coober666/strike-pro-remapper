# Alesis Strike `.skt` / `.sin` File Format Reference

Community reverse-engineering reference for the Alesis Strike / Strike Pro module's kit
(`.skt`) and instrument (`.sin`) file formats. Maintained as part of
[Strike Pro Remapper](README.md); verified against the module's 116 factory preset kits and
1,749 factory instruments via byte-for-byte round-trip tests.

**Confidence legend:**
- ✅ **confirmed** — verified by hardware hex diff (change value on module → compare bytes)
- 📊 **strong evidence** — statistical analysis across all factory presets matches the
  documented parameter range exactly
- ⚠️ **hypothesis** — structurally plausible, byte patterns consistent, not yet verified
- ❓ **unknown** — bytes exist, purpose unidentified

Multi-byte integers are **little-endian**. Files are **4-byte aligned** (zero-padded).
Signed bytes use two's complement (`0xCE` = −50).

---

## Common chunk structure

Both formats are sequences of chunks:

```
+0  4 bytes   ASCII magic ('KIT ', 'inst', 'str ', 'INST', 'msmp')
+4  uint32    payload size
+8  payload
```

---

## `.skt` — Kit file

Chunk sequence: one `KIT ` block, ~22 `inst` blocks (one per pad/zone), one `str ` block,
then zero padding.

### `KIT ` block — kit-level settings (44-byte payload)

Offsets below are **kit_raw-relative** (payload offset + 8-byte chunk header), matching
the project's source. Layout ✅ hardware-confirmed via hex diff against official-editor
saves (May 2026):

| kit_raw offset | Type | Meaning | Status |
|---|---|---|---|
| 16 | uint8 | reverb type index (2=BigGate, 3=CloseMic; 0–21 observed) | ✅ |
| 17 | uint8 | reverb size 0–99 | ✅ |
| 18 | uint8 | reverb color 0–99 | ✅ |
| 19 | uint8 | reverb level 0–99 | ✅ |
| 20 | uint8 | FX1 type index (see enum below; 0xFF = off) | ✅ |
| 21 | uint8 | FX1 level 0–99 | ✅ |
| 22–23 | uint16 | FX1 delay ms for delay-family types (140 = slapback, 800 = delay observed) | 📊 |
| 26 | uint8 | FX1 feedback 0–99 | ✅ |
| 28 | uint8 | FX1 depth 0–99 | ✅ |
| 29 | uint8 | FX1 rate 0–99 | ✅ |
| 32–41 | — | FX2 block — exact mirror of FX1 layout | ✅ |
| 44 | uint8 | compressor preset index (0=Master 1, 1=Radio 1 confirmed; full order per official editor guide: Master 1, Radio 1, Radio 2, Soft Hyper, Bright, Country, Crunch, Dance, Hip Hop, Jazz, Lo Boost, Rock 1, Rock 2, Rock 3) | ✅ |
| 45 | int8 | comp threshold dB | ✅ |
| 46 | int8 | HF gain dB | ✅ |
| 47 | int8 | LF gain dB | ✅ |
| 48 | uint8 | LF freq index (10=58 Hz, 11=66 Hz; sequential) | ✅ |
| 49 | int8 | comp output dB | ✅ |
| 50 | uint8 | HF freq index (77=8.7 kHz, 78=9.1 kHz; sequential) | ✅ |

**FX type enum** — 0-based, no Off entry (0xFF = off). Anchored by hex diff
(0=Mono Flanger, 1=Stereo Flanger, 3=Mono Chorus 1); remainder inferred from the
manuals' effects-table order:

```
0 Mono Flanger   1 Stereo Flanger  2 Xover Flanger   3 Mono Chorus 1
4 Mono Chorus 2  5 Stereo Chorus   6 XOver Chorus    7 Mono Vibrato
8 Vibrato        9 Mono Doubler   10 Doubler        11 Mono Slapback
12 Slapback     13 Mono Delay     14 Delay          15 XOver Delay
16 Ping Pong                       (0xFF = off)
```

### `inst` block — one per pad/zone (72-byte payload)

The first 4 bytes are the zone ID in ASCII (e.g. `K1H `, `S1R `, `C2B `: kick/snare/tom/
hihat/crash/ride + number + Head/Rim/Bow/Edge/Foot/D=bell). Layer A occupies offsets
4–23; layer B is an exact structural mirror at +20 (offsets 24–43).

All visible per-pad parameters in the official editor are now ✅ **hardware-confirmed**
(hex diff against official-editor saves, May 2026):

| Offset (A / B) | Type | Meaning | Status |
|---|---|---|---|
| 4 / 24 | uint16 | instrument index into `str ` table; `0xFFFF` = none | ✅ |
| 6 / 26 | uint8 | level 0–99 | ✅ |
| 7 / 27 | int8 | pan −50..+50 | ✅ |
| 8 / 28 | uint8 | decay 0–99 | ✅ |
| 11 / 31 | int8 | pitch semitones −12..+12 | ✅ |
| 12 / 32 | int8 | fine pitch −50..+50 cents | ✅ |
| 13 / 33 | uint8 | filter cutoff 0–99 | ✅ |
| 14 / 34 | uint8 | filter enable 0/1 (filter *type* lives in the .sin, not the kit) | ✅ |
| 15 / 35 | uint8 | velocity→decay 0–127 | ✅ |
| 16 / 36 | uint8 | velocity→pitch 0–127 | ✅ |
| 17 / 37 | uint8 | velocity→filter 0–127 | ✅ |
| 18 / 38 | uint8 | velocity→volume 0–127 | ✅ |
| 19 / 39 | uint8 | layer velocity-range min (off 39 = layer B min = the xfade threshold) | ✅ |
| 20 / 40 | uint8 | layer velocity-range max (127 in every factory pad) | ✅ |
| 21 / 41 | uint8 | loop mode 0/1 | ✅ |
| 44 | uint8 | reverb send 0–99 | ✅ |
| 45 | uint8 | FX1 send 0–99 | ✅ |
| 46 | uint8 | EQ/Comp enable 0/1 | ✅ |
| 48 | uint8 | priority 0=Low 1=Med 2=High | ✅ |
| 49 | uint8 | mute/choke group 0=off, 1–9 | ✅ |
| 50 | uint8 | note-off mode 0=Sent 1=None 2=Alt | ✅ |
| 51 | uint8 | MIDI channel, 0-indexed (0=ch1 … 15=ch16) | ✅ |
| 52 | uint8 | MIDI note 0–127 | ✅ |
| 53 | uint8 | gate time: 0–99 = Free gate length in **ms** (per official editor guide), 100–109=Sync:32…Sync:2T, 255=OFF | ✅ |
| 54 | uint8 | playback mode 0=Mono 1=Poly | ✅ |
| 61 | uint8 | FX2 send 0–99 | ✅ |
| 9–10, 22–23, 29–30, 42–43, 47, 55, 56–60 | — | reserved/internal — no UI param maps here; do not write | ❓ |

### `str ` block

Zero-terminated ASCII strings, one per instrument slot, referenced by index from the
`inst` blocks. Paths are relative with forward slashes (e.g. `Kicks/Big Boom.sin`).

---

## `.sin` — Instrument file

Chunk sequence: `INST` (24-byte params) → `msmp` (sample mappings) → `str ` (WAV paths).
INST layout originally decoded by [strike4j](https://github.com/cbuschka/strike4j);
verified here against all 1,749 factory instruments with zero exceptions.

### `INST` block (24-byte payload)

| Offset | Type | Meaning | Status |
|---|---|---|---|
| 0 | uint8 | constant 0 | — |
| 1 | uint8 | instrument group 0–19 (see group enum) | 📊 |
| 2–5 | bytes | constants 1, 0, 0, 0 | — |
| 6 | uint8 | level (75–99 observed) | 📊 |
| 7 | int8 | pan −50..+50 | 📊 |
| 8 | uint8 | decay | 📊 |
| 9–10 | bytes | constants 0, 0 | — |
| 11 | int8 | pitch semitones −12..+12 | 📊 |
| 12 | int8 | fine pitch −50..+50 cents | 📊 |
| 13 | uint8 | filter cutoff (99–127 observed; 127 ≈ open) | 📊 |
| 14 | uint8 | filter type: 0 = low-pass, 1 = high-pass | 📊 |
| 15 | int8 | velocity→decay −99..+99 | 📊 |
| 16 | int8 | velocity→pitch −99..+99 | 📊 |
| 17 | int8 | velocity→filter −99..+99 | 📊 |
| 18 | int8 | velocity→level −99..+99 | 📊 |
| 19–20 | bytes | constants 0, 0x7F | — |
| 21 | uint8 | loop flag 0/1 | 📊 |
| 22–23 | bytes | constants 0, 0 | — |

**Instrument group enum** (byte 1; names verified empirically by correlating against the
factory library's folder structure — groups 6/12/15/16/17 unused by the factory set):

```
0 Kick      1 Snare        2 Tom         3 Hi-Hat       4 Crash    5 Ride
7 E. Kick   8 E. Snare     9 E. Tom     10 Percussion  11 Perc Ethnic
13 Perc Orchestral  14 E. Perc  18 Claps/SFX  19 Melodic
```

### `msmp` block — sample mappings

This layout was confirmed by hex analysis of real multi-velocity preset `.sin` files.

Header (4 bytes): `[0]` cycle mode (0 = round-robin, 1 = random), `[1]` ❓, `[2]` mapping
count, `[3]` ❓. Then `count` × 28-byte mapping records:

| Offset | Type | Meaning | Status |
|---|---|---|---|
| 0–1 | uint16 | string index into `str ` table (the WAV path) | 📊 |
| 2 | uint8 | command byte (0x63 typical; 0x4D–0x62 observed in presets) | ❓ |
| 3 | uint8 | velocity range min 0–127 | 📊 |
| 4 | uint8 | velocity range max 0–127 | 📊 |
| 5–6 | bytes | ❓ (6 mostly 0x7F) | ❓ |
| 7 | int8 | round-robin index (1-based within a velocity band); **signed** — `0xFE`/−2 marks hi-hat pedal chick/splash functions | 📊 |
| 8–9 | bytes | ❓ | ❓ |
| 10 | uint8 | hi-hat pedal-open range min 0–127 | ⚠️ (per strike4j) |
| 11 | uint8 | hi-hat pedal-open range max 0–127 | ⚠️ (per strike4j) |
| 12–27 | bytes | ❓ (constants/sparse; preserve on edit) | ❓ |

### `str ` block

Zero-terminated ASCII WAV paths. Preset instruments use paths relative to
`<SD volume>/Samples/`; locally-created instruments may use paths relative to the
instrument library root. **Paths are effectively absolute references — renaming or moving
a WAV breaks every instrument that points at it.**

---

## Practical notes for implementers

- **Round-trip before writing.** Parse → rebuild must reproduce input files byte-for-byte
  before you trust any writer (`tools/test_roundtrip.py`, `tools/test_sin_roundtrip.py`).
- **Never invent unknown bytes.** When adding mapping records, clone an existing record
  from the same file and patch only the known fields.
- **Module constraints:** filenames ≤ 26 chars; instruments must live in a subfolder of
  `/Instruments/` (never the root); one subfolder level visible; 200 MB per kit;
  WAVs 16/24-bit, 44.1/48/96 kHz (48 kHz native).
- **Factory pad defaults:** offsets 53/54 are `102`/`1` in every factory pad. Generated
  kits that write zeros there load fine but may differ in MIDI gate/note-off behavior.

## Credits

- [strike4j](https://github.com/cbuschka/strike4j) (cbuschka) — original `.sin` INST decode
- [strikeparse](https://github.com/mmdurrant/strikeparse) (mmdurrant) — early `.skt` exploration
- Alesis Strike Module User Guide v1.5 & Strike Editor User Guide v1.2 — parameter
  names, ranges, and the FX type table
- alesisdrummer.com community research
