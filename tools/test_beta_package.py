"""Extracted beta starts with an external synthetic library and serves paired MIDI assets."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.build_beta import build, PREFIX

PROBE = r'''
import faulthandler, http.client, json, sys
faulthandler.dump_traceback_later(8, repeat=True)
from urllib.parse import urlparse, parse_qs
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import strike_remap as app
from strike_remapper.host import Host
app.get_volumes=lambda: (None,None)
host=Host()
try:
    host.start(sys.argv[2],bind='127.0.0.1',port=0)
    url=urlparse(host.pair_url)
    token=parse_qs(url.fragment)['pair'][0]
    conn=http.client.HTTPConnection(url.hostname,url.port,timeout=4)
    origin='http://'+url.netloc
    conn.request('POST','/wifi/pair',json.dumps({'token':token}),{'Content-Type':'application/json','Origin':origin})
    response=conn.getresponse(); assert response.status == 200; response.read()
    cookie=response.getheader('Set-Cookie').split(';')[0]
    assets=['/','/midi','/app.js','/app.css','/wifi/pair.js','/wifi/pair.css']
    assets += ['/midi/'+p.name for p in (Path(sys.argv[1])/'web'/'midi-toolkit').glob('*') if p.suffix in ('.js','.css')]
    for asset in assets:
        conn.request('GET',asset,headers={'Cookie':cookie})
        response=conn.getresponse(); data=response.read()
        assert response.status == 200 and data, (asset,response.status)
    conn.close()
finally:
    host.stop()
assert not (Path(sys.argv[1])/'library').exists()
print('Extracted source beta: paired editor and MIDI assets passed')
'''


class BetaPackageTests(unittest.TestCase):
    def test_archive_integrity_exclusions_permissions_and_relocated_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            first, second = base / 'one.zip', base / 'two.zip'
            build(first)
            build(second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                names = archive.namelist()
                self.assertEqual(len(names), len(set(names)))
                self.assertFalse(any('/library/' in n or '/.git/' in n or '/node_modules/' in n or '/test_' in n for n in names))
                manifest = json.loads(archive.read(PREFIX+'BETA-MANIFEST.json'))
                self.assertEqual(set(names), {PREFIX+n for n in manifest['files']} | {PREFIX+'BETA-MANIFEST.json'})
                for name, digest in manifest['files'].items():
                    self.assertEqual(hashlib.sha256(archive.read(PREFIX+name)).hexdigest(), digest)
                command = archive.getinfo(PREFIX+'launch-host.command')
                self.assertTrue((command.external_attr >> 16) & 0o111)
                self.assertNotIn(b'\r', archive.read(command))
                archive.extractall(base / 'Relocated application')
            root = base / 'Relocated application' / PREFIX
            try:
                result = subprocess.run([sys.executable, '-c', PROBE, str(root), str(base / 'External library')],
                                        cwd=base, capture_output=True, text=True, timeout=20)
            except subprocess.TimeoutExpired as exc:
                diagnostic = exc.stderr or b''
                if isinstance(diagnostic, bytes):
                    diagnostic = diagnostic.decode('utf-8', errors='replace')
                self.fail('Extracted beta exceeded 20 seconds. Child stacks:\n' + diagnostic)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with self.assertRaises(FileExistsError):
                build(first)


if __name__ == '__main__':
    unittest.main()
