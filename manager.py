"""ROB RUN 简体中文资源管理器。Python 3.12 / UnityPy 1.25.4。"""
import argparse
from collections import Counter
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
import msvcrt
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import winreg

BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
HOME = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
APPID = '4262460'
AA = Path('ROB RUN_Data/StreamingAssets/aa/StandaloneWindows64')
TEXT = AA / 'localization-string-tables-english(unitedstates)(en-us)_assets_all.bundle'
FONT = AA / 'inbuild_assets_all.bundle'
META = '_ROB_RUN_ZH'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    atomic_write(Path(path), json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8'))


def digest(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.zh-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def locate_games():
    roots = set()
    for hive, key, value in [
        (winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
        (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath'),
    ]:
        try:
            with winreg.OpenKey(hive, key) as k:
                roots.add(Path(winreg.QueryValueEx(k, value)[0]))
        except OSError:
            pass
    for root in list(roots):
        config = root / 'steamapps/libraryfolders.vdf'
        if config.exists():
            for p in re.findall(r'"path"\s*"([^"]+)"', config.read_text(encoding='utf-8')):
                roots.add(Path(p.replace('\\\\', '\\')))
    result = []
    for root in sorted(roots):
        manifest = root / f'steamapps/appmanifest_{APPID}.acf'
        if manifest.exists():
            m = re.search(r'"installdir"\s*"([^"]+)"', manifest.read_text(encoding='utf-8'))
            if m:
                game = root / 'steamapps/common' / m[1]
                if (game / 'ROB RUN.exe').is_file():
                    result.append(game)
    return result


def game_build(game):
    manifest = game.parent.parent / f'appmanifest_{APPID}.acf'
    if not manifest.exists():
        return '未知'
    match = re.search(r'"buildid"\s*"(\d+)"', manifest.read_text(encoding='utf-8'))
    return match[1] if match else '未知'


def require_closed():
    result = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True,
                            creationflags=subprocess.CREATE_NO_WINDOW, check=True)
    if b'rob run.exe' in result.stdout.lower() or b'start_protected_game.exe' in result.stdout.lower():
        raise RuntimeError('请先退出 ROB RUN，再安装或还原汉化。')


@contextmanager
def game_lock(game):
    folder = game / META
    folder.mkdir(exist_ok=True)
    with (folder / 'operation.lock').open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError('另一个汉化工具正在操作此游戏，请等待其完成。')
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def locked_operation(operation):
    def run(self, path, log=print):
        game = self.game(path)
        with game_lock(game):
            return operation(self, game, log)
    return run


def format_signature(text):
    """Compare formatting syntax, allowing translated text in SmartFormat branches."""
    fields = Counter(re.findall(r'\{([^{}:|\s]*)(?=[:}])', text))
    formats = Counter(re.findall(r'\{[^{}:]*:([A-Za-z0-9_]+(?:\([^{}]*?\))?)(?=[:}])', text))
    tags = Counter(re.findall(r'</?[A-Za-z][^>]*>', text))
    return fields, formats, tags, text.count('{'), text.count('}'), text.count('|')


def validate_translation(source, target):
    if not isinstance(target, str) or (source.strip() and not target.strip()):
        raise ValueError('译文不能为空。')
    if format_signature(source) != format_signature(target):
        raise ValueError('译文中的变量、格式标签或分支结构与原文不一致。')


class Manager:
    def __init__(self):
        self.entries = read_json(BASE / 'data/strings_en.json')
        self.by_id = {e['id']: e for e in self.entries}
        self.translation = read_json(BASE / 'data/zh_cn.json')
        self.spec = read_json(BASE / 'data/patch_manifest.json')
        self.overrides_path = HOME / '用户词库.json'
        self.overrides = read_json(self.overrides_path) if self.overrides_path.exists() else {}
        self.check_dictionary(self.overrides)

    def check_dictionary(self, values):
        if not isinstance(values, dict):
            raise ValueError('词库应为 JSON 对象：文本 ID 对应中文译文。')
        for key, value in values.items():
            if key not in self.by_id:
                raise ValueError(f'词库包含未知文本 ID：{key}')
            validate_translation(self.by_id[key]['en'], value)
        # The supplied atlas must contain every translated character.
        allowed = set(self.spec['font_characters'])
        missing = {c for t in values.values() for c in t if ord(c) > 127 and c not in allowed}
        if missing:
            raise ValueError('当前字体未包含这些字符：' + ''.join(sorted(missing))[:60])

    def values(self):
        return self.translation | self.overrides

    def game(self, path):
        game = Path(path).resolve()
        if not (game / 'ROB RUN.exe').is_file() or not (game / TEXT).is_file():
            raise ValueError('所选目录不是完整的 ROB RUN 游戏目录。')
        return game

    def state(self, game):
        file = game / META / 'state.json'
        state = read_json(file) if file.exists() else None
        if state and set(state.get('files', {})) != {str(TEXT), str(FONT)}:
            raise RuntimeError('安装记录无效，请勿编辑 state.json。')
        return state

    def inspect(self, path):
        game = self.game(path)
        build = game_build(game)
        state = self.state(game)
        current = {str(p): digest(game / p) for p in [TEXT, FONT]}
        original = self.spec['original_sha256']
        if state:
            good = all(current.get(p) == v['patched'] for p, v in state['files'].items())
            status = '已安装汉化' if good and state['phase'] == 'installed' else '文件已变化 / 上次操作未完成'
        elif current == original:
            status = '资源汉化已停用（反作弊拒绝）' if self.spec.get('installation_blocked') else '可安装汉化'
        else:
            status = '版本或文件不兼容'
        return {'build': build, 'status': status, 'sha256': current,
                'compatible': current == original or bool(state and all(
                    current.get(p) == v['patched'] for p, v in state['files'].items()))}

    @locked_operation
    def install(self, path, log=print):
        if self.spec.get('installation_blocked'):
            raise RuntimeError(self.spec['installation_blocked'])
        require_closed()
        game = self.game(path)
        report = self.inspect(game)
        if not report['compatible']:
            raise RuntimeError('资源文件不匹配。请先还原汉化或在 Steam 验证文件；游戏更新后需重新适配。')
        old = self.state(game)
        if old and old['phase'] != 'installed':
            raise RuntimeError('检测到未完成的操作，请先点击“一键还原”。')
        values = self.values()
        self.check_dictionary(values)
        folder = game / META
        folder.mkdir(exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='stage-', dir=folder))
        try:
            originals = {}
            for rel in [TEXT, FONT]:
                backup = folder / 'original' / rel
                expected = self.spec['original_sha256'][str(rel)]
                if not backup.exists():
                    if digest(game / rel) != expected:
                        raise RuntimeError(f'无法建立原版备份：{rel.name}')
                    atomic_write(backup, (game / rel).read_bytes())
                if digest(backup) != expected:
                    raise RuntimeError(f'原版备份与当前适配版本不匹配：{rel.name}。请保留并归档旧 _ROB_RUN_ZH 文件夹，再使用本版工具。')
                originals[rel] = backup
            log('原版备份已校验。正在生成中文文本包……')
            import UnityPy
            env = UnityPy.load(originals[TEXT].read_bytes())
            count = 0
            for obj in env.objects:
                if obj.type.name != 'MonoBehaviour':
                    continue
                tree = obj.read_typetree()
                if 'm_TableData' not in tree:
                    continue
                for entry in tree['m_TableData']:
                    key = str(entry['m_Id'])
                    if key in values:
                        validate_translation(entry['m_Localized'], values[key])
                        entry['m_Localized'] = values[key]
                        count += 1
                obj.save_typetree(tree)
            staged_text = stage / TEXT.name
            staged_text.write_bytes(env.file.save(packer='lz4'))
            log(f'正在验证 {count:,} 条译文回写结果……')
            verify = UnityPy.load(staged_text.read_bytes())
            loaded = {}
            for obj in verify.objects:
                if obj.type.name == 'MonoBehaviour':
                    tree = obj.read_typetree()
                    loaded.update({str(e['m_Id']): e['m_Localized'] for e in tree.get('m_TableData', [])})
            if any(loaded.get(k) != v for k, v in values.items()):
                raise RuntimeError('资源包回读验证失败，未安装。')
            staged_font = stage / FONT.name
            payload = BASE / 'data/font_zh.bundle'
            if digest(payload) != self.spec['font_payload_sha256']:
                raise RuntimeError('中文字体包校验失败，请重新解压工具。')
            shutil.copyfile(payload, staged_font)
            files = {str(rel): {'original': digest(originals[rel]), 'patched': digest(stage / rel.name)}
                     for rel in [TEXT, FONT]}
            for rel in [TEXT, FONT]:
                shutil.copyfile(game / rel, stage / (rel.name + '.previous'))
                files[str(rel)]['previous'] = digest(game / rel)
            state = {'version': 1, 'build': report['build'], 'phase': 'installing',
                     'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'files': files, 'entries': count}
            write_json(folder / 'state.json', state)
            log('正在安装中文文本与字体……')
            try:
                for rel in [TEXT, FONT]:
                    atomic_write(game / rel, (stage / rel.name).read_bytes())
                state['phase'] = 'installed'
                write_json(folder / 'state.json', state)
            except Exception:
                # Restore the exact state preceding this attempt when re-installing.
                for rel in [TEXT, FONT]:
                    before = stage / (rel.name + '.previous')
                    if before.exists():
                        atomic_write(game / rel, before.read_bytes())
                    else:
                        atomic_write(game / rel, originals[rel].read_bytes())
                if old:
                    write_json(folder / 'state.json', old)
                else:
                    (folder / 'state.json').unlink(missing_ok=True)
                raise
            log(f'汉化已安装：{count:,} 条。游戏语言请选 English（英语）。')
        finally:
            shutil.rmtree(stage)

    @locked_operation
    def restore(self, path, log=print):
        require_closed()
        game = self.game(path)
        folder = game / META
        state = self.state(game)
        if not state:
            raise RuntimeError('没有检测到本工具的安装记录。')
        # Validate all files before touching any; never overwrite Steam updates.
        for name, hashes in state['files'].items():
            backup = folder / 'original' / name
            if not backup.is_file() or digest(backup) != hashes['original']:
                raise RuntimeError(f'原版备份丢失或损坏：{Path(name).name}')
            if digest(game / name) not in {hashes['original'], hashes['patched'], hashes.get('previous')}:
                raise RuntimeError('游戏文件已被更新或改动，已停止还原，避免覆盖新版本。请用 Steam 验证文件。')
        state['phase'] = 'restoring'
        write_json(folder / 'state.json', state)
        for name in state['files']:
            atomic_write(game / name, (folder / 'original' / name).read_bytes())
        (folder / 'state.json').unlink()
        log('已还原原版，并保留原版备份。')


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('ROB RUN · 简体中文汉化管理器')
        if (BASE / 'data/icon.ico').exists():
            self.iconbitmap(str(BASE / 'data/icon.ico'))
        self.geometry('1040x760')
        self.minsize(860, 650)
        self.option_add('*Font', ('Microsoft YaHei UI', 10))
        self.manager = Manager()
        self.events = queue.Queue()
        self.busy = False
        self.current = None
        self.protocol('WM_DELETE_WINDOW', self.close)
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='ROB RUN  简体中文', font=('Microsoft YaHei UI', 21, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='汉化安装与还原 · 词条检索与修订', foreground='#526173').pack(anchor='w', pady=(3, 16))
        row = ttk.Frame(frame)
        row.pack(fill='x')
        self.path = tk.StringVar()
        ttk.Entry(row, textvariable=self.path).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='选择游戏目录', command=self.browse).pack(side='left', padx=(8, 0))
        ttk.Button(row, text='自动定位', command=self.locate).pack(side='left', padx=(8, 0))
        self.status = tk.StringVar(value='正在读取游戏状态……')
        ttk.Label(frame, textvariable=self.status, foreground='#16689a').pack(anchor='w', pady=12)
        row = ttk.Frame(frame)
        row.pack(fill='x')
        self.actions = []
        for label, fn in [('检查状态', self.refresh), ('安装 / 更新汉化', lambda: self.run(self.manager.install)),
                          ('一键还原', lambda: self.run(self.manager.restore))]:
            btn = ttk.Button(row, text=label, command=fn)
            btn.pack(side='left', padx=(0, 8))
            self.actions.append(btn)
        if self.manager.spec.get('installation_blocked'):
            self.actions[1].configure(state='disabled')
        addon_button = ttk.Button(row, text='新增中文（实验）', command=self.open_addon)
        addon_button.pack(side='left', padx=(0, 8))
        self.actions.append(addon_button)
        ttk.Label(frame, text='安装和还原前请退出游戏。汉化使用 English 语言槽位。', foreground='#526173').pack(anchor='w', pady=(10, 12))
        tabs = ttk.Notebook(frame)
        tabs.pack(fill='both', expand=True)
        editor = ttk.Frame(tabs, padding=10)
        logs = ttk.Frame(tabs, padding=10)
        tabs.add(editor, text='翻译词库')
        tabs.add(logs, text='操作记录')
        row = ttk.Frame(editor)
        row.pack(fill='x')
        self.query = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.query)
        entry.pack(side='left', fill='x', expand=True)
        entry.bind('<Return>', lambda _: self.search())
        ttk.Button(row, text='搜索', command=self.search).pack(side='left', padx=6)
        ttk.Button(row, text='导出词库', command=self.export).pack(side='left', padx=3)
        ttk.Button(row, text='导入词库', command=self.import_dict).pack(side='left', padx=3)
        ttk.Label(editor, text='可搜索中文、英文或文本键名。修改保存后，再安装汉化即可生效。', foreground='#526173').pack(anchor='w', pady=7)
        table_frame = ttk.Frame(editor)
        table_frame.pack(fill='both', expand=True)
        self.table = ttk.Treeview(table_frame, columns=('en', 'zh'), show='headings', height=8, selectmode='browse')
        self.table.heading('en', text='英文原文')
        self.table.heading('zh', text='中文译文')
        self.table.column('en', width=430)
        self.table.column('zh', width=430)
        scroll = ttk.Scrollbar(table_frame, orient='vertical', command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.table.bind('<<TreeviewSelect>>', self.select)
        self.key = tk.StringVar(value='选择词条后可修订译文')
        ttk.Label(editor, textvariable=self.key, foreground='#526173').pack(anchor='w', pady=(8, 4))
        self.source = tk.Text(editor, height=3, wrap='word', background='#f0f2f5', relief='flat')
        self.source.pack(fill='x')
        self.source.configure(state='disabled')
        self.target = tk.Text(editor, height=3, wrap='word', relief='solid', borderwidth=1, undo=True)
        self.target.pack(fill='x', pady=(6, 6))
        self.save_button = ttk.Button(editor, text='保存当前译文', command=self.save_entry)
        self.save_button.pack(anchor='e')
        self.logbox = tk.Text(logs, wrap='word', relief='flat', state='disabled')
        self.logbox.pack(fill='both', expand=True)
        ttk.Label(frame, text='旧版覆盖式安装已停用。独立语言扩展见“新增中文（实验）”；游戏与 EAC 兼容尚待验证。', foreground='#a33b26').pack(anchor='w', pady=(12, 0))
        self.search()
        self.locate()
        self.after(100, self.poll)

    def close(self):
        if self.busy:
            messagebox.showinfo('操作进行中', '请等待当前安装或还原完成后再关闭。')
        else:
            self.destroy()

    def open_addon(self):
        import addon
        addon.open_window(self)

    def log(self, text):
        self.logbox.configure(state='normal')
        self.logbox.insert('end', time.strftime('%H:%M:%S  ') + text + '\n')
        self.logbox.see('end')
        self.logbox.configure(state='disabled')

    def locate(self):
        if self.busy:
            return
        games = locate_games()
        if games:
            self.path.set(str(games[0]))
            self.refresh()
        else:
            self.status.set('未自动找到游戏，请选择包含 ROB RUN.exe 的目录。')

    def browse(self):
        if self.busy:
            return
        path = filedialog.askdirectory(title='选择 ROB RUN 游戏目录')
        if path:
            self.path.set(path)
            self.refresh()

    def refresh(self):
        try:
            report = self.manager.inspect(self.path.get())
            self.status.set(f"Build {report['build']}  ·  {report['status']}  ·  词库 {len(self.manager.values()):,} 条")
        except Exception as e:
            self.status.set(str(e))

    def run(self, operation):
        if self.busy:
            return
        self.busy = True
        for btn in self.actions + [self.save_button]:
            btn.configure(state='disabled')
        game = self.path.get()
        self.status.set('正在处理，请稍候……')
        def work():
            try:
                operation(game, lambda t: self.events.put(('log', t)))
                self.events.put(('done', ''))
            except Exception as e:
                self.events.put(('error', str(e)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        while not self.events.empty():
            kind, value = self.events.get()
            if kind == 'log':
                self.log(value)
            else:
                self.busy = False
                for btn in self.actions + [self.save_button]:
                    btn.configure(state='normal')
                if self.manager.spec.get('installation_blocked'):
                    self.actions[1].configure(state='disabled')
                self.refresh()
                if kind == 'error':
                    self.log('失败：' + value)
                    messagebox.showerror('操作未完成', value)
                else:
                    messagebox.showinfo('操作完成', '已完成。详细结果见“操作记录”。')
        self.after(100, self.poll)

    def search(self):
        self.table.delete(*self.table.get_children())
        q = self.query.get().strip().casefold()
        values = self.manager.values()
        for e in self.manager.entries:
            zh = values.get(e['id'], e['en'])
            if not q or q in (e['en'] + '\n' + zh + '\n' + e['key']).casefold():
                self.table.insert('', 'end', iid=e['id'], values=(e['en'].replace('\n', ' ')[:180], zh.replace('\n', ' ')[:180]))

    def select(self, _=None):
        selected = self.table.selection()
        if not selected:
            return
        self.current = selected[0]
        e = self.manager.by_id[self.current]
        self.key.set(e['key'] + '  ·  ' + self.current)
        self.source.configure(state='normal')
        self.source.delete('1.0', 'end')
        self.source.insert('1.0', e['en'])
        self.source.configure(state='disabled')
        self.target.delete('1.0', 'end')
        self.target.insert('1.0', self.manager.values().get(self.current, e['en']))

    def save_entry(self):
        if not self.current:
            return
        try:
            new = self.manager.overrides | {self.current: self.target.get('1.0', 'end-1c')}
            self.manager.check_dictionary(new)
            write_json(self.manager.overrides_path, new)
            self.manager.overrides = new
            self.table.item(self.current, values=(self.manager.by_id[self.current]['en'].replace('\n', ' ')[:180], new[self.current].replace('\n', ' ')[:180]))
            self.log('已保存译文：' + self.manager.by_id[self.current]['key'])
        except Exception as e:
            messagebox.showerror('无法保存', str(e))

    def export(self):
        path = filedialog.asksaveasfilename(defaultextension='.json', initialfile='ROB_RUN_中文词库.json')
        if path:
            write_json(path, self.manager.values())

    def import_dict(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(filetypes=[('JSON 词库', '*.json')])
        if not path:
            return
        try:
            values = self.manager.overrides | read_json(path)
            self.manager.check_dictionary(values)
            write_json(self.manager.overrides_path, values)
            self.manager.overrides = values
            self.search()
            self.log('已导入词库，重新安装汉化后生效。')
        except Exception as e:
            messagebox.showerror('导入失败', str(e))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', metavar='GAME_DIR')
    parser.add_argument('--install', metavar='GAME_DIR')
    parser.add_argument('--restore', metavar='GAME_DIR')
    parser.add_argument('--install-addon', metavar='GAME_DIR')
    parser.add_argument('--remove-addon', metavar='GAME_DIR')
    parser.add_argument('--addon-status', metavar='GAME_DIR')
    args = parser.parse_args()
    if args.install_addon or args.remove_addon or args.addon_status:
        import addon
        if args.install_addon:
            print(addon.install(args.install_addon))
        elif args.remove_addon:
            print(addon.remove(args.remove_addon))
        else:
            print(addon.status(args.addon_status))
    elif args.check or args.install or args.restore:
        manager = Manager()
        if args.check:
            print(json.dumps(manager.inspect(args.check), ensure_ascii=False, indent=2))
        elif args.install:
            manager.install(args.install)
        else:
            manager.restore(args.restore)
    else:
        try:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except (OSError, AttributeError):
                pass
            App().mainloop()
        except Exception as e:
            messagebox.showerror('启动失败', str(e))
            raise
