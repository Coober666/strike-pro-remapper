"""Native output discovery and one fixed Strike activation message. No generic send API.

Run in a short-lived subprocess so a stalled OS MIDI driver cannot hang the server.
macOS: CoreMIDI; Windows: WinMM; Linux: alsa-utils' amidi.
"""
import ctypes as C
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
import time

ACTIVATION = bytes.fromhex('F0 00 00 0E 48 0E 33 03 01 F7')


def strike_name(name):
    return bool(re.search(r'\bstrike\b', name, re.I))


def output_id(address, name):
    return hashlib.sha256(f'{address}:{name}'.encode()).hexdigest()[:24]


def bind(lib, name, result, args):
    fn = getattr(lib, name)
    fn.restype, fn.argtypes = result, args
    return fn


class MacMIDI:
    def __init__(self):
        self.m = C.CDLL('/System/Library/Frameworks/CoreMIDI.framework/CoreMIDI')
        self.cf = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        u32, ptr = C.c_uint32, C.c_void_p
        bind(self.m, 'MIDIGetNumberOfDestinations', C.c_size_t, [])
        bind(self.m, 'MIDIGetDestination', u32, [C.c_size_t])
        bind(self.m, 'MIDIObjectGetStringProperty', C.c_int32, [u32, ptr, C.POINTER(ptr)])
        bind(self.m, 'MIDIClientCreate', C.c_int32, [ptr, ptr, ptr, C.POINTER(u32)])
        bind(self.m, 'MIDIOutputPortCreate', C.c_int32, [u32, ptr, C.POINTER(u32)])
        bind(self.m, 'MIDIPacketListInit', ptr, [ptr])
        bind(self.m, 'MIDIPacketListAdd', ptr, [ptr, C.c_size_t, ptr, C.c_uint64, C.c_size_t, ptr])
        bind(self.m, 'MIDISend', C.c_int32, [u32, u32, ptr])
        bind(self.m, 'MIDIPortDispose', C.c_int32, [u32])
        bind(self.m, 'MIDIClientDispose', C.c_int32, [u32])
        bind(self.cf, 'CFStringGetCString', C.c_bool, [ptr, ptr, C.c_long, u32])
        bind(self.cf, 'CFStringCreateWithCString', ptr, [ptr, C.c_char_p, u32])
        bind(self.cf, 'CFRelease', None, [ptr])

    def outputs(self):
        prop = C.c_void_p.in_dll(self.m, 'kMIDIPropertyDisplayName')
        result = []
        for i in range(self.m.MIDIGetNumberOfDestinations()):
            endpoint = self.m.MIDIGetDestination(i)
            value = C.c_void_p()
            if not self.m.MIDIObjectGetStringProperty(endpoint, prop, C.byref(value)) and value:
                try:
                    buf = C.create_string_buffer(1024)
                    if self.cf.CFStringGetCString(value, buf, len(buf), 0x08000100):
                        result.append((endpoint, buf.value.decode('utf-8')))
                finally:
                    self.cf.CFRelease(value)
        return result

    def activate(self, endpoint):
        client, port = C.c_uint32(), C.c_uint32()
        name = self.cf.CFStringCreateWithCString(None, b'Strike factory activation', 0x08000100)
        try:
            if self.m.MIDIClientCreate(name, None, None, C.byref(client)):
                raise RuntimeError('Could not create MIDI client.')
            if self.m.MIDIOutputPortCreate(client, name, C.byref(port)):
                raise RuntimeError('Could not open MIDI output.')
            packet = C.create_string_buffer(1024)
            data = C.create_string_buffer(ACTIVATION)
            first = self.m.MIDIPacketListInit(packet)
            if not self.m.MIDIPacketListAdd(packet, len(packet), first, 0, len(ACTIVATION), data):
                raise RuntimeError('Could not prepare activation packet.')
            if self.m.MIDISend(port, endpoint, packet):
                raise RuntimeError('MIDI send failed. Check the USB connection.')
            time.sleep(0.3)
        finally:
            if port.value:
                self.m.MIDIPortDispose(port)
            if client.value:
                self.m.MIDIClientDispose(client)
            self.cf.CFRelease(name)


