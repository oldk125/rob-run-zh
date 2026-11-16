"""Transactional user-cache language add-on. Never writes game installation files."""
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
import hashlib
import json
import msvcrt
import os
import re
import tempfile
import tkinter as tk
from tkinter import messagebox, ttk

from manager import BASE, atomic_write, digest, read_json, require_closed


def user_profile():
    return Path(os.environ['USERPROFILE']) / 'AppData/LocalLow/Kefir/ROB RUN'


@contextmanager
def profile_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    path = root / '.codex_zh_addon.lock'
    marker = b'ROB_RUN_ZH_ADDON_LOCK_V1\n'
    try:
        handle = path.open('x+b')
        handle.write(marker)
        handle.flush()
    except FileExistsError:
        handle = path.open('r+b')
    with handle:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError('另一实例正在操作附加语言，请等待完成。')
        try:
            handle.seek(0)
            if handle.read() != marker:
                raise RuntimeError('操作锁文件不属于本工具，未修改任何现有文件。')
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def locked(operation):
    @wraps(operation)
    def run(game, profile=None, *args, **kwargs):
        root = Path(profile).resolve() if profile else user_profile().resolve()
        with profile_lock(root):
            return operation(game, profile, *args, **kwargs)
    return run


def file_hash(path):
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise RuntimeError(f'目标不是普通文件，未覆盖：{path.name}')
    return digest(path)


def publish_new(source, target, expected, root):
    fd, name = tempfile.mkstemp(prefix='.codex-zh-stage-', dir=root)
    staging = Path(name)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(source.read_bytes())
            handle.flush()
            os.fsync(handle.fileno())
        if digest(staging) != expected:
            raise RuntimeError('附加包暂存文件校验失败。')
        os.rename(staging, target)  # Windows rename refuses an existing destination.
    finally:
        staging.unlink(missing_ok=True)


def write_cache(source, target, expected, allowed):
    """Stage and validate first; replace one known cache file atomically."""
    fd, name = tempfile.mkstemp(prefix='.codex-zh-cache-', dir=target.parent)
    staging = Path(name)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(source.read_bytes())
            handle.flush()
            os.fsync(handle.fileno())
        if digest(staging) != expected:
            raise RuntimeError('缓存暂存文件校验失败。')
        if file_hash(target) not in allowed:
            raise RuntimeError(f'缓存出现未知变化，未覆盖：{target.name}')
        os.replace(staging, target)
        if digest(target) != expected:
            raise RuntimeError('缓存回读校验失败。')
    finally:
        staging.unlink(missing_ok=True)


def patch_base(game, spec, patch):
    if (not isinstance(patch, dict) or patch.get('format') != 'bsdiff4'
            or not isinstance(patch.get('sha256'), str)
            or not re.fullmatch('[0-9a-f]{64}', patch['sha256'])
            or not isinstance(patch.get('base'), str)
            or patch['base'] not in spec['original_sha256']):
        raise RuntimeError('附加包差分清单无效。')
    relative = Path(patch['base'])
    base = game / relative
    if (relative.is_absolute() or '..' in relative.parts or base.resolve() != base
            or not base.is_relative_to(game)):
        raise RuntimeError('差分原版资源路径越界或含链接。')
    return base


def prepare_payloads(game, spec, payloads, temporary):
    """Rebuild and verify everything before the profile transaction begins."""
    game = Path(game).resolve()
    result = []
    for index, (item, (source, target, expected)) in enumerate(zip(spec['files'], payloads)):
        if 'patch' in item:
            import bsdiff4
            patch = item['patch']
            base = patch_base(game, spec, patch).read_bytes()
            delta = source.read_bytes()
            if hashlib.sha256(base).hexdigest() != spec['original_sha256'][patch['base']]:
                raise RuntimeError('差分原版资源校验失败，未安装。')
            if hashlib.sha256(delta).hexdigest() != patch['sha256']:
                raise RuntimeError('附加包差分内容校验失败，未安装。')
            rebuilt = bsdiff4.patch(base, delta)
            if hashlib.sha256(rebuilt).hexdigest() != expected:
                raise RuntimeError('差分重建结果校验失败，未安装。')
            source = temporary / str(index)
            source.write_bytes(rebuilt)
        result.append((source, target, expected))
    return result


