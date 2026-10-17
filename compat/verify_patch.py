"""Verify vendored hashes and apply patch in a temporary directory, never live Hermes."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parent


def prepare(destination):
    manifest=json.loads((ROOT/'source-manifest.json').read_text())
    for name,expected in manifest['files'].items():
        source=ROOT/'upstream'/name
        if hashlib.sha256(source.read_bytes()).hexdigest()!=expected:
            raise ValueError(f'Source hash mismatch: {name}')
        target=Path(destination)/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
    subprocess.run(['git','apply','--check',str(ROOT/'hermes-per-launch-settings.patch')],cwd=destination,check=True,capture_output=True)
    subprocess.run(['git','apply',str(ROOT/'hermes-per-launch-settings.patch')],cwd=destination,check=True,capture_output=True)
    for name in manifest['files']:
        if name.endswith('.py'):
            compile((Path(destination)/name).read_text(),name,'exec')
    return manifest


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-remote',action='store_true',help='Opt in to public pinned-source downloads for digest comparison')
    args=parser.parse_args()
    if args.verify_remote:
        import urllib.request
        manifest=json.loads((ROOT/'source-manifest.json').read_text())
        for name,expected in manifest['files'].items():
            url=f"https://raw.githubusercontent.com/NousResearch/hermes-agent/{manifest['commit']}/{name}"
            with urllib.request.urlopen(url,timeout=15) as response:
                data=response.read(2_000_000)
            if hashlib.sha256(data).hexdigest()!=expected:
                raise ValueError(f'Remote hash mismatch: {name}')
    with tempfile.TemporaryDirectory(prefix='orpheus-hermes-patch-') as directory:
        prepare(directory)
    print('PASS: pinned source hashes, clean patch application, module compilation')