class WindowsMIDI:
    class Caps(C.Structure):
        _fields_ = [('mid', C.c_uint16), ('pid', C.c_uint16), ('version', C.c_uint32),
                    ('name', C.c_wchar * 32), ('technology', C.c_uint16),
                    ('voices', C.c_uint16), ('notes', C.c_uint16),
                    ('channels', C.c_uint16), ('support', C.c_uint32)]

    class Header(C.Structure):
        _fields_ = [('data', C.c_void_p), ('length', C.c_uint32), ('recorded', C.c_uint32),
                    ('user', C.c_size_t), ('flags', C.c_uint32), ('next', C.c_void_p),
                    ('reserved', C.c_size_t), ('offset', C.c_uint32),
                    ('reserved_array', C.c_size_t * 8)]

    def __init__(self):
        self.m = C.WinDLL('winmm')
        bind(self.m, 'midiOutGetNumDevs', C.c_uint, [])
        bind(self.m, 'midiOutGetDevCapsW', C.c_uint, [C.c_size_t, C.POINTER(self.Caps), C.c_uint])
        bind(self.m, 'midiOutOpen', C.c_uint, [C.POINTER(C.c_void_p), C.c_uint, C.c_size_t, C.c_size_t, C.c_uint])
        for name in ('midiOutPrepareHeader', 'midiOutLongMsg', 'midiOutUnprepareHeader'):
            bind(self.m, name, C.c_uint, [C.c_void_p, C.POINTER(self.Header), C.c_uint])
        bind(self.m, 'midiOutClose', C.c_uint, [C.c_void_p])

    def outputs(self):
        result = []
        for i in range(self.m.midiOutGetNumDevs()):
            caps = self.Caps()
            if not self.m.midiOutGetDevCapsW(i, C.byref(caps), C.sizeof(caps)):
                result.append((i, caps.name))
        return result

    def activate(self, index):
        handle = C.c_void_p()
        if self.m.midiOutOpen(C.byref(handle), index, 0, 0, 0):
            raise RuntimeError('Cannot open Strike MIDI output. Close other MIDI applications.')
        data = C.create_string_buffer(ACTIVATION)
        header = self.Header(data=C.cast(data, C.c_void_p), length=len(ACTIVATION))
        size = C.sizeof(header)
        try:
            if self.m.midiOutPrepareHeader(handle, C.byref(header), size):
                raise RuntimeError('Could not prepare MIDI buffer.')
            if self.m.midiOutLongMsg(handle, C.byref(header), size):
                self.m.midiOutUnprepareHeader(handle, C.byref(header), size)
                raise RuntimeError('MIDI send failed.')
            # Keep the buffer alive until the driver releases it. The parent process
            # imposes a timeout; do not reset the whole MIDI device or free an in-use buffer.
            while not header.flags & 1:  # MHDR_DONE
                time.sleep(0.01)
            while self.m.midiOutUnprepareHeader(handle, C.byref(header), size) == 65:
                time.sleep(0.01)  # MIDIERR_STILLPLAYING
        finally:
            self.m.midiOutClose(handle)


class LinuxMIDI:
    def __init__(self):
        self.command = shutil.which('amidi')
        if not self.command:
            raise RuntimeError('Install alsa-utils on the USB host to provide amidi.')

    def outputs(self):
        run = subprocess.run([self.command, '-l'], capture_output=True, text=True, timeout=3)
        if run.returncode:
            raise RuntimeError('Cannot list ALSA MIDI outputs. Check MIDI device permissions.')
        result = []
        for line in run.stdout.splitlines():
            match = re.match(r'^\s*([IO]+)\s+(hw:\d+,\d+(?:,\d+)?)\s+(.+)$', line)
            if match and 'O' in match[1]:
                result.append((match[2], match[3].strip()))
        return result

    def activate(self, address):
        run = subprocess.run([self.command, '-p', address, '-S', ACTIVATION.hex()],
                             capture_output=True, timeout=3)
        if run.returncode:
            raise RuntimeError('ALSA MIDI send failed. Check USB and MIDI device permissions.')


def execute(selected=None, backend=None):
    if backend is None:
        cls = {'Darwin': MacMIDI, 'Windows': WindowsMIDI, 'Linux': LinuxMIDI}.get(platform.system())
        if not cls:
            raise RuntimeError('This MIDI host platform is not supported.')
        backend = cls()
    outputs = [(address, name) for address, name in backend.outputs() if strike_name(name)]
    if selected is None:
        return {'outputs': [{'id': output_id(a, n), 'name': n} for a, n in outputs]}
    matches = [(a, n) for a, n in outputs if output_id(a, n) == selected]
    if len(matches) != 1:
        raise ValueError('Selected Strike is no longer connected. Refresh outputs and select again.')
    backend.activate(matches[0][0])
    return {'sent': True}


if __name__ == '__main__':
    try:
        print(json.dumps(execute(sys.argv[1] if len(sys.argv) == 2 else None)))
    except Exception as exc:
        print(json.dumps({'error': str(exc)}))
        sys.exit(1)