def plan(game, profile=None, verify_game=True):
    game = Path(game).resolve()
    root = Path(profile).resolve() if profile else user_profile().resolve()
    spec = read_json(BASE / 'data/addon/manifest.json')
    if not (game / 'ROB RUN.exe').is_file():
        raise RuntimeError('请选择 ROB RUN 游戏目录。')
    if verify_game:
        for name, expected in spec['original_sha256'].items():
            if digest(game / name) != expected:
                raise RuntimeError('原版资源不匹配。请先还原旧汉化，或等待新版本适配。')
    payloads = []
    for item in spec['files']:
        relative = Path(item['target'])
        if (relative.is_absolute() or '..' in relative.parts or len(relative.parts) != 2
                or relative.parts[0] not in {'codex_zh_addon', 'com.unity.addressables'}):
            raise RuntimeError('附加包目标路径无效。')
        target = root / relative
        if target.resolve() != target or not target.is_relative_to(root):
            raise RuntimeError('附加包目标越界或含链接。')
        source = (BASE / item['source']).resolve()
        expected_source = item['sha256']
        if 'patch' in item:
            patch_base(game, spec, item['patch'])
            expected_source = item['patch']['sha256']
        if not source.is_relative_to(BASE.resolve()) or digest(source) != expected_source:
            raise RuntimeError('附加包内容校验失败。')
        payloads.append((source, target, item['sha256']))
    cache_pair(root, payloads)
    return root, spec, payloads


def cache_pair(root, payloads):
    caches = [p for p in payloads if p[1].parent == root / 'com.unity.addressables']
    if (len(caches) != 2 or {p.suffix for _, p, _ in caches} != {'.bin', '.hash'}
            or len({p.stem for _, p, _ in caches}) != 1
            or not all(p.name.startswith('catalog_') for _, p, _ in caches)):
        raise RuntimeError('附加包缓存清单无效。')
    return sorted(caches, key=lambda p: p[1].suffix)


def official_pair(game, caches):
    source = Path(game).resolve() / 'ROB RUN_Data/StreamingAssets/aa/StandaloneWindows64'
    return all(p.is_file() and not p.is_symlink() and (source / p.name).is_file()
               and file_hash(p) == digest(source / p.name) for _, p, _ in caches)


def cache_to_preserve(game, root, payloads):
    caches = cache_pair(root, payloads)
    if official_pair(game, caches):
        return {p for _, p, _ in caches}
    if all(file_hash(p) in {None, sha} for _, p, sha in caches):
        return set()
    raise RuntimeError('内容目录缓存存在未知变化或版本混配，未删除任何文件。')


def record(owner, state, phase):
    state['phase'] = phase
    atomic_write(owner / 'installed.json', json.dumps(state, ensure_ascii=False, indent=2).encode('utf-8'))


def expected_files(root, payloads):
    return {str(p.relative_to(root)): sha for _, p, sha in payloads}


def known_file_sets(root, payloads):
    """Accept only explicitly shipped legacy digests, never arbitrary old state."""
    current = expected_files(root, payloads)
    legacy = read_json(BASE / 'data/addon/manifest.json').get('legacy_files', [])
    cache_keys = {str(p.relative_to(root)) for _, p, _ in cache_pair(root, payloads)}
    if not isinstance(legacy, list):
        raise RuntimeError('旧版附加语言白名单格式无效。')
    for item in legacy:
        if (not isinstance(item, dict) or not cache_keys.issubset(item)
                or not set(item).issubset(current)
                or any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha) for sha in item.values())
                or item == current):
            raise RuntimeError('旧版附加语言白名单不符合本版迁移范围。')
    return current, legacy


