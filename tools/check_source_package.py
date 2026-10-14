"""Check an actual source ZIP using only Python's standard library and temporary files."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

PROBE = r'''
import http.client, json, os, sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, sys.argv[1])
import strike_remap as app
from strike_remapper.host import Host
from strike_remapper.support import identity
app.get_volumes = lambda: (None, None)
app._find_strike_volumes = lambda: {}
host = Host()
try:
    host.start(sys.argv[2], bind='127.0.0.1', port=0)
    url = urlparse(host.pair_url)
    conn = http.client.HTTPConnection(url.hostname, url.port, timeout=5)
    conn.request('POST', '/wifi/pair', json.dumps({'token':parse_qs(url.fragment)['pair'][0]}),
                 {'Content-Type':'application/json','Origin':'http://'+url.netloc})
    response = conn.getresponse()
    assert response.status == 200
    response.read()
    cookie = response.getheader('Set-Cookie').split(';')[0]
    for asset in ('/', '/midi', '/midi/app.js', '/midi/core.js', '/app.js', '/app.css', '/wifi/pair.js'):
        conn.request('GET', asset, headers={'Cookie':cookie})
        response = conn.getresponse()
        assert response.status == 200 and response.read(), asset
    conn.close()
    with app.STATE_LOCK:
        app.create_new_kit('Source check')
        app.set_pad_param('S1H', 'la_level', 31)
        app.save_kit(str(Path(sys.argv[2])/'kits'/'Source check.skt'))
        app.set_pad_param('S1H', 'la_level', 32)
finally:
    host.stop()
library = Path(sys.argv[2])/'kits'
saved = library/'Source check.skt'
recovery = library/'Source check.autosave.skt'
assert saved.is_file() and recovery.is_file()
assert saved.read_bytes() != recovery.read_bytes()
assert not (Path(sys.argv[1])/'library').exists()
fallback = None
if sys.platform.startswith('linux') and not os.environ.get('DISPLAY'):
    import launch_editor
    try:
        launch_editor.main()
    except SystemExit as error:
        fallback = str(error)
        assert 'without Tk' in fallback or 'desktop session' in fallback, fallback
    else:
        raise AssertionError('Headless launcher did not explain terminal fallback')
print(json.dumps({'paired_assets':True,'save':True,'recovery':True,'headless_help':fallback,'identity':identity(Path(sys.argv[1]))}))
'''


def check(archive):
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    sidecar = archive.with_suffix('.sha256.txt')
    if sidecar.read_text().split()[0].lower() != digest:
        raise ValueError('ZIP checksum mismatch')
    with tempfile.TemporaryDirectory(prefix='strike-source-check-') as tmp:
        base = Path(tmp)
        with zipfile.ZipFile(archive) as bundle:
            name = 'strike-remapper-beta/BETA-MANIFEST.json'
            manifest = json.loads(bundle.read(name))
            expected = {'strike-remapper-beta/'+n: sha for n, sha in manifest['files'].items()}
            actual = {n: hashlib.sha256(bundle.read(n)).hexdigest()
                      for n in bundle.namelist() if not n.endswith('/') and n != name}
            if actual != expected or len(bundle.namelist()) != len(set(bundle.namelist())):
                raise ValueError('Package contents do not match manifest')
            for item in bundle.infolist():
                (base/item.filename).resolve().relative_to(base.resolve())
                if (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('Linked archive member')
            launcher = bundle.getinfo('strike-remapper-beta/launch-host.command')
            if not (launcher.external_attr >> 16) & 0o111 or b'\r' in bundle.read(launcher):
                raise ValueError('Mac launcher metadata is invalid')
            bundle.extractall(base)
        root = base/'strike-remapper-beta'
        result = subprocess.run([sys.executable, '-I', '-c', PROBE, str(root), str(base/'External library')],
                                cwd=base, capture_output=True, text=True, timeout=45)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        after = {n: hashlib.sha256((root/n).read_bytes()).hexdigest() for n in manifest['files']}
        if after != manifest['files']:
            raise ValueError('Application payload changed')
        print(json.dumps({'sha256':digest,'files':len(after),'runtime':json.loads(result.stdout)}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    check(parser.parse_args().archive)
