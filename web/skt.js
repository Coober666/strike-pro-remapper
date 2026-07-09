// skt.js — READ-ONLY JavaScript port of strike_remap.py's .skt parser.
//
// Byte-for-byte faithful to parse_skt() + _pad_view(). No writers live here — the
// losslessness burden (build_skt) belongs to a later, test-gated stage. Vanilla JS +
// standard Web/Node APIs only (DataView / TextDecoder); no dependencies.
//
// parseSkt(buf) returns the shape the existing frontend consumes:
//   { kit_raw, pads, instruments, tail }
// where `pads` is already the _pad_view() array (drop-in for renderDrumMap /
// renderPadDetail) and kit_raw / tail are Uint8Arrays of the raw block bytes.

import { toU8, asciiReplace, pyStrip, u16le, u32le, magic4 } from './bytes.js';

// ── Offset constants (relative to the start of an `inst` block payload) ──────────
export const LAYER_A_IDX_OFF = 4;   // uint16 LE — Layer A str index
export const LAYER_B_IDX_OFF = 24;  // uint16 LE — Layer B str index
export const NO_INSTRUMENT   = 0xFFFF;

export const MIDI_NOTE_OFF = 52;
export const LA_LEVEL_OFF  = 6;
export const LA_PAN_OFF    = 7;   // int8
export const LA_PITCH_OFF  = 11;  // int8
export const LA_FCUT_OFF   = 13;
export const LA_FFLAG_OFF  = 14;
export const LA_DECAY_OFF  = 8;
export const LA_VEL_DEC_OFF = 15;
export const LA_VEL_PCH_OFF = 16;
export const LA_VEL_FLT_OFF = 17;
export const LA_VEL_VOL_OFF = 18;
export const LA_VEL_MIN_OFF = 19;
export const LA_VEL_MAX_OFF = 20;
export const LB_LEVEL_OFF  = 26;
export const LB_PAN_OFF    = 27;  // int8
export const LB_PITCH_OFF  = 31;  // int8
export const LB_FCUT_OFF   = 33;
export const LB_FFLAG_OFF  = 34;
export const LB_DECAY_OFF  = 28;
export const LB_VEL_DEC_OFF = 35;
export const LB_VEL_PCH_OFF = 36;
export const LB_VEL_FLT_OFF = 37;
export const LB_VEL_VOL_OFF = 38;
export const XFADE_VEL_OFF = 39;
export const EQ_COMP_OFF   = 46;
export const REVERB_OFF    = 44;
export const FX1_OFF       = 45;
export const FX2_OFF       = 61;
export const PRIORITY_OFF  = 48;
export const MUTE_GRP_OFF  = 49;
export const NOTE_OFF_OFF  = 50;
export const MIDI_CHAN_OFF = 51;
export const GATE_TIME_OFF = 53;
export const PLAY_MODE_OFF = 54;
export const LA_FINE_OFF   = 12;  // int8
export const LB_FINE_OFF   = 32;  // int8
export const LA_LOOP_OFF   = 21;
export const LB_LOOP_OFF   = 41;

export const PAD_LABEL = {
  K1H: 'Kick 1 Head',   K2H: 'Kick 2 Head',
  S1H: 'Snare Head',    S1R: 'Snare Rim',
  T1H: 'Tom 1 Head',    T1R: 'Tom 1 Rim',
  T2H: 'Tom 2 Head',    T2R: 'Tom 2 Rim',
  T3H: 'Tom 3 Head',    T3R: 'Tom 3 Rim',
  T4H: 'Tom 4 Head',    T4R: 'Tom 4 Rim',
  H1B: 'Hi-Hat Bow',    H1E: 'Hi-Hat Edge',  H1F: 'Hi-Hat Foot',
  C1B: 'Cymbal 1 Bow',  C1E: 'Cymbal 1 Edge',
  C2B: 'Cymbal 2 Bow',  C2E: 'Cymbal 2 Edge',
  C3B: 'Cymbal 3 Bow',  C3E: 'Cymbal 3 Edge',
  R1D: 'Ride Bell',     R1B: 'Ride Bow',     R1E: 'Ride Edge',
};