def read_state(owner, root, payloads):
    path = owner / 'installed.json'
    if not path.is_file() or path.is_symlink():
        raise RuntimeError('未找到本工具的附加语言安装记录；已有目录未修改。')
    state = read_json(path)
    current, legacy = known_file_sets(root, payloads)
    if state.get('files') != current and state.get('files') not in legacy:
        raise RuntimeError('附加语言记录不在本版或明确支持的旧版白名单中，未修改任何文件。')
    if state.get('schema', 1) not in {1, 2}:
        raise RuntimeError('附加语言记录版本未知，未修改任何文件。')
    originals = state.get('original_cache', {})
    caches = cache_pair(root, payloads)
    if not isinstance(originals, dict):
        raise RuntimeError('官方缓存备份记录格式无效。')
    if originals and set(originals) != {str(p.relative_to(root)) for _, p, _ in caches}:
        raise RuntimeError('官方缓存备份记录不完整。')
    for _, target, _ in caches:
        item = originals.get(str(target.relative_to(root)))
        if originals and (not isinstance(item, dict)
                          or item.get('backup') != str(Path('cache-backup') / target.name)
                          or not isinstance(item.get('sha256'), str)
                          or not re.fullmatch('[0-9a-f]{64}', item['sha256'])):
            raise RuntimeError('官方缓存备份记录路径或校验值无效。')
    return state


def backups(owner, root, payloads, state, missing_ok=False):
    result = {}
    for _, target, _ in cache_pair(root, payloads):
        item = state.get('original_cache', {}).get(str(target.relative_to(root)))
        if item:
            path = owner / 'cache-backup' / target.name
            if path.resolve() != path:
                raise RuntimeError('官方缓存备份路径含链接。')
            value = file_hash(path)
            if value != item['sha256'] and not (missing_ok and value is None):
                raise RuntimeError(f'官方缓存备份缺失或校验失败，未覆盖缓存：{target.name}')
            result[target] = (path, item['sha256'])
    return result


def remove_owned(game, root, payloads, state):
    """Also recovers an interrupted install/restore using only journaled hashes."""
    owner = root / 'codex_zh_addon'
    caches = cache_pair(root, payloads)
    owned = [row for row in payloads if row not in caches]
    original = state.get('original_cache', {})
    preserved = official_pair(game, caches)
    before = {p: file_hash(p) for _, p, _ in caches}
    original_pair = bool(original) and all(before[p] == original[str(p.relative_to(root))]['sha256'] for _, p, _ in caches)
    # Preparation has not touched caches. Cleanup may have already deleted a
    # backup; in that phase the pair must already be fully restored/official.
    missing_ok = ((state.get('phase') == 'backing_up' and original_pair)
                  or (state.get('phase') == 'cleanup' and (original_pair or preserved)))
    saved = backups(owner, root, payloads, state, missing_ok)
    for _, path, sha in owned:
        if file_hash(path) not in {None, sha}:
            raise RuntimeError(f'附加资源存在未知变化，未删除任何文件：{path.name}')
    if not preserved:
        for _, path, sha in caches:
            allowed = {None, sha}
            if path in saved:
                allowed.add(saved[path][1])
            if before[path] not in allowed:
                raise RuntimeError('内容目录缓存存在未知变化或版本混配，未覆盖任何文件。')
        if state.get('phase') == 'cleanup' and saved and not original_pair:
            raise RuntimeError('清理阶段缓存出现变化，保留备份和记录。')
    if original and not preserved and not original_pair:
        record(owner, state, 'restoring_cache')
        for _, path, sha in caches:
            source, old_sha = saved[path]
            if file_hash(path) != old_sha:
                write_cache(source, path, old_sha, {None, sha, old_sha})
        if any(file_hash(p) != saved[p][1] for _, p, _ in caches):
            raise RuntimeError('官方缓存恢复未完成，请重试移除。')
    elif not original and not preserved:
        record(owner, state, 'removing_cache')
        for _, path, sha in reversed(caches):
            if file_hash(path) not in {None, sha}:
                raise RuntimeError('缓存出现未知变化，保留安装记录。')
            path.unlink(missing_ok=True)
    record(owner, state, 'removing_payload')
    for _, path, sha in reversed(owned):
        if file_hash(path) not in {None, sha}:
            raise RuntimeError('附加资源出现未知变化，保留备份和记录。')
        path.unlink(missing_ok=True)
    record(owner, state, 'cleanup')
    for path, sha in saved.values():
        if file_hash(path) not in {None, sha}:
            raise RuntimeError('备份出现未知变化，保留安装记录。')
        path.unlink(missing_ok=True)
    backup_dir = owner / 'cache-backup'
    if backup_dir.exists():
        try:
            backup_dir.rmdir()
        except OSError:
            pass
    (owner / 'installed.json').unlink()
    try:
        owner.rmdir()
    except OSError:
        pass  # Preserve unrelated files.
    if preserved:
        return '语言包已移除，官方内容缓存已保留。'
    if original:
        return '语言包已移除，安装前的官方用户缓存已恢复。'
    return '语言包已移除。'


