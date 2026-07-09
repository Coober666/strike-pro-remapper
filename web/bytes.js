// bytes.js — tiny shared byte helpers for the read-only .skt/.sin parsers.
// Vanilla JS, no dependencies. Semantics mirror the Python originals exactly.

// Accepts ArrayBuffer, Uint8Array, or Node Buffer → Uint8Array (no copy).
export function toU8(buf) {
  if (buf instanceof Uint8Array) return buf;
  if (buf instanceof ArrayBuffer) return new Uint8Array(buf);
  if (ArrayBuffer.isView(buf)) return new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength);
  throw new TypeError('expected an ArrayBuffer, Uint8Array, or Buffer');
}

// Mirror Python bytes.decode('ascii', errors='replace'): bytes 0–127 map to the
// matching code point, every byte >127 becomes U+FFFD. (Do NOT use TextDecoder('ascii')
// — per WHATWG that label is an alias for windows-1252, which decodes 0x80–0xFF instead
// of replacing them, so it would diverge from Python.)
export function asciiReplace(u8) {
  let s = '';
  for (let i = 0; i < u8.length; i++) {
    const b = u8[i];
    s += b < 128 ? String.fromCharCode(b) : '�';
  }
  return s;
}

// Python str.strip() with no args strips ASCII whitespace (space/tab/nl/cr/vt/ff).
// (Note: it does NOT strip NULs — neither does this.)
export function pyStrip(s) {
  return s.replace(/^[\t\n\v\f\r ]+/, '').replace(/[\t\n\v\f\r ]+$/, '');
}

export function u16le(u8, off) { return u8[off] | (u8[off + 1] << 8); }
export function u32le(u8, off) {
  return (u8[off] | (u8[off + 1] << 8) | (u8[off + 2] << 16) | (u8[off + 3] * 0x1000000)) >>> 0;
}
export function magic4(u8, off) { return asciiReplace(u8.subarray(off, off + 4)); }
