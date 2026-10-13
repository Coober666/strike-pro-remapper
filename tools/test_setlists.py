"""Setlist persistence, isolation, readiness and paired HTTP boundaries."""
import copy
import hashlib
import http.client
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import strike_remap as app
from strike_remapper.setlists import Store, Conflict, validate, filename
from strike_remapper.wifi_editor import Pairing, make_handler


def document(*kits):
    return {'format': 'strike-setlist', 'version': 1, 'name': 'Friday show', 'notes': '',
            'numbered': True, 'entries': [{'kit': kit, 'song': 'Song', 'output': '', 'notes': ''} for kit in kits]}


class SetlistTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'library'
        (self.root / 'kits').mkdir(parents=True)
        self.store = Store(self.root)
        self.original = app.build_skt(app._KIT_BLOCK_TEMPLATE, [], [])
        (self.root / 'kits' / 'Original.skt').write_bytes(self.original)

    def test_portable_revision_guard_delete_and_rename(self):
        saved = self.store.save(document('Original.skt'))
        changed = copy.deepcopy(saved['document']); changed['name'] = 'Saturday show'
        with self.assertRaises(Conflict):
            self.store.save(changed, saved['id'], 'wrong')
        newer = self.store.save(changed, saved['id'], saved['revision'])
        with self.assertRaises(Conflict):
            self.store.delete(saved['id'], saved['revision'])
        self.assertEqual(self.store.load(saved['id']), newer)
        data = self.store.path(saved['id']).read_text(encoding='utf-8')
        self.assertNotIn(str(self.root), data)
        duplicate = self.store.save(json.loads(data))
        self.assertNotEqual(duplicate['id'], saved['id'])
        self.store.delete(saved['id'], newer['revision'])
        self.assertEqual((self.root / 'kits' / 'Original.skt').read_bytes(), self.original)
        self.assertEqual(len(self.store.listing()['setlists']), 1)

    def test_failed_replace_keeps_previous_document_and_cleans_temporary(self):
        saved = self.store.save(document('Original.skt'))
        draft = copy.deepcopy(saved['document']); draft['name'] = 'Not saved'
        with patch('strike_remapper.setlists.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.store.save(draft, saved['id'], saved['revision'])
        self.assertEqual(self.store.load(saved['id']), saved)
        self.assertEqual(len(list(self.store.folder.iterdir())), 1)

    def test_path_validation_and_limits(self):
        for invalid in ('../card/kit.skt', '/card/kit.skt', 'C:/card/kit.skt', 'folder\\kit.skt', 'kit.autosave.skt', './kit.skt', 'x//kit.skt'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.store.save(document(invalid))
        for bad in (None, [], {'format': 'strike-setlist', 'version': True}, document(*(['Original.skt']*129))):
            with self.assertRaises(ValueError):
                validate(bad)
        for invalid in ('../x', 'a'*32+'.json', None):
            with self.assertRaises(ValueError):
                self.store.load(invalid)
        with self.assertRaises(ValueError):
            self.store.copy_kit('Original.skt', '../new')
        self.assertFalse(self.store.folder.exists())

    def test_symlink_cannot_read_or_copy_an_outside_kit(self):
        outside = Path(self.tmp.name) / 'outside.skt'; outside.write_bytes(self.original)
        try:
            (self.root / 'kits' / 'Linked.skt').symlink_to(outside)
        except OSError:
            self.skipTest('Symlinks unavailable without Windows developer mode')
        self.assertEqual(len(self.store.listing()['kits']), 1)
        self.assertEqual(self.store.check(document('Linked.skt'))['rows'][0]['status'], 'blocked')
        with self.assertRaises(ValueError):
            self.store.copy_kit('Linked.skt', 'Copy')

    def test_missing_corrupt_duplicate_names_and_normalization(self):
        (self.root / 'kits' / 'Broken.skt').write_bytes(b'not a kit')
        draft = document('Original.skt', 'Original.skt', 'Missing.skt', 'Broken.skt')
        draft['numbered'] = False
        checked = self.store.check(draft)
        self.assertTrue(all(row['status'] == 'blocked' for row in checked['rows']))
        draft['numbered'] = True
        checked = self.store.check(draft)
        self.assertEqual(checked['rows'][0]['filename'], '001 Original.skt')
        self.assertEqual(checked['rows'][0]['status'], 'review')
        self.assertEqual(checked['rows'][1]['filename'], '002 Original.skt')
        self.assertLessEqual(len(filename('a'*100, 128)), 26)
        self.assertEqual(filename('CON'), 'Kit CON.skt')
        self.assertEqual(filename('Music/?*<>'), 'Music.skt')

    def test_copy_is_byte_exact_exclusive_and_checks_do_not_change_editor(self):
        before = copy.deepcopy(app.state)
        with patch.object(app, 'get_volumes', side_effect=AssertionError('must not inspect cards')):
            self.store.check(document('Original.skt'))
            result = self.store.copy_kit('Original.skt', 'Song copy')
        self.assertEqual((self.root / 'kits' / result['kit']).read_bytes(), self.original)
        with self.assertRaises(ValueError):
            self.store.copy_kit('Original.skt', 'song COPY')
        self.assertEqual(app.state, before)

    def test_local_and_factory_evidence_never_proves_missing_samples(self):
        payload = bytearray(62); payload[:4] = b'S1H '
        struct.pack_into('<HH', payload, 4, 0, 100)
        struct.pack_into('<H', payload, 24, 1)
        kit = app.build_skt(app._KIT_BLOCK_TEMPLATE, [{'id':'S1H', 'payload':payload, 'layer_a':0, 'layer_b':1}], ['Factory/Good.sin', 'Custom/Missing.sin'])
        (self.root / 'kits' / 'Assigned.skt').write_bytes(kit)
        catalog = Path(self.tmp.name) / 'catalog.json'
        catalog.write_text(json.dumps({'instruments': {'Factory/Good.sin': {}}}))
        store = Store(self.root, catalog)
        result = store.check(document('Assigned.skt'))['rows'][0]
        self.assertEqual(result['status'], 'review')
        self.assertIn('cannot be verified', str(result))
        self.assertIn('1 factory-catalog', str(result))
        self.assertNotIn('will be silent', str(result))
        self.assertIn('Samples and card contents are not checked', str(result))

    def test_paired_route_requires_owner_and_rejects_bad_body(self):
        old = app.LIBRARY_DIR
        app.set_library_root(self.root)
        self.addCleanup(app.set_library_root, old)
        pairing = Pairing('test-setlist-token', '127.0.0.1:0')
        handler = make_handler(app, pairing)
        server = app._Server(('127.0.0.1', 0), handler)
        pairing.authority = f'127.0.0.1:{server.server_port}'
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
        self.addCleanup(conn.close)
        def request(method, data=None, headers=None, route='/api/setlists'):
            conn.request(method, route, json.dumps(data) if data is not None else None, headers or {})
            response = conn.getresponse(); return response.status, json.loads(response.read())
        self.assertEqual(request('GET')[0], 401)
        cookie = pairing.pair('test-setlist-token').split(';')[0]
        headers = {'Cookie':cookie, 'Origin':'http://'+pairing.authority, 'Content-Type':'application/json'}
        self.assertEqual(request('GET', headers=headers)[0], 200)
        draft = {'action':'save', 'document':document('Original.skt')}
        self.assertEqual(request('POST', draft, headers)[0], 409)
        token = request('POST', {}, headers, '/wifi/editor')[1]['token']
        headers['X-Strike-Editor'] = token
        self.assertEqual(request('POST', [], headers)[0], 400)
        saved = request('POST', draft, headers)
        self.assertEqual(saved[0], 200)
        self.assertEqual(request('POST', {'action':'save', 'document':document(), 'id':saved[1]['id'], 'revision':'stale'}, headers)[0], 409)
        headers['Origin'] = 'http://other.invalid'
        self.assertEqual(request('POST', draft, headers)[0], 403)


if __name__ == '__main__':
    unittest.main()