@locked
def install(game, profile=None, allow_official_cache=False):
    require_closed()
    root, spec, payloads = plan(game, profile)
    owner = root / 'codex_zh_addon'
    caches = cache_pair(root, payloads)
    if owner.exists():
        state = read_state(owner, root, payloads)
        if state['files'] != expected_files(root, payloads):
            raise RuntimeError('检测到明确支持的旧版附加语言记录；请先移除旧版，再重新安装本版。')
        if state.get('phase') == 'installed' and all(file_hash(p) == sha for _, p, sha in payloads):
            backups(owner, root, payloads, state)
            return '附加语言已安装，无需重复安装。'
        if official_pair(game, caches):
            raise RuntimeError('检测到旧安装记录，但缓存已恢复为官方版本；请先移除附加语言，再重新安装。')
        raise RuntimeError('检测到未完成或已变化的附加语言；请先移除以恢复，再重新安装。')
    if any(p.exists() for _, p, _ in payloads if p.parent == owner):
        raise RuntimeError('附加语言资源已存在，未覆盖。')
    existing = any(p.exists() for _, p, _ in caches)
    if existing and (not allow_official_cache or not official_pair(game, caches)):
        raise RuntimeError('已有同名用户缓存；仅严格匹配游戏官方的同版本完整缓存对才可授权备份切换。未知或混配缓存不会覆盖。')
    original = {}
    if existing:
        for _, path, _ in caches:
            original[str(path.relative_to(root))] = {'backup': str(Path('cache-backup') / path.name), 'sha256': digest(path)}
    with tempfile.TemporaryDirectory(prefix='rob-zh-payload-') as temporary:
        payloads = prepare_payloads(game, spec, payloads, Path(temporary))
        caches = cache_pair(root, payloads)
        owner.mkdir()
        state = {'schema': 2, 'phase': 'backing_up', 'files': expected_files(root, payloads), 'original_cache': original}
        try:
            record(owner, state, 'backing_up')
            if original:
                (owner / 'cache-backup').mkdir()
                for _, path, _ in caches:
                    item = original[str(path.relative_to(root))]
                    publish_new(path, owner / item['backup'], item['sha256'], root)
                backups(owner, root, payloads, state)  # Both copies verified before any cache write.
                if any(file_hash(p) != original[str(p.relative_to(root))]['sha256'] for _, p, _ in caches):
                    raise RuntimeError('备份期间用户缓存出现变化，未切换缓存。')
            record(owner, state, 'installing_payload')
            for source, target, sha in payloads:
                if target.parent == owner:
                    publish_new(source, target, sha, root)
                    if digest(target) != sha:
                        raise RuntimeError('新增文件回读校验失败。')
            record(owner, state, 'switching_cache')
            require_closed()
            for source, target, sha in caches:
                target.parent.mkdir(parents=True, exist_ok=True)
                if original:
                    old_sha = original[str(target.relative_to(root))]['sha256']
                    write_cache(source, target, sha, {old_sha})
                else:
                    publish_new(source, target, sha, root)
                    if digest(target) != sha:
                        raise RuntimeError('缓存回读校验失败。')
            record(owner, state, 'installed')
            plan(game, profile)  # Independently verify original game resource hashes.
        except Exception as error:
            try:
                if (owner / 'installed.json').is_file():
                    remove_owned(game, root, payloads, read_state(owner, root, payloads))
                else:
                    owner.rmdir()
            except Exception as recovery_error:
                raise RuntimeError(f'安装未完成：{error}。自动恢复未完成：{recovery_error}。已保留记录和备份，请检查后重试移除。') from error
            raise
    return '语言包安装完成。'


