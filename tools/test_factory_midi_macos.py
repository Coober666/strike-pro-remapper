"""macOS-only native transport test: sends solely to our temporary virtual endpoint."""
import ctypes as C
from pathlib import Path
import platform
import struct
import sys
import threading
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strike_remapper.factory_midi import ACTIVATION, MacMIDI, bind, execute, output_id


def main():
    if platform.system() != 'Darwin':
        print('skip: CoreMIDI virtual-destination test requires macOS')
        return
    driver = MacMIDI()
    received = []
    ready = threading.Event()
    read_proc = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, C.c_void_p)

    @read_proc
    def capture(packets, _ref, _source):
        # CoreMIDI's MIDI 1.0 packet-list ABI is packed to 4 bytes. First packet:
        # list count (4), timestamp (8), length (2), then data.
        header = C.string_at(packets, 14)
        length = struct.unpack_from('=H', header, 12)[0]
        received.append(C.string_at(packets + 14, length))
        ready.set()

    bind(driver.m, 'MIDIDestinationCreate', C.c_int32,
         [C.c_uint32, C.c_void_p, read_proc, C.c_void_p, C.POINTER(C.c_uint32)])
    bind(driver.m, 'MIDIEndpointDispose', C.c_int32, [C.c_uint32])
    client, endpoint = C.c_uint32(), C.c_uint32()
    label = ('Strike virtual test ' + uuid.uuid4().hex).encode()
    name = driver.cf.CFStringCreateWithCString(None, label, 0x08000100)
    try:
        assert driver.m.MIDIClientCreate(name, None, None, C.byref(client)) == 0
        assert driver.m.MIDIDestinationCreate(client, name, capture, None, C.byref(endpoint)) == 0
        matches = [(address, label) for address, label in driver.outputs() if address == endpoint.value]
        assert len(matches) == 1, 'our virtual endpoint was not enumerated'
        address, label = matches[0]
        # Select the endpoint we just created, never the user's physical Strike.
        assert address == endpoint.value
        execute(output_id(address, label), driver)
        assert ready.wait(2), 'CoreMIDI did not deliver to the virtual destination'
        assert received == [ACTIVATION], received
        print('PASS: CoreMIDI delivered exactly one evidence-matching packet to our virtual endpoint')
    finally:
        if endpoint.value:
            driver.m.MIDIEndpointDispose(endpoint)
        if client.value:
            driver.m.MIDIClientDispose(client)
        driver.cf.CFRelease(name)


if __name__ == '__main__':
    main()
