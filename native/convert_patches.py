"""Development-only BSDIFF40 to bounded gzip conversion; no Python at runtime."""
import argparse
import bz2
import copy
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import struct

MAX_BYTES = 256 * 1024 * 1024
MAGIC = b'RRZHDF1\0'


def off_t(value):
    number = int.from_bytes(value, 'little')
    return -(number & ((1 << 63) - 1)) if number >> 63 else number


def inflate(block):
    reader = bz2.BZ2Decompressor()
    result = reader.decompress(block, max_length=MAX_BYTES + 1)
    if len(result) > MAX_BYTES or not reader.eof or reader.unused_data:
        raise ValueError('Invalid or oversized bzip2 block')
    return result


def convert(data):
    if len(data) < 32 or data[:8] != b'BSDIFF40':
        raise ValueError('Expected BSDIFF40')
    control_size, diff_size, new_size = [off_t(data[p:p + 8]) for p in (8, 16, 24)]
    if min(control_size, diff_size, new_size) < 0 or max(control_size, diff_size, new_size) > MAX_BYTES:
        raise ValueError('Invalid source lengths')
    if 32 + control_size + diff_size > len(data):
        raise ValueError('Truncated source patch')
    control = inflate(data[32:32 + control_size])
    difference = inflate(data[32 + control_size:32 + control_size + diff_size])
    extra = inflate(data[32 + control_size + diff_size:])
    if len(control) % 24 or len(difference) + len(extra) != new_size:
        raise ValueError('Invalid unpacked source lengths')
    payload = struct.pack('<4q', new_size, len(control), len(difference), len(extra)) + control + difference + extra
    if len(payload) > MAX_BYTES:
        raise ValueError('Unpacked patch exceeds runtime limit')
    compressed = gzip.compress(payload, compresslevel=9, mtime=0)
    result = MAGIC + struct.pack('<2q', len(payload), len(compressed)) + compressed
    if len(result) > MAX_BYTES:
        raise ValueError('Compressed patch exceeds runtime limit')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    original = json.loads((source / 'data/addon/manifest.json').read_text(encoding='utf-8'))
    manifest = copy.deepcopy(original)
    rows = []
    for item in manifest['files']:
        path = (source / item['source']).resolve()
        if not path.is_relative_to(source):
            raise ValueError('Source escapes release tree')
        data = path.read_bytes()
        expected = item.get('patch', {}).get('sha256', item['sha256'])
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('Source patch hash mismatch: ' + item['source'])
        if 'patch' in item:
            if item['patch']['format'] != 'bsdiff4' or item['patch']['base'] not in manifest['original_sha256']:
                raise ValueError('Unsupported source patch or unregistered base')
            transformed = convert(data)
            item['source'] = str(Path(item['source']).with_suffix('.rrpatch')).replace('\\', '/')
            item['patch']['format'] = 'rrzh-gzip-v1'
            item['patch']['sha256'] = hashlib.sha256(transformed).hexdigest()
            destination = output / item['source']
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(transformed)
            rows.append({'source': item['source'], 'source_bytes': len(data), 'native_bytes': len(transformed),
                         'sha256': item['patch']['sha256'], 'target_sha256': item['sha256']})
        else:
            destination = output / item['source']
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
    assert {i['target']: i['sha256'] for i in original['files']} == {i['target']: i['sha256'] for i in manifest['files']}
    manifest['revision'] = 'native-gzip-delta-v1'
    target_manifest = output / 'data/addon/manifest.json'
    target_manifest.parent.mkdir(parents=True, exist_ok=True)
    target_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    result = {'converted': rows, 'target_hash_map_unchanged': True,
              'total_patch_bytes': sum(r['native_bytes'] for r in rows)}
    (output / 'conversion_result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
