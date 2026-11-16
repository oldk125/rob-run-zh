"""Run cache transactions only in temporary fake games/profiles, never real paths."""
import argparse
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile

import addon
from manager import digest, read_json


class PowerCut(BaseException):
    pass


@contextmanager
def patched(obj, name, value):
    original = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield original
    finally:
        setattr(obj, name, original)


def rejects(action, exception=RuntimeError):
    try:
        action()
    except exception as error:
        return str(error)
    raise AssertionError(f'Expected {exception.__name__}')


def snapshot(root):
    return {str(p.relative_to(root)): (digest(p), p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file() and p.name != '.codex_zh_addon.lock'}


def check_delta():
    import bsdiff4
    sha = lambda value: hashlib.sha256(value).hexdigest()
    with tempfile.TemporaryDirectory(prefix='rob-zh-delta-tests-') as temp:
        base = Path(temp).resolve()
        package, game = base / 'package', base / 'game'
        (package / 'data/addon').mkdir(parents=True)
        game.mkdir()
        (game / 'ROB RUN.exe').write_bytes(b'fake executable; never executed')
        original = b'original resource\n' * 30
        translated = original.replace(b'original', '中文资源'.encode())
        delta = bsdiff4.diff(original, translated)
        (game / 'original.bundle').write_bytes(original)
        patch_file = package / 'resource.bsdiff'
        patch_file.write_bytes(delta)
        spec = {'original_sha256': {'original.bundle': sha(original)}, 'files': [
            {'source': 'resource.bsdiff', 'target': 'codex_zh_addon/zh.bundle', 'sha256': sha(translated),
             'patch': {'format': 'bsdiff4', 'base': 'original.bundle', 'sha256': sha(delta)}}]}
        for extension in ['bin', 'hash']:
            name = 'catalog_test.' + extension
            content = ('test cache ' + extension).encode()
            (package / name).write_bytes(content)
            spec['files'].append({'source': name, 'target': 'com.unity.addressables/' + name,
                                  'sha256': sha(content)})
        manifest = package / 'data/addon/manifest.json'
        manifest.write_text(json.dumps(spec), encoding='utf-8')
        def fail_rebuild(*args):
            raise AssertionError('Read-only/status/idempotent/remove must not rebuild')
        with patched(addon, 'BASE', package), patched(addon, 'require_closed', lambda: None):
            # Reject malformed/escaping bases even when explicitly listed as originals.
            for bad_base in ['unlisted.bundle', '../outside.bundle', str(base / 'outside.bundle')]:
                bad = json.loads(json.dumps(spec))
                bad['files'][0]['patch']['base'] = bad_base
                if bad_base != 'unlisted.bundle':
                    bad['original_sha256'][bad_base] = sha(original)
                manifest.write_text(json.dumps(bad), encoding='utf-8')
                rejects(lambda: addon.plan(game, base / 'invalid-path', verify_game=False))
                assert not (base / 'invalid-path').exists()
            manifest.write_text(json.dumps(spec), encoding='utf-8')
            # Simulate files changing after plan's first verification: no profile transaction.
            planner = addon.plan
            for name, changed_file, content in [('base', game / 'original.bundle', original),
                                                 ('patch', patch_file, delta)]:
                profile = base / ('corrupt-' + name)
                def change_after_plan(*args, **kwargs):
                    result = planner(*args, **kwargs)
                    changed_file.write_bytes(b'corrupt actual read')
                    return result
                try:
                    with patched(addon, 'plan', change_after_plan):
                        assert '校验失败' in rejects(lambda: addon.install(game, profile))
                    assert not snapshot(profile), 'Corrupt delta input wrote profile payload or journal'
                finally:
                    changed_file.write_bytes(content)
            profile = base / 'wrong-result'
            with patched(bsdiff4, 'patch', lambda *args: b'wrong output'):
                assert '重建结果校验失败' in rejects(lambda: addon.install(game, profile))
            assert not snapshot(profile)
            profile = base / 'installed'
            addon.install(game, profile)
            assert (profile / 'codex_zh_addon/zh.bundle').read_bytes() == translated
            before = snapshot(profile)
            with patched(addon, 'prepare_payloads', fail_rebuild), patched(bsdiff4, 'patch', fail_rebuild):
                assert '已安装' in addon.status(game, profile)
                assert '已安装' in addon.install(game, profile)
                assert snapshot(profile) == before
                # Removal still works when the base resource has disappeared.
                (game / 'original.bundle').unlink()
                addon.remove(game, profile)
            assert not snapshot(profile)
    print('PASS: delta bytes exact; base/patch actual-read and output SHA checks before transaction; unsafe base rejection; status, idempotent install and removal never rebuild; removal needs no base resource.')


def check(real_game, legacy_dirs=None):
    check_delta()
    real_game = Path(real_game).resolve()
    legacy_dirs = [Path(folder).resolve() for folder in (legacy_dirs or [])]
    old_catalogs = [(folder / 'catalog.bin').read_bytes() for folder in legacy_dirs
                    if (folder / 'catalog.bin').is_file()]
    with tempfile.TemporaryDirectory(prefix='rob-zh-cache-tests-') as temp:
        base = Path(temp).resolve()
        _, spec, payloads = addon.plan(real_game, base / 'unused')
        rebuilt = base / 'rebuilt'
        rebuilt.mkdir()
        complete = addon.prepare_payloads(real_game, spec, payloads, rebuilt)
        complete_bytes = {str(target.relative_to(base / 'unused')): source.read_bytes()
                          for source, target, _ in complete}
        # Regression: this sidecar is the exact supported base-version marker,
        # not a checksum recomputed from the modified community catalog bytes.
        binding = spec['catalog_base_override']
        marker_item = next(x for x in spec['files'] if Path(x['target']).suffix == '.hash')
        catalog_item = next(x for x in spec['files'] if Path(x['target']).suffix == '.bin')
        marker_bytes = complete_bytes[str(Path(marker_item['target']))]
        official_marker = real_game / binding['base_marker']
        official_catalog = real_game / binding['base_catalog']
        candidate_catalog = complete_bytes[str(Path(catalog_item['target']))]
        assert marker_bytes == official_marker.read_bytes(), 'Do not regenerate catalog.hash from candidate content'
        assert marker_bytes.decode('ascii').strip() == binding['inherited_base_version_fingerprint']
        assert hashlib.sha256(candidate_catalog).hexdigest() == catalog_item['sha256'] != digest(official_catalog)
        assert hashlib.md5(candidate_catalog, usedforsecurity=False).hexdigest() != marker_bytes.decode('ascii').strip()
        assert spec['original_sha256'][binding['base_catalog']] == binding['base_catalog_sha256'] == digest(official_catalog)
        assert spec['original_sha256'][binding['base_marker']] == binding['base_marker_sha256'] == digest(official_marker)
        settings_key = str(Path('ROB RUN_Data/StreamingAssets/aa/settings.json'))
        assert settings_key in spec['original_sha256']
        assert spec['original_sha256'][settings_key] == digest(real_game / settings_key)
        assert binding['candidate_is_official_content'] is False
        assert binding['real_base_update_supported'] is False
        game = base / 'fake-game'
        game.mkdir()
        (game / 'ROB RUN.exe').write_bytes(b'fake executable marker; never executed')
        for relative in spec['original_sha256']:
            destination = game / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(real_game / relative, destination)
        aa = Path('ROB RUN_Data/StreamingAssets/aa/StandaloneWindows64')
        for item in spec['files']:
            path = Path(item['target'])
            if path.parent.name == 'com.unity.addressables':
                shutil.copyfile(real_game / aa / path.name, game / aa / path.name)
        protected_before = {n: digest(game / n) for n in spec['original_sha256']}
        real_before = {n: digest(real_game / n) for n in spec['original_sha256']}
        closed_checks = []
        def require_fake_closed():
            closed_checks.append(True)
        def make_profile(name, official=True):
            profile = base / name
            root, _, payloads = addon.plan(game, profile)
            caches = addon.cache_pair(root, payloads)
            if official:
                for _, target, _ in caches:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(game / aa / target.name, target)
            return profile, payloads, caches
        def cache_hashes(caches):
            return {p: digest(p) for _, p, _ in caches}
        def assert_cache(caches, expected):
            assert all(p.is_file() and digest(p) == sha for p, sha in expected.items())
        def assert_absent(profile, payloads):
            assert not any(p.exists() for _, p, _ in payloads)
            assert not (profile / 'codex_zh_addon').exists()
        def restore_legacy_payloads(profile, payloads, old_files):
            for source, path, _ in payloads:
                key = str(path.relative_to(profile))
                if key not in old_files:
                    path.unlink()
                    continue
                if digest(path) == old_files[key]:
                    continue
                candidates = []
                for legacy_dir in legacy_dirs:
                    name = 'catalog' + path.suffix if path.parent.name == 'com.unity.addressables' else path.name
                    if path.name == 'font-extension.bundle':
                        name = 'font_zh.bundle'
                    for fixture in {legacy_dir / name, legacy_dir / source.name}:
                        if fixture.is_file():
                            candidates.append(fixture.read_bytes())
                if path.parent.name == 'com.unity.addressables' and path.suffix == '.hash':
                    candidates.extend(hashlib.md5(value, usedforsecurity=False).hexdigest().encode('ascii')
                                      for value in old_catalogs)
                content = next((value for value in candidates if hashlib.sha256(value).hexdigest() == old_files[key]), None)
                if content is not None:
                    path.write_bytes(content)
                else:
                    assert not legacy_dirs, f'Legacy fixture does not match shipped allowlist: {path.name}'
                    path.unlink()  # Exercise an interrupted old install when no complete fixture was supplied.

        with patched(addon, 'require_closed', require_fake_closed):
            # A genuine base change must be rejected before creating any payload.
            for relative in [binding['base_catalog'], binding['base_marker']]:
                original = (game / relative).read_bytes()
                profile = base / ('wrong-base-' + Path(relative).suffix[1:])
                try:
                    (game / relative).write_bytes(b'changed temporary official base fixture')
                    assert '原版资源不匹配' in rejects(lambda: addon.install(game, profile, True))
                    assert not (profile / 'codex_zh_addon').exists()
                    assert not (profile / 'com.unity.addressables').exists()
                    assert all(p.name == '.codex_zh_addon.lock' for p in profile.rglob('*') if p.is_file())
                finally:
                    (game / relative).write_bytes(original)
            # Existing no-cache behavior and legacy installed.json remain supported.
            profile, payloads, caches = make_profile('no-cache', False)
            addon.install(game, profile)
            assert addon.status(game, profile).startswith('附加语言已安装')
            before = snapshot(profile)
            assert '已安装' in addon.install(game, profile)
            assert snapshot(profile) == before, 'Repeated install rewrote files'
            owner = profile / 'codex_zh_addon'
            state = read_json(owner / 'installed.json')
            legacy = {'phase': 'installed', 'files': state['files']}
            addon.atomic_write(owner / 'installed.json', __import__('json').dumps(legacy).encode())
            addon.remove(game, profile)
            assert_absent(profile, payloads)

            # Only an exact official pair can be explicitly backed up and switched.
            profile, payloads, caches = make_profile('official')
            originals = cache_hashes(caches)
            assert '可备份切换' in addon.status(game, profile)
            rejects(lambda: addon.install(game, profile))
            assert not (profile / 'codex_zh_addon').exists()
            addon.install(game, profile, allow_official_cache=True)
            owner = profile / 'codex_zh_addon'
            state = read_json(owner / 'installed.json')
            assert state['schema'] == 2 and state['phase'] == 'installed'
            for _, path, expected in caches:
                item = state['original_cache'][str(path.relative_to(profile))]
                assert item['sha256'] == originals[path]
                assert digest(owner / item['backup']) == originals[path]
                assert digest(path) == expected
            before = snapshot(profile)
            assert '已安装' in addon.install(game, profile, allow_official_cache=True)
            assert before == snapshot(profile)
            addon.remove(game, profile)
            assert_cache(caches, originals)
            assert not owner.exists()

            # Initial journal failure must not leave an orphan owner.
            profile, payloads, caches = make_profile('journal-failure')
            originals = cache_hashes(caches)
            atomic = addon.atomic_write
            def fail_journal(path, data):
                if Path(path).name == 'installed.json':
                    raise OSError('injected initial journal write failure')
                return atomic(path, data)
            with patched(addon, 'atomic_write', fail_journal):
                rejects(lambda: addon.install(game, profile, True), OSError)
            assert_cache(caches, originals)
            assert not (profile / 'codex_zh_addon').exists()

            # Backup pair must complete before the first cache mutation.
            profile, payloads, caches = make_profile('backup-failure')
            originals = cache_hashes(caches)
            publish = addon.publish_new
            def fail_backup(source, target, expected, root):
                if target.parent.name == 'cache-backup' and target.suffix == '.hash':
                    raise OSError('injected second backup failure')
                return publish(source, target, expected, root)
            with patched(addon, 'publish_new', fail_backup):
                rejects(lambda: addon.install(game, profile, True), OSError)
            assert_cache(caches, originals)
            assert not (profile / 'codex_zh_addon').exists()

            # A failure writing the second cache file rolls the first one back.
            profile, payloads, caches = make_profile('switch-failure')
            originals = cache_hashes(caches)
            writer = addon.write_cache
            calls = 0
            def fail_second(*args):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError('injected second cache write failure')
                return writer(*args)
            with patched(addon, 'write_cache', fail_second):
                rejects(lambda: addon.install(game, profile, True), OSError)
            assert_cache(caches, originals)
            assert not (profile / 'codex_zh_addon').exists()

            # A power loss bypasses exception rollback; fresh remove recovers mixed pair.
            profile, payloads, caches = make_profile('power-cut')
            originals = cache_hashes(caches)
            def cut_after_write(*args):
                writer(*args)
                raise PowerCut()
            with patched(addon, 'write_cache', cut_after_write):
                rejects(lambda: addon.install(game, profile, True), PowerCut)
            owner = profile / 'codex_zh_addon'
            assert read_json(owner / 'installed.json')['phase'] == 'switching_cache'
            assert digest(caches[0][1]) == caches[0][2]
            assert digest(caches[1][1]) == originals[caches[1][1]]
            addon.remove(game, profile)
            assert_cache(caches, originals)
            assert not owner.exists()

            # Power loss during restore must not consume either backup.
            profile, payloads, caches = make_profile('restore-cut')
            originals = cache_hashes(caches)
            addon.install(game, profile, True)
            with patched(addon, 'write_cache', cut_after_write):
                rejects(lambda: addon.remove(game, profile), PowerCut)
            owner = profile / 'codex_zh_addon'
            assert read_json(owner / 'installed.json')['phase'] == 'restoring_cache'
            assert len(list((owner / 'cache-backup').iterdir())) == 2
            addon.remove(game, profile)
            assert_cache(caches, originals)
            assert not owner.exists()

            # Cleanup is restartable even if one backup was already removed.
            profile, payloads, caches = make_profile('cleanup-cut')
            originals = cache_hashes(caches)
            addon.install(game, profile, True)
            unlink = Path.unlink
            def cut_after_backup_delete(path, *args, **kwargs):
                result = unlink(path, *args, **kwargs)
                if path.parent.name == 'cache-backup':
                    raise PowerCut()
                return result
            with patched(Path, 'unlink', cut_after_backup_delete):
                rejects(lambda: addon.remove(game, profile), PowerCut)
            assert read_json(profile / 'codex_zh_addon/installed.json')['phase'] == 'cleanup'
            addon.remove(game, profile)
            assert_cache(caches, originals)

            # Unknown changes, including unknown/mixed initial caches, stay untouched.
            profile, payloads, caches = make_profile('unknown-cache')
            caches[0][1].write_bytes(b'unknown cache')
            before = snapshot(profile)
            rejects(lambda: addon.install(game, profile, True))
            assert before == snapshot(profile)
            assert not (profile / 'codex_zh_addon').exists()
            profile, payloads, caches = make_profile('unknown-after-install')
            addon.install(game, profile, True)
            caches[1][1].write_bytes(b'external change during ownership')
            before = snapshot(profile)
            rejects(lambda: addon.remove(game, profile))
            assert snapshot(profile) == before
            assert (profile / 'codex_zh_addon/cache-backup').is_dir()

            profile, payloads, caches = make_profile('tampered-backup')
            addon.install(game, profile, True)
            backup = profile / 'codex_zh_addon/cache-backup' / caches[0][1].name
            backup.write_bytes(b'unknown backup data')
            before = snapshot(profile)
            rejects(lambda: addon.remove(game, profile))
            assert snapshot(profile) == before

            # Official cache alone must not hide unknown bundles or broken backups.
            profile, payloads, caches = make_profile('status-unknown')
            addon.install(game, profile, True)
            for _, target, _ in caches:
                shutil.copyfile(game / aa / target.name, target)
            payloads[0][1].write_bytes(b'unknown bundle')
            assert '官方' not in addon.status(game, profile)
            payloads[0][1].write_bytes(complete_bytes[str(payloads[0][1].relative_to(profile))])
            backup = profile / 'codex_zh_addon/cache-backup' / caches[0][1].name
            backup.write_bytes(b'broken backup')
            assert '官方' not in addon.status(game, profile)

            # Only the exact shipped legacy files map may be removed/migrated.
            for version, old_files in enumerate(spec.get('legacy_files', [])):
                for restored in [False, True]:
                    profile, payloads, caches = make_profile(f'legacy-{version}-{restored}')
                    originals = cache_hashes(caches)
                    addon.install(game, profile, True)
                    owner = profile / 'codex_zh_addon'
                    state_path = owner / 'installed.json'
                    state = read_json(state_path)
                    state['files'] = old_files
                    restore_legacy_payloads(profile, payloads, old_files)
                    addon.atomic_write(state_path, json.dumps(state).encode('utf-8'))
                    if restored:
                        for _, target, _ in caches:
                            shutil.copyfile(game / aa / target.name, target)
                    assert addon.status(game, profile).startswith('旧版附加语言记录')
                    before = snapshot(profile)
                    assert '先移除旧版' in rejects(lambda: addon.install(game, profile, True))
                    assert snapshot(profile) == before
                    addon.remove(game, profile)
                    assert_cache(caches, originals)
                    assert not owner.exists()
                # A current-version target absent from the old record is unowned.
                extras = [str(path.relative_to(profile)) for _, path, _ in payloads
                          if str(path.relative_to(profile)) not in old_files]
                if extras:
                    profile, payloads, caches = make_profile(f'legacy-{version}-untracked-new-target')
                    addon.install(game, profile, True)
                    state_path = profile / 'codex_zh_addon/installed.json'
                    state = read_json(state_path)
                    state['files'] = old_files
                    restore_legacy_payloads(profile, payloads, old_files)
                    extra = profile / extras[0]
                    extra.write_bytes(b'untracked new-version target; must survive old removal')
                    addon.atomic_write(state_path, json.dumps(state).encode('utf-8'))
                    for _, target, _ in caches:
                        shutil.copyfile(game / aa / target.name, target)
                    addon.remove(game, profile)
                    assert extra.read_bytes() == b'untracked new-version target; must survive old removal'
                    assert not state_path.exists()
                    assert '缺少有效记录' in addon.status(game, profile)
            profile, payloads, caches = make_profile('unknown-record')
            addon.install(game, profile, True)
            state_path = profile / 'codex_zh_addon/installed.json'
            state = read_json(state_path)
            state['files'][str(caches[1][1].relative_to(profile))] = '0' * 64
            addon.atomic_write(state_path, json.dumps(state).encode('utf-8'))
            before = snapshot(profile)
            rejects(lambda: addon.install(game, profile, True))
            rejects(lambda: addon.remove(game, profile))
            rejects(lambda: addon.status(game, profile))
            assert snapshot(profile) == before

            # A refreshed official pair wins over an old backup, even after game update.
            profile, payloads, caches = make_profile('official-refresh')
            addon.install(game, profile, True)
            game_cache_before = {game / aa / target.name: (game / aa / target.name).read_bytes() for _, target, _ in caches}
            for _, target, _ in caches:
                official = game / aa / target.name
                official.write_bytes(b'new official version: ' + target.suffix.encode())
                shutil.copyfile(official, target)
            refreshed = cache_hashes(caches)
            protected_cache = any(str((aa / p.name)) in spec['original_sha256'] for _, p, _ in caches)
            if protected_cache:
                assert '原版资源不匹配' in rejects(lambda: addon.status(game, profile))
                assert '原版资源不匹配' in rejects(lambda: addon.install(game, profile, True))
            else:
                assert '官方版本' in addon.status(game, profile)
                assert '请先移除' in rejects(lambda: addon.install(game, profile, True))
            assert '官方内容缓存已保留' in addon.remove(game, profile)
            assert_cache(caches, refreshed)
            assert not (profile / 'codex_zh_addon').exists()
            for path, content in game_cache_before.items():
                path.write_bytes(content)  # Reset only this temporary game fixture.

            # Previous add-only install rejects a half-official pair, still preserves both official files.
            profile, payloads, caches = make_profile('old-mixed', False)
            addon.install(game, profile)
            shutil.copyfile(game / aa / caches[0][1].name, caches[0][1])
            caches[1][1].write_bytes(b'external mismatched hash')
            before = snapshot(profile)
            rejects(lambda: addon.remove(game, profile))
            assert snapshot(profile) == before
            for source, target, _ in caches:
                target.write_bytes(complete_bytes[str(target.relative_to(profile))])
            addon.remove(game, profile)
            assert_absent(profile, payloads)

            # Extra owner files are retained; operation lock remains exclusive.
            profile, payloads, caches = make_profile('extra-owner', False)
            addon.install(game, profile)
            extra = profile / 'codex_zh_addon/user-note.txt'
            extra.write_text('keep this', encoding='utf-8')
            addon.remove(game, profile)
            assert extra.read_text(encoding='utf-8') == 'keep this'
            with addon.profile_lock(profile):
                rejects(lambda: addon.install(game, profile, True))

            # The no-cache creation path still rolls back a failed payload publish.
            profile, payloads, caches = make_profile('new-publish-failure', False)
            count = 0
            def fail_third(*args):
                nonlocal count
                count += 1
                if count == 3:
                    raise OSError('injected new payload failure')
                return publish(*args)
            with patched(addon, 'publish_new', fail_third):
                rejects(lambda: addon.install(game, profile), OSError)
            assert_absent(profile, payloads)

        assert protected_before == {n: digest(game / n) for n in spec['original_sha256']}
        assert real_before == {n: digest(real_game / n) for n in spec['original_sha256']}
        assert closed_checks
    print('PASS: exact base-version marker (not candidate MD5), protected catalog/bin/hash/settings, real base-change refusal; official backup/switch/restore; idempotent no-write; exact legacy allowlist recovery/restored removal, new untracked target preservation and unknown-record rejection; legacy/no-cache compatibility; journal/backup/second-cache failure rollback; interrupted install/restore/cleanup recovery; unknown/tampered/mixed protection; official refresh preserved; lock; original game hashes unchanged. All writes used temporary fake games/profiles.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--game', required=True, help='Read-only original game source for the temporary fixture')
    parser.add_argument('--legacy-dir', action='append', help='Read-only previous payload snapshot; repeat for multiple revisions')
    args = parser.parse_args()
    check(args.game, args.legacy_dir)
