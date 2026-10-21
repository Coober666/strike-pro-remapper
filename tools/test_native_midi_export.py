"""Verify native capture JSON with the existing web session/profile validators.

Compiles only Foundation data code; never enumerates MIDI or accesses devices.
Native XCTest covers lifecycle and the real Core MIDI packet boundary separately.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    compiler = shutil.which('swiftc')
    node = shutil.which('node')
    if not compiler or not node:
        print('SKIP native MIDI export parity: Swift compiler and Node required (native XCTest still runs on macOS).')
        return
    with tempfile.TemporaryDirectory(prefix='strike-native-midi-') as temporary:
        folder = Path(temporary)
        source = folder / 'main.swift'
        source.write_text('''import Foundation
let bom = String(UnicodeScalar(0xfeff)!)
var take = DrumMIDITake(source: bom + "Synthetic native parity" + bom, synthetic: true)
for (time, bytes): (Double, [UInt8]) in [(0, [0x99, 38, 96]), (10, [0x99, 38, 0]),
    (20, [0x90, 38, 32]), (30, [0xb9, 4, 64]), (40, [0xc9, 5])] {
    precondition(take.append(DrumMIDIMessage(bytes)!, milliseconds: time))
}
precondition(!take.namePad(channel: 10, note: 38, label: bom))
precondition(take.namePad(channel: 10, note: 38, label: bom + "Snare rim" + bom))
take.finish(milliseconds: 100, partial: true)
FileHandle.standardOutput.write(try take.exported())
''')
        executable = folder / 'native-midi-export'
        subprocess.run([compiler, '-swift-version', '6', '-module-cache-path', str(folder / 'cache'),
                        str(ROOT / 'native/StrikeCompanioniOS/Sources/MIDIRecording.swift'),
                        str(source), '-o', str(executable)], check=True, timeout=120)
        exported = subprocess.check_output([str(executable)], timeout=10)
        capture = folder / 'capture.json'
        capture.write_bytes(exported)
        script = '''import fs from 'node:fs';
import assert from 'node:assert/strict';
import {validateSession, summarize} from CORE;
const session = validateSession(JSON.parse(fs.readFileSync(process.argv[1], 'utf8')));
assert.equal(session.captureStatus, 'partial');
assert.equal(session.synthetic, true);
assert.equal(session.source, 'Synthetic native parity');
assert.equal(session.durationMs, 100);
assert.deepEqual(session.segments, [0]);
assert.equal(session.events.length, 5);
assert.deepEqual(session.padMap.mappings, [{channel:10,note:38,label:'Snare rim'}]);
const summary = summarize(session);
assert.equal(summary.hits, 2);
assert.equal(summary.notes.length, 2);
assert.equal(summary.notes[0].channel, 1);
assert.equal(summary.notes[1].channel, 10);
assert.equal(summary.notes[1].hits, 1); // Velocity-zero Note On is Note Off.
assert.equal(summary.controllers[0].last, 64);
'''.replace('CORE', json.dumps((ROOT / 'web/midi-toolkit/core.js').as_uri()))
        subprocess.run([node, '--input-type=module', '--eval', script, str(capture)], check=True, timeout=10)
    print('Native MIDI capture export passes web session/profile validation and analysis.')


if __name__ == '__main__':
    main()