export const PAD_INPUT = {
  K1H: 'KICK',            K2H: 'KICK (2nd)',
  S1H: 'SNARE · tip',     S1R: 'SNARE · ring',
  T1H: 'TOM 1 · tip',     T1R: 'TOM 1 · ring',
  T2H: 'TOM 2 · tip',     T2R: 'TOM 2 · ring',
  T3H: 'TOM 3 · tip',     T3R: 'TOM 3 · ring',
  T4H: 'TOM 4 · tip',     T4R: 'TOM 4 · ring',
  H1B: 'HI-HAT · tip',    H1E: 'HI-HAT · ring',  H1F: 'HH CONTROL',
  C1B: 'CRASH 1 · tip',   C1E: 'CRASH 1 · ring',
  C2B: 'CRASH 2 · tip',   C2E: 'CRASH 2 · ring',
  C3B: 'CRASH 3 · tip',   C3E: 'CRASH 3 · ring',
  R1B: 'RIDE 1 · tip',    R1E: 'RIDE 1 · ring',
  R1D: 'RIDE 2',
};

export const GM_DRUMS = {
  35: 'Ac.Bass Drum', 36: 'Bass Drum 1', 37: 'Side Stick',
  38: 'Ac.Snare',     39: 'Hand Clap',   40: 'Elec.Snare',
  41: 'Lo Floor Tom', 42: 'Closed HH',   43: 'Hi Floor Tom',
  44: 'Pedal HH',     45: 'Lo Tom',      46: 'Open HH',
  47: 'Lo-Mid Tom',   48: 'Hi-Mid Tom',  49: 'Crash 1',
  50: 'Hi Tom',       51: 'Ride 1',      52: 'Chinese',
  53: 'Ride Bell',    54: 'Tambourine',  55: 'Splash',
  56: 'Cowbell',      57: 'Crash 2',     58: 'Vibraslap',
  59: 'Ride 2',       60: 'Hi Bongo',    61: 'Lo Bongo',
};

// ── parser ──────────────────────────────────────────────────────────────────────

// Faithful port of parse_skt(): returns { kit_raw, pads(raw), instruments, tail }
// with raw pad objects ({id, label, layer_a, layer_b, payload}). Internal — the
// public parseSkt() runs this and then _pad_view over the result.
function parseSktRaw(u8) {
  if (magic4(u8, 0) !== 'KIT ') throw new Error('Not a KIT file');
  const kitSize = u32le(u8, 4);
  const kit_raw = u8.subarray(0, 8 + kitSize);
  let pos = 8 + kitSize;

  const pads = [];
  while (pos + 8 <= u8.length && magic4(u8, pos) === 'inst') {
    const blkSize = u32le(u8, pos + 4);
    const payload = u8.subarray(pos + 8, pos + 8 + blkSize);
    const padId = pyStrip(asciiReplace(payload.subarray(0, 4)));
    pads.push({
      id: padId,
      label: PAD_LABEL[padId] ?? padId,
      layer_a: u16le(payload, LAYER_A_IDX_OFF),
      layer_b: u16le(payload, LAYER_B_IDX_OFF),
      payload,
    });
    pos += 8 + blkSize;
  }

  const instruments = [];
  let tail = new Uint8Array(0);
  if (pos + 8 <= u8.length && magic4(u8, pos) === 'str ') {
    const strSize = u32le(u8, pos + 4);
    const strData = u8.subarray(pos + 8, pos + 8 + strSize);
    // Replicate the Python index()/break loop: only NUL-terminated segments count,
    // a trailing un-terminated segment is dropped.
    let i = 0;
    while (i < strData.length) {
      let end = strData.indexOf(0, i);
      if (end === -1) break;
      const s = asciiReplace(strData.subarray(i, end));
      if (s) instruments.push(s);
      i = end + 1;
    }
    tail = u8.subarray(pos + 8 + strSize);
  }

  return { kit_raw, pads, instruments, tail };
}

