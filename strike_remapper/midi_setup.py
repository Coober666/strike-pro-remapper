"""Read-only host MIDI diagnostics. Enumeration does not open an input port."""
import importlib.metadata
import platform
import sys

from strike_remapper.midi_input import NativeInput


def check_setup(backend=None, version=importlib.metadata.version):
    result = {'system': platform.system(), 'python': platform.python_version(),
              'package': None, 'inputs': [], 'status': 'missing',
              'message': '', 'detail': ''}
    try:
        result['package'] = version('python-rtmidi')
    except importlib.metadata.PackageNotFoundError:
        result['message'] = ('Install the optional MIDI package on the host, using the same Python '
                             'environment that launches the editor. See the setup guide below.')
        return result
    try:
        result['inputs'] = (backend or NativeInput()).inputs()
    except Exception as exc:
        result.update(status='driver-error', message=(
            'The MIDI package is installed, but input discovery failed. Check the host MIDI '
            'driver and USB connection. If another app is using the input, close it when convenient '
            'and check again.'), detail=str(exc)[:1000])
        return result
    result.update(status='ready' if result['inputs'] else 'no-inputs', message=(
        'MIDI inputs are visible. Select one and Record to check access and incoming notes. '
        'Discovery alone does not prove the input can be opened.' if result['inputs'] else
        'The MIDI helper works, but no inputs are visible. Connect and power on the module '
        'at the host, check its USB cable or MIDI interface, then check again.'))
    return result


if __name__ == '__main__':
    import json
    report = check_setup()
    print(json.dumps(report, indent=2))
    sys.exit(0 if report['status'] == 'ready' else 1)