@locked
def remove(game, profile=None):
    require_closed()
    root, _, payloads = plan(game, profile, verify_game=False)
    state = read_state(root / 'codex_zh_addon', root, payloads)
    recorded_payloads = [(source, target, state['files'][str(target.relative_to(root))])
                         for source, target, _ in payloads
                         if str(target.relative_to(root)) in state['files']]
    return remove_owned(game, root, recorded_payloads, state)


def status(game, profile=None):
    root, _, payloads = plan(game, profile)
    state_path = root / 'codex_zh_addon/installed.json'
    caches = cache_pair(root, payloads)
    if state_path.is_file():
        state = read_state(state_path.parent, root, payloads)
        if state['files'] != expected_files(root, payloads):
            return '旧版附加语言记录 · 请先移除旧版，再重新安装本版'
        if state.get('phase') == 'installed' and all(file_hash(p) == sha for _, p, sha in payloads):
            try:
                backups(state_path.parent, root, payloads, state)
            except RuntimeError:
                return '附加语言备份异常 · 暂不能自动移除，请保留现有记录'
            return '附加语言已安装'
        if official_pair(game, caches):
            try:
                original = state.get('original_cache', {})
                original_pair = bool(original) and all(file_hash(p) == original[str(p.relative_to(root))]['sha256'] for _, p, _ in caches)
                missing_ok = state.get('phase') == 'cleanup' or (state.get('phase') == 'backing_up' and original_pair)
                backups(state_path.parent, root, payloads, state, missing_ok)
                if any(file_hash(p) not in {None, sha} for _, p, sha in payloads if p.parent == state_path.parent):
                    raise RuntimeError('unknown bundle')
            except RuntimeError:
                return '附加语言存在未知变化或备份异常 · 暂不能自动移除'
            return '内容目录已恢复为官方版本 · 可先移除旧汉化并保留官方缓存'
        return '附加语言安装不完整或文件已变化 · 可尝试移除恢复，未知文件会保留'
    if (root / 'codex_zh_addon').exists():
        return '未安装附加语言 · 已有目录缺少有效记录，未修改'
    if official_pair(game, caches):
        return '未安装附加语言 · 官方缓存可备份切换'
    if any(p.exists() for _, p, _ in caches):
        return '未安装附加语言 · 已有缓存来源不明或版本混配，拒绝覆盖'
    return '未安装附加语言'


def open_window(parent):
    window = tk.Toplevel(parent)
    window.title('ROB RUN · 中文语言包')
    window.geometry('700x350')
    frame = ttk.Frame(window, padding=20)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='简体中文语言包', font=('Microsoft YaHei UI', 16, 'bold')).pack(anchor='w')
    label = tk.StringVar()
    ttk.Label(frame, textvariable=label, wraplength=650, foreground='#16689a').pack(anchor='w', pady=8)
    game = parent.path.get()
    def refresh():
        try:
            label.set(status(game))
        except Exception as error:
            label.set(str(error))
    def run(action):
        try:
            message = action(game)
            refresh()
            messagebox.showinfo('附加语言', message, parent=window)
        except Exception as error:
            messagebox.showerror('操作未完成', str(error), parent=window)
    buttons = ttk.Frame(frame)
    buttons.pack(anchor='w', pady=10)
    ttk.Button(buttons, text='安装新增中文语言', command=lambda: run(install)).pack(side='left', padx=(0, 10))
    ttk.Button(buttons, text='移除新增语言与缓存', command=lambda: run(remove)).pack(side='left', padx=(0, 10))
    ttk.Button(buttons, text='检查状态', command=refresh).pack(side='left')
    refresh()
