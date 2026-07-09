// sin.js — READ-ONLY JavaScript port of strike_remap.py's .sin instrument parser.
//
// Byte-for-byte faithful to parse_sin() / parse_sin_all_wavs() / _sin_blocks().
// No writers (patch_sin / rebuild_sin_zones) — those are a later, test-gated stage.
// Vanilla JS + standard APIs only; no dependencies.
//
// .sin layout (INST → msmp → str chunks), decoded by the strike4j project and verified
// against the whole preset library. See CLAUDE.md § ".sin instrument format".

import { toU8, asciiReplace, pyStrip, u16le, u32le } from './bytes.js';

export const SIN_GROUPS = {
  0: 'Kick', 1: 'Snare', 2: 'Tom', 3: 'Hi-Hat', 4: 'Crash', 5: 'Ride',
  6: 'Group 6', 7: 'E. Kick', 8: 'E. Snare', 9: 'E. Tom', 10: 'Percussion',
  11: 'Perc Ethnic', 12: 'Group 12', 13: 'Perc Orchestral', 14: 'E. Perc',
  15: 'Group 15', 16: 'Group 16', 17: 'Group 17', 18: 'Claps/SFX', 19: 'Melodic',
};

// name: [offset into INST payload, signed, lo, hi] — mirrors _SIN_PARAM_MAP.
const SIN_PARAM_MAP = {
  group:      [1,  false, 0, 19],
  level:      [6,  false, 0, 127],
  pan:        [7,  true, -50, 50],
  decay:      [8,  false, 0, 127],
  semi:       [11, true, -12, 12],
  fine:       [12, true, -50, 50],
  cutoff:     [13, false, 0, 127],
  hipass:     [14, false, 0, 1],
  vel_decay:  [15, true, -99, 99],
  vel_pitch:  [16, true, -99, 99],
  vel_filter: [17, true, -99, 99],
  vel_level:  [18, true, -99, 99],
  loop:       [21, false, 0, 1],
};

const SIN_MAPPING_SIZE = 28;

// Faithful port of _sin_blocks(): walk chunks → { magic: [payloadOffset, payloadSize] }.
// Later duplicate magics overwrite earlier ones (same as the Python dict).
export function sinBlocks(buf) {
  const data = toU8(buf);
  const blocks = {};
  let pos = 0;
  while (pos + 8 <= data.length) {
    const magic = asciiReplace(data.subarray(pos, pos + 4));
    const size = u32le(data, pos + 4);
    if (pos + 8 + size > data.length) break;
    blocks[magic] = [pos + 8, size];
    pos += 8 + size;
  }
  return blocks;
}

// Faithful port of parse_sin(): → { params, cycle_random, mappings, strings }.
export function parseSin(buf) {
  const data = toU8(buf);
  const blocks = sinBlocks(data);
  if (!('INST' in blocks) || blocks['INST'][1] < 24) {
    throw new Error('Not a valid .sin file (missing INST block)');
  }
  const ioff = blocks['INST'][0];

  const val = (off, signed) => {
    const v = data[ioff + off];
    return signed && v > 127 ? v - 256 : v;
  };

  const params = {};
  for (const name in SIN_PARAM_MAP) {
    const [off, signed] = SIN_PARAM_MAP[name];
    params[name] = val(off, signed);
  }

  let strings = [];
  if ('str ' in blocks) {
    const [soff, ssize] = blocks['str '];
    strings = splitNul(data.subarray(soff, soff + ssize))
      .filter((seg) => seg.length > 0)
      .map((seg) => asciiReplace(seg));
  }

  let cycle_random = 0;
  const mappings = [];
  if ('msmp' in blocks) {
    const [moff, msize] = blocks['msmp'];
    if (msize >= 4) {
      cycle_random = data[moff];
      const count = data[moff + 2];
      for (let i = 0; i < count; i++) {
        const m = moff + 4 + i * SIN_MAPPING_SIZE;
        if (m + SIN_MAPPING_SIZE > moff + msize) break;
        const strIdx = u16le(data, m);
        mappings.push({
          sample: strIdx < strings.length ? strings[strIdx] : `<str ${strIdx}>`,
          vmin: data[m + 3],
          vmax: data[m + 4],
          rr: data[m + 7],
          hh_min: data[m + 10],
          hh_max: data[m + 11],
        });
      }
    }
  }
  return { params, cycle_random, mappings, strings };
}

// Faithful port of parse_sin_all_wavs(): every WAV path in the str block, in order.
export function parseSinAllWavs(buf) {
  const data = toU8(buf);
  let pos = 0;
  while (pos + 8 <= data.length) {
    const magic = asciiReplace(data.subarray(pos, pos + 4));
    const size = u32le(data, pos + 4);
    if (magic === 'str ') {
      const strData = data.subarray(pos + 8, pos + 8 + size);
      return splitNul(strData)
        .filter((seg) => seg.length > 0)
        .map((seg) => pyStrip(asciiReplace(seg)))
        .filter((s) => {
          const lower = s.toLowerCase();
          return lower.endsWith('.wav') || lower.endsWith('.wave');
        });
    }
    if (pos + 8 + size > data.length) break;
    pos += 8 + size;
  }
  return [];
}

// Faithful port of parse_sin_first_wav(): first WAV path, or null.
export function parseSinFirstWav(buf) {
  const data = toU8(buf);
  let pos = 0;
  while (pos + 8 <= data.length) {
    const magic = asciiReplace(data.subarray(pos, pos + 4));
    const size = u32le(data, pos + 4);
    if (magic === 'str ') {
      const strData = data.subarray(pos + 8, pos + 8 + size);
      for (const seg of splitNul(strData)) {
        const s = pyStrip(asciiReplace(seg));
        const lower = s.toLowerCase();
        if (s && (lower.endsWith('.wav') || lower.endsWith('.wave'))) return s;
      }
      break;
    }
    if (pos + 8 + size > data.length) break;
    pos += 8 + size;
  }
  return null;
}

// Split a Uint8Array on NUL bytes → array of Uint8Array segments (like bytes.split(b'\x00')).
function splitNul(u8) {
  const out = [];
  let start = 0;
  for (let i = 0; i < u8.length; i++) {
    if (u8[i] === 0) {
      out.push(u8.subarray(start, i));
      start = i + 1;
    }
  }
  out.push(u8.subarray(start));
  return out;
}