// Faithful port of Handler._pad_view(): serialize raw pads → the frontend pad array.
export function padView(pads, instruments) {
  const name = (idx) => {
    if (idx === NO_INSTRUMENT || idx >= instruments.length) return null;
    let s = instruments[idx];
    s = s.substring(s.lastIndexOf('/') + 1);            // rsplit('/', 1)[-1]
    s = s.split('.sin').join('').split('.SIN').join(''); // .replace('.sin','').replace('.SIN','')
    return s;
  };
  const ipath = (idx) =>
    (idx === NO_INSTRUMENT || idx >= instruments.length) ? null : instruments[idx];

  return pads.map((p) => {
    const payload = p.payload;
    const u8 = (off) => (off < payload.length ? payload[off] : 0);
    const i8 = (off) => {
      const v = off < payload.length ? payload[off] : 0;
      return v < 128 ? v : v - 256;
    };
    const midi = u8(MIDI_NOTE_OFF);
    return {
      id: p.id,
      label: p.label,
      layer_a: p.layer_a,
      layer_a_name: name(p.layer_a),
      layer_a_path: ipath(p.layer_a),
      layer_b: p.layer_b,
      layer_b_name: name(p.layer_b),
      layer_b_path: ipath(p.layer_b),
      midi_note: midi,
      midi_name: GM_DRUMS[midi] ?? `note ${midi}`,
      la_level: u8(LA_LEVEL_OFF),
      la_pan: i8(LA_PAN_OFF),
      la_pitch: i8(LA_PITCH_OFF),
      la_decay: u8(LA_DECAY_OFF),
      la_vel_dec: u8(LA_VEL_DEC_OFF),
      la_vel_pch: u8(LA_VEL_PCH_OFF),
      la_vel_flt: u8(LA_VEL_FLT_OFF),
      la_vel_vol: u8(LA_VEL_VOL_OFF),
      la_fcut: u8(LA_FCUT_OFF),
      la_fflag: u8(LA_FFLAG_OFF),
      la_fine: i8(LA_FINE_OFF),
      la_loop: u8(LA_LOOP_OFF),
      la_vel_min: u8(LA_VEL_MIN_OFF),
      la_vel_max: u8(LA_VEL_MAX_OFF),
      lb_level: u8(LB_LEVEL_OFF),
      lb_pan: i8(LB_PAN_OFF),
      lb_pitch: i8(LB_PITCH_OFF),
      lb_decay: u8(LB_DECAY_OFF),
      lb_vel_dec: u8(LB_VEL_DEC_OFF),
      lb_vel_pch: u8(LB_VEL_PCH_OFF),
      lb_vel_flt: u8(LB_VEL_FLT_OFF),
      lb_vel_vol: u8(LB_VEL_VOL_OFF),
      xfade_vel: u8(XFADE_VEL_OFF),
      lb_fcut: u8(LB_FCUT_OFF),
      lb_fflag: u8(LB_FFLAG_OFF),
      lb_fine: i8(LB_FINE_OFF),
      lb_loop: u8(LB_LOOP_OFF),
      reverb: u8(REVERB_OFF),
      fx1: u8(FX1_OFF),
      fx2: u8(FX2_OFF),
      eq_comp: u8(EQ_COMP_OFF),
      priority: u8(PRIORITY_OFF),
      note_off: u8(NOTE_OFF_OFF),
      midi_chan: u8(MIDI_CHAN_OFF) + 1,
      play_mode: u8(PLAY_MODE_OFF),
      gate_time: u8(GATE_TIME_OFF),
      mute_grp: u8(MUTE_GRP_OFF),
      input: PAD_INPUT[p.id] ?? '',
    };
  });
}

// Public API: parse a .skt into the frontend-ready shape.
//   pads        → padView array (drop-in for renderDrumMap / renderPadDetail)
//   instruments → str table (ordered WAV/.sin paths)
//   kit_raw / tail → Uint8Array of the raw KIT block and trailing bytes
export function parseSkt(buf) {
  const u8 = toU8(buf);
  const raw = parseSktRaw(u8);
  return {
    kit_raw: raw.kit_raw,
    pads: padView(raw.pads, raw.instruments),
    instruments: raw.instruments,
    tail: raw.tail,
  };
}
