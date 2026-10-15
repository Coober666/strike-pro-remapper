"""Test and package the native setlist viewer using Apple's installed compiler.

No package downloads, Xcode test frameworks, user library reads or app launching.
An explicit --render-preview renders the bundled synthetic demo only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys


def run(arguments):
    print('+ ' + ' '.join(map(str, arguments)), flush=True)
    subprocess.run(list(map(str, arguments)), check=True)


def build(output, revision, render_preview=False):
    if sys.platform != 'darwin':
        raise ValueError('Build on macOS with Apple Command Line Tools or Xcode.')
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Revision must be the full source commit SHA.')
    root = Path(__file__).resolve().parent.parent
    source = root / 'native/StrikeCompanion'
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    compiler = subprocess.check_output(['xcrun', '--find', 'swiftc'], text=True).strip()
    version = subprocess.check_output([compiler, '--version'], stderr=subprocess.STDOUT, text=True).strip()
    sdk = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
    target = ['-sdk', sdk, '-target', 'arm64-apple-macosx14.0', '-swift-version', '6']
    # A standalone executable exercises production model/navigation code without
    # depending on the broken Swift Testing integration in some CLT releases.
    contracts = output / 'companion-contracts'
    run([compiler, *target, source / 'Sources/Setlist.swift', source / 'Tests/Contracts.swift', '-o', contracts])
    run([contracts, source])
    bundle = output / 'Strike Companion.app'
    executable = bundle / 'Contents/MacOS/StrikeCompanion'
    executable.parent.mkdir(parents=True)
    resources = bundle / 'Contents/Resources'
    resources.mkdir()
    run([compiler, *target, '-O', source / 'Sources/Setlist.swift',
         source / 'Sources/StrikeCompanion.swift', '-o', executable])
    info = {
        'CFBundleExecutable': 'StrikeCompanion', 'CFBundleIdentifier': 'net.cooberlab.strike-companion',
        'CFBundleName': 'Strike Companion', 'CFBundleDisplayName': 'Strike Companion',
        'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': '0.1.0',
        'CFBundleVersion': '1', 'LSMinimumSystemVersion': '14.0',
        'NSHighResolutionCapable': True, 'NSPrincipalClass': 'NSApplication',
        'StrikeSourceRevision': revision,
        'CFBundleDocumentTypes': [{'CFBundleTypeName': 'Strike setlist JSON',
            'CFBundleTypeRole': 'Viewer', 'LSHandlerRank': 'Alternate',
            'LSItemContentTypes': ['public.json']}],
    }
    (bundle / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    shutil.copyfile(source / 'Resources/Demo.setlist.json', resources / 'Demo.setlist.json')
    (resources / 'build-identity.json').write_text(json.dumps({'revision': revision, 'swift': version}, indent=2) + '\n')
    run(['codesign', '--force', '--sign', '-', bundle])
    run(['codesign', '--verify', '--deep', '--strict', bundle])
    if render_preview:
        run([executable, '--render-demo', output / 'preview.png'])
    archive = output / 'Strike-Companion-macOS-arm64.zip'
    run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', bundle, archive])
    receipt = {'revision': revision, 'architecture': 'arm64', 'minimum_macos': '14.0',
               'artifact': archive.name, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
               'bytes': archive.stat().st_size, 'swift': version,
               'contracts': 'passed', 'signature': 'ad-hoc local build; not notarized',
               'demo_rendered': render_preview}
    (output / 'build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New output directory; never overwrites')
    parser.add_argument('--revision', required=True)
    parser.add_argument('--render-preview', action='store_true')
    args = parser.parse_args()
    build(args.output, args.revision, args.render_preview)


if __name__ == '__main__':
    main()
