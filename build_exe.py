"""Package only the manifest's patches, UI assets and license notices."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def runtime_files():
    manifest = ROOT / 'data/addon/manifest.json'
    paths = [manifest, ROOT / 'DISCLAIMER.md',
             ROOT / 'THIRD_PARTY_NOTICES.md']
    for item in json.loads(manifest.read_text(encoding='utf-8'))['files']:
        path = (ROOT / item['source']).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError(f'无效的发布资源：{item["source"]}')
        paths.append(path)
    paths += sorted((ROOT / 'data/ui_icons').glob('*.png'))
    paths += sorted(ROOT.glob('*LICENSE.txt'))
    paths += sorted(p for p in (ROOT / 'third_party_licenses').rglob('*') if p.is_file())
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', default='ROB_RUN_CN')
    parser.add_argument('--output', type=Path, default=ROOT)
    parser.add_argument('--work', type=Path, default=ROOT / 'build')
    args = parser.parse_args()
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed',
               '--noupx', '--name', args.name, '--distpath', str(args.output.resolve()),
               '--workpath', str(args.work.resolve()), '--specpath', str(args.work.resolve()),
               '--paths', str(ROOT), '--exclude-module', 'UnityPy', '--exclude-module', 'PIL',
               '--icon', 'NONE']
    for path in runtime_files():
        command += ['--add-data', f'{path};{path.relative_to(ROOT).parent}']
    subprocess.run([*command, str(ROOT / 'ui_v2.py')], check=True)


if __name__ == '__main__':
    main()
