"""Single-column UI for the Chinese language pack manager."""
import ctypes
from datetime import datetime
from fractions import Fraction
import json
from pathlib import Path
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import filedialog, ttk

import addon
import manager as backend


BLUE = '#0755df'
INK = '#172033'
MUTED = '#626c7b'
PANEL = '#f1f6ff'
VERSION = '0.2.6'
SENSITIVE_KEY = r'(?:access[_ -]?token|refresh[_ -]?token|authorization|password|passwd|api[_ -]?key|client[_ -]?secret|secret|token|account(?:[_ -]?id)?|steam[_ -]?id|账号|账户ID)'


def redact(value):
    text = str(value)
    text = re.sub(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+', 'Bearer [已隐藏]', text)
    text = re.sub(
        rf'''(?ix)({SENSITIVE_KEY}["']?\s*[=:：]\s*)("[^"]*"|'[^']*'|[^\s,;}}\]]+)''',
        lambda m: m[1] + '[已隐藏]', text)
    text = re.sub(r'\b7656\d{13}\b', '[Steam账号已隐藏]', text)
    text = re.sub(r'(?i)([A-Z]:[\\/]Users[\\/])[^\\/\r\n"\']+', r'\1[用户]', text)
    return text


def redact_data(value):
    if isinstance(value, dict):
        return {key: '[已隐藏]' if re.fullmatch(SENSITIVE_KEY, str(key), re.I) else redact_data(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    return redact(value) if isinstance(value, str) else value


def existing_log_summary():
    """Export only counts from bounded existing logs, never raw account data."""
    summaries = {}
    for name in ('Player.log', 'Player-prev.log'):
        path = addon.user_profile() / name
        if not path.is_file():
            summaries[name] = {'exists': False}
            continue
        with path.open('rb') as handle:
            handle.seek(max(0, path.stat().st_size - 131072))
            tail = handle.read(131072).decode('utf-8', errors='replace')
        folded = tail.casefold()
        markers = re.findall(r'\b(?:E-\d{4}|SocketException|HttpRequestException|TimeoutException|WebException|NetworkUnreachable|ConnectionRefused|AuthenticationFailed|HeartbeatTimeout|NullClient)\b', tail, re.I)
        summaries[name] = {
            'exists': True, 'bytes': path.stat().st_size,
            'modified_at': datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(),
            'sample': 'last_128_KiB',
            'reported_failure_correlation': 'unverified',
            'error_markers': sorted(set(markers))[:20],
            'keyword_counts': {word: folded.count(word) for word in
                               ('error', 'exception', 'anti-cheat', 'eac', 'catalog', 'localization')},
        }
    return summaries


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f'ROB RUN 中文适配工具 · v{VERSION}')
        icon = backend.BASE / 'data/icon.ico'
        if icon.is_file():
            try:
                self.iconbitmap(str(icon))
            except tk.TclError:
                pass
        self.configure(background='white')
        self.scale = max(1.0, self.winfo_fpixels('1i') / 96)
        available_w = max(600, self.winfo_screenwidth() - self.p(64))
        available_h = max(480, self.winfo_screenheight() - self.p(80))
        self.geometry(f'{min(self.p(1100), available_w)}x{min(self.p(780), available_h)}')
        self.minsize(min(self.p(760), available_w), min(self.p(570), available_h))
        self.option_add('*Font', ('Microsoft YaHei UI', 10))
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.path = tk.StringVar()
        self.busy = False
        self.events = queue.Queue()
        self.logs = []
        self.last_error = ''
        self.snapshot = {'build': '尚未检查', 'package_status': '尚未检查'}
        self.icons = {}
        self.log_expanded = True
        self._styles()
        self._layout()
        self.path.trace_add('write', self._path_changed)
        self.after(80, self._poll)
        self.after(140, self.locate)

    def p(self, pixels):
        return round(pixels * self.scale)

    def _icon(self, filename):
        if filename not in self.icons:
            path = backend.BASE / 'data/ui_icons' / filename
            if not path.is_file():
                return ''
            icon = tk.PhotoImage(file=str(path), master=self)
            ratio = Fraction(self.scale).limit_denominator(4)
            if ratio.numerator != ratio.denominator:
                icon = icon.zoom(ratio.numerator).subsample(ratio.denominator)
            self.icons[filename] = icon
        return self.icons[filename]

    def _styles(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('TButton', font=('Microsoft YaHei UI', 11), padding=(self.p(18), self.p(11)),
                        background='#fafbfd', foreground=INK, bordercolor='#c5cddb',
                        lightcolor='#fafbfd', darkcolor='#fafbfd', focuscolor=BLUE)
        style.map('TButton', background=[('active', '#edf2fa'), ('disabled', '#f2f3f5')],
                  foreground=[('disabled', '#a0a7b2')])
        style.configure('Primary.TButton', font=('Microsoft YaHei UI', 13, 'bold'),
                        foreground='white', background=BLUE, bordercolor=BLUE,
                        lightcolor=BLUE, darkcolor=BLUE, padding=(self.p(24), self.p(13)))
        style.map('Primary.TButton', background=[('disabled', '#b6c9ed'), ('active', '#0646bf')],
                  foreground=[('disabled', '#ffffff')], bordercolor=[('disabled', '#b6c9ed')])
        style.configure('Link.TButton', foreground=BLUE, background='white', borderwidth=0,
                        padding=(self.p(2), self.p(6)))
        style.map('Link.TButton', background=[('active', '#f2f6ff')],
                  foreground=[('disabled', '#a0a7b2')])
        style.configure('Path.TEntry', padding=(self.p(12), self.p(13)),
                        fieldbackground='#fbfcfe', foreground=INK, bordercolor='#c5cddb')
        style.map('Path.TEntry', bordercolor=[('focus', BLUE)])

    def _label(self, parent, text='', *, bg='white', color=INK, size=10, bold=False, **kwargs):
        return tk.Label(parent, text=text, background=bg, foreground=color, anchor='w',
                        font=('Microsoft YaHei UI', size, 'bold' if bold else 'normal'), **kwargs)

    def _layout(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        header = tk.Frame(self, background='#f8faff', padx=self.p(32), pady=self.p(14))
        header.grid(row=0, column=0, columnspan=2, sticky='ew')
        header.grid_columnconfigure(3, weight=1)
        tk.Label(header, text='ROB RUN', font=('Arial', 23, 'bold italic'),
                 foreground=BLUE, background='#f8faff').grid(row=0, column=0, sticky='w')
        ttk.Separator(header, orient='vertical').grid(row=0, column=1, sticky='ns', padx=self.p(22))
        self._label(header, '中文适配工具', bg='#f8faff', size=18, bold=True).grid(row=0, column=2)
        self._label(header, f'v{VERSION}', bg='#f8faff', color=MUTED, size=11).grid(row=0, column=4, sticky='e')
        self.canvas = tk.Canvas(self, background='white', highlightthickness=0, borderwidth=0)
        self.canvas.grid(row=1, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        scroll.grid(row=1, column=1, sticky='ns')
        self.canvas.configure(yscrollcommand=scroll.set)
        self.body = tk.Frame(self.canvas, background='white', padx=self.p(36), pady=self.p(18))
        self.body.grid_columnconfigure(0, weight=1)
        self.body_window = self.canvas.create_window((0, 0), window=self.body, anchor='nw')
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self.body_window, width=e.width))
        self.body.bind('<Configure>', lambda _: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.bind('<MouseWheel>', self._wheel, add='+')

        self._label(self.body, '游戏目录', size=20, bold=True).grid(row=0, column=0, sticky='w')
        paths = tk.Frame(self.body, background='white')
        paths.grid(row=2, column=0, sticky='ew', pady=(self.p(12), 0))
        paths.grid_columnconfigure(0, weight=1)
        self.path_entry = ttk.Entry(paths, textvariable=self.path, style='Path.TEntry', font=('Microsoft YaHei UI', 12))
        self.path_entry.grid(row=0, column=0, sticky='ew')
        self.path_entry.bind('<Return>', lambda _: self.refresh())
        self.locate_button = ttk.Button(paths, text='自动定位', command=self.locate)
        self.locate_button.grid(row=0, column=1, padx=(self.p(14), self.p(10)))
        self.browse_button = ttk.Button(paths, text='选择目录', image=self._icon('folder_blue_24.png'), compound='left', command=self.browse)
        self.browse_button.grid(row=0, column=2)

        card = tk.Frame(self.body, background=PANEL, highlightbackground='#d7e1f0', highlightthickness=1,
                        padx=self.p(26), pady=self.p(18))
        card.grid(row=3, column=0, sticky='ew', pady=(self.p(20), self.p(18)))
        card.grid_columnconfigure(0, weight=1)
        title = tk.Frame(card, background=PANEL)
        title.grid(row=0, column=0, sticky='ew')
        self._label(title, '简体中文', bg=PANEL, size=21, bold=True).pack(side='left')
        self.badge = self._label(title, '未检查', bg='#e1e7f0', color='#4e5868', size=10,
                                  padx=self.p(12), pady=self.p(4))
        self.badge.pack(side='left', padx=self.p(18))
        self.status_label = self._label(card, '正在定位游戏目录…', bg=PANEL, color=MUTED,
                                       wraplength=self.p(880), justify='left')
        self.status_label.grid(row=2, column=0, sticky='ew', pady=(self.p(10), 0))
        self.inline_error = self._label(card, bg=PANEL, color='#b42318',
                                        wraplength=self.p(880), justify='left')
        self.inline_error.grid(row=4, column=0, sticky='ew', pady=(self.p(10), 0))
        self.inline_error.grid_remove()
        actions = tk.Frame(card, background=PANEL)
        actions.grid(row=5, column=0, sticky='ew', pady=(self.p(14), 0))
        actions.grid_columnconfigure(0, weight=3)
        actions.grid_columnconfigure(1, weight=2)
        actions.grid_columnconfigure(2, weight=2)
        self.install_button = ttk.Button(actions, text='安装中文语言包', style='Primary.TButton',
                                         image=self._icon('download_white_24.png'), compound='left',
                                         command=lambda: self._operation('install'))
        self.install_button.grid(row=0, column=0, sticky='ew', padx=(0, self.p(18)))
        self.remove_button = ttk.Button(actions, text='移除语言包', image=self._icon('trash-2_gray_24.png'),
                                        compound='left', command=lambda: self._operation('remove'))
        self.remove_button.grid(row=0, column=1, sticky='ew')

        ttk.Separator(self.body).grid(row=4, column=0, sticky='ew')
        log_header = tk.Frame(self.body, background='white')
        log_header.grid(row=5, column=0, sticky='ew', pady=(self.p(12), self.p(8)))
        log_header.grid_columnconfigure(1, weight=1)
        self.log_toggle = ttk.Button(log_header, text='操作记录  ', image=self._icon('chevron-up_gray_20.png'),
                                     compound='right', style='Link.TButton', command=self.toggle_logs)
        self.log_toggle.grid(row=0, column=0, sticky='w')
        self.copy_button = ttk.Button(log_header, text='复制日志', image=self._icon('copy_blue_20.png'),
                                      compound='left', style='Link.TButton', command=self.copy_logs)
        self.copy_button.grid(row=0, column=2, sticky='e')
        self.log_frame = tk.Frame(self.body, background='#f3f6fa', padx=self.p(14), pady=self.p(8))
        self.log_frame.grid(row=6, column=0, sticky='ew')
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_text = tk.Text(self.log_frame, height=5, wrap='word', state='disabled', relief='flat',
                                background='#f3f6fa', foreground='#354258', borderwidth=0,
                                font=('Microsoft YaHei UI', 10), padx=self.p(4), pady=self.p(2))
        self.log_text.grid(row=0, column=0, sticky='nsew')
        log_scroll = ttk.Scrollbar(self.log_frame, command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky='ns')
        self.log_text.configure(yscrollcommand=log_scroll.set)
        footer = tk.Frame(self, background='white', padx=self.p(36), pady=self.p(12))
        footer.grid(row=2, column=0, columnspan=2, sticky='ew')
        footer.grid_columnconfigure(1, weight=1)
        self.diagnostic_button = ttk.Button(footer, text='导出诊断', image=self._icon('file-text_blue_20.png'),
                                            compound='left', style='Link.TButton', command=self.export_diagnostics)
        self.diagnostic_button.grid(row=0, column=0, sticky='w')
        self.disclaimer_button = ttk.Button(footer, text='免责声明', style='Link.TButton',
                                             command=self.show_disclaimer)
        self.disclaimer_button.grid(row=0, column=2, sticky='e', padx=(self.p(16), 0))
        self.feedback = self._label(footer, color=MUTED, wraplength=self.p(680), justify='right')
        self.feedback.grid(row=0, column=1, sticky='e', padx=(self.p(14), 0))
        footer.bind('<Configure>', lambda e: self.feedback.configure(
            wraplength=max(self.p(180), e.width - self.diagnostic_button.winfo_reqwidth()
                           - self.disclaimer_button.winfo_reqwidth() - self.p(125))))
        self.controls = [self.path_entry, self.locate_button, self.browse_button,
                         self.install_button, self.remove_button, self.diagnostic_button]
        self._set_busy(False)
        self.body.bind('<Configure>', self._body_resized, add='+')

    def _body_resized(self, event):
        width = max(self.p(280), event.width - self.p(125))
        self.status_label.configure(wraplength=width)
        self.inline_error.configure(wraplength=width)

    def _wheel(self, event):
        if event.widget is not self.log_text:
            self.canvas.yview_scroll(round(-event.delta / 120), 'units')

    def _set_busy(self, value):
        self.busy = value
        for control in self.controls:
            control.configure(state='disabled' if value else 'normal')
        if not value and not self.path.get().strip():
            self.install_button.configure(state='disabled')
            self.remove_button.configure(state='disabled')

    def log(self, text):
        line = datetime.now().strftime('%H:%M:%S') + '  ' + redact(text)
        self.logs.append(line)
        self.logs = self.logs[-1000:]
        self.log_text.configure(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.insert('1.0', '\n'.join(self.logs))
        self.log_text.see('end')
        self.log_text.configure(state='disabled')

    def _start(self, name, work):
        if self.busy:
            return
        self._set_busy(True)
        self.inline_error.grid_remove()
        self.feedback.configure(text=name + '，请稍候…', foreground=MUTED)
        self.log(name + '…')
        def worker():
            try:
                self.events.put(('done', work()))
            except Exception as error:
                self.events.put(('error', redact(error)))
        threading.Thread(target=worker, daemon=True).start()

    def _inspect(self, path):
        return {'path': path, 'build': backend.game_build(Path(path)), 'package_status': addon.status(path)}

    def _apply_status(self, report):
        self.snapshot = report
        message = report['package_status']
        official_ready = message.startswith('未安装') and '官方' in message and '可备份切换' in message
        conflict = any(marker in message for marker in ('来源不明', '版本混配', '缺少有效记录'))
        if message.startswith('附加语言已安装'):
            badge, color, bg = '已安装', '#1d5987', '#dceafa'
            detail = '中文语言包已安装。'
        elif message.startswith('未安装') and not conflict:
            badge, color, bg = '未安装', '#4e5868', '#e1e7f0'
            detail = '尚未安装中文语言包。'
        else:
            badge, color, bg = '需要处理', '#925b00', '#fff0d3'
            detail = message
        self.badge.configure(text=badge, foreground=color, background=bg)
        self.install_button.configure(text='备份缓存并安装' if official_ready else '安装中文语言包')
        self.status_label.configure(text=f"Build {report['build']} · {redact(detail)}", foreground=MUTED)

    def _poll(self):
        while not self.events.empty():
            kind, data = self.events.get_nowait()
            if kind == 'error':
                self._set_busy(False)
                self.last_error = data
                self.log('操作未完成：' + data)
                self.feedback.configure(text='操作未完成，详见操作记录。', foreground='#b42318')
                self.status_label.configure(text=data, foreground='#b42318')
                self.badge.configure(text='需要处理', foreground='#925b00', background='#fff0d3')
            else:
                if data.get('path'):
                    self.path.set(data['path'])
                self._set_busy(False)
                if data.get('report'):
                    self._apply_status(data['report'])
                if data.get('status_error'):
                    self.last_error = data['status_error']
                    self.status_label.configure(text='状态刷新失败：' + data['status_error'], foreground='#b42318')
                    self.log('状态刷新失败：' + data['status_error'])
                if data.get('operation_error'):
                    self.last_error = data['operation_error']
                    self.inline_error.configure(text='操作未完成：' + data['operation_error'])
                    self.inline_error.grid()
                self.log(data['message'])
                self.feedback.configure(text=data.get('feedback', '检查完成。'),
                                        foreground='#b42318' if data.get('operation_error') or data.get('status_error') else MUTED)
        self.after(80, self._poll)

    def locate(self):
        def work():
            games = backend.locate_games()
            if not games:
                raise RuntimeError('未自动找到游戏，请选择包含 ROB RUN.exe 的安装目录。')
            path = str(games[0])
            try:
                return {'path': path, 'report': self._inspect(path),
                        'message': '已定位游戏目录；语言包状态检查完成。'}
            except Exception as error:
                return {'path': path, 'status_error': redact(error),
                        'message': '已定位游戏目录，语言包状态需要处理。'}
        self._start('自动定位游戏目录', work)

    def browse(self):
        if self.busy:
            return
        path = filedialog.askdirectory(parent=self, title='选择 ROB RUN 游戏安装目录')
        if path:
            self.path.set(path)
            self.refresh()

    def _path_changed(self, *_):
        if not self.busy:
            self._set_busy(False)
            if self.path.get().strip() != self.snapshot.get('path'):
                self.badge.configure(text='未检查', foreground='#4e5868', background='#e1e7f0')
                self.status_label.configure(text='目录已更改；按 Enter 可检查语言包状态。', foreground=MUTED)

    def refresh(self):
        path = self.path.get().strip()
        if not path or self.busy:
            return
        def work():
            report = self._inspect(path)
            report['path'] = path
            return {'report': report, 'message': '语言包状态检查完成。'}
        self._start('检查语言包状态', work)

    def _operation(self, operation):
        path = self.path.get().strip()
        if self.busy or not path:
            return
        def work():
            try:
                result = addon.install(path, allow_official_cache=True) if operation == 'install' else addon.remove(path)
                data = {'message': redact(result), 'feedback': '安装完成。' if operation == 'install' else '移除完成。'}
            except Exception as error:
                data = {'operation_error': redact(error), 'message': '操作未完成：' + redact(error),
                        'feedback': '操作未完成，详见上方提示与操作记录。'}
            try:
                data['report'] = self._inspect(path)
                data['report']['path'] = path
            except Exception as error:
                data['status_error'] = redact(error)
            return data
        self._start('安装语言包' if operation == 'install' else '移除语言包', work)

    def toggle_logs(self):
        self.log_expanded = not self.log_expanded
        if self.log_expanded:
            self.log_frame.grid()
        else:
            self.log_frame.grid_remove()
        self.log_toggle.configure(image=self._icon('chevron-up_gray_20.png' if self.log_expanded else 'chevron-down_gray_20.png'))

    def copy_logs(self):
        self.clipboard_clear()
        self.clipboard_append(redact('\n'.join(self.logs)))
        self.feedback.configure(text='日志已复制，敏感字段已隐藏。', foreground=MUTED)

    def show_disclaimer(self):
        window = tk.Toplevel(self)
        window.title('免责声明与第三方许可')
        window.geometry(f'{min(self.p(820), self.winfo_screenwidth() - 60)}x'
                        f'{min(self.p(620), self.winfo_screenheight() - 80)}')
        window.bind('<Escape>', lambda _: window.destroy())
        tabs = ttk.Notebook(window)
        tabs.pack(fill='both', expand=True, padx=self.p(12), pady=self.p(12))
        base = backend.BASE
        licenses = sorted(base.glob('*LICENSE.txt')) + sorted(
            path for path in (base / 'third_party_licenses').rglob('*') if path.is_file())
        for title, paths in (
                ('免责声明', [base / 'DISCLAIMER.md']),
                ('第三方许可', [base / 'THIRD_PARTY_NOTICES.md', *licenses])):
            page = ttk.Frame(tabs)
            tabs.add(page, text=title)
            text = tk.Text(page, wrap='word', relief='flat', padx=self.p(16), pady=self.p(12))
            scroll = ttk.Scrollbar(page, command=text.yview)
            scroll.pack(side='right', fill='y')
            text.pack(fill='both', expand=True)
            text.configure(yscrollcommand=scroll.set)
            for path in paths:
                text.insert('end', path.name + '\n\n')
                try:
                    text.insert('end', path.read_text(encoding='utf-8') + '\n\n')
                except OSError:
                    text.insert('end', '文件缺失或不可读取，请从完整发布包重新获取。\n\n')
            text.configure(state='disabled')

    def export_diagnostics(self):
        if self.busy:
            return
        path = filedialog.asksaveasfilename(parent=self, title='导出本地诊断摘要',
                                           initialfile='ROB_RUN_诊断.json', defaultextension='.json',
                                           filetypes=[('JSON 诊断摘要', '*.json')])
        if not path:
            return
        try:
            manifest = backend.read_json(backend.BASE / 'data/addon/manifest.json')
            report = {'schema': 1, 'created_at': datetime.now().astimezone().isoformat(),
                      'tool': 'ROB RUN 中文适配工具', 'tool_version': VERSION, 'python': sys.version.split()[0],
                      'game_directory': self.path.get(), 'status': self.snapshot,
                      'package_build': manifest.get('build'),
                      'last_error': self.last_error, 'tool_logs': self.logs,
                      'existing_game_logs': existing_log_summary()}
            backend.atomic_write(Path(path), json.dumps(redact_data(report), ensure_ascii=False, indent=2).encode('utf-8'))
            self.log('已将脱敏诊断摘要保存到所选本地文件。')
            self.feedback.configure(text='诊断已导出到本地，未上传。', foreground=MUTED)
        except Exception as error:
            self.last_error = redact(error)
            self.log('导出失败：' + self.last_error)
            self.feedback.configure(text='导出失败，详见操作记录。', foreground='#b42318')

    def close(self):
        if self.busy:
            self.feedback.configure(text='正在处理文件，请等待完成后再关闭。', foreground='#925b00')
            return
        self.destroy()


def run():
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass
    App().mainloop()


if __name__ == '__main__':
    run()
