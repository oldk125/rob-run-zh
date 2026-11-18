using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[assembly: AssemblyTitle("ROB RUN 中文适配工具")]
[assembly: AssemblyDescription("ROB RUN 简体中文适配管理器")]
[assembly: AssemblyProduct("ROB RUN 中文适配工具")]
[assembly: AssemblyVersion("0.3.0.0")]
[assembly: AssemblyFileVersion("0.3.0.0")]

namespace RobRunZh
{
    internal static class Program
    {
        internal const string Version = "0.3.0";

        [STAThread]
        private static int Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            try
            {
                if (args.Length == 3 && args[0] == "--self-test-ui")
                    return MainForm.SelfCheck(args[1], args[2]);
                string home = AppDomain.CurrentDomain.BaseDirectory;
                Application.Run(new MainForm(new Manager(home), home, Manager.DefaultProfile(), true));
                return 0;
            }
            catch (Exception error)
            {
                if (args.Length == 3 && args[0] == "--self-test-ui")
                {
                    File.WriteAllText(args[2], new JavaScriptSerializer().Serialize(new { passed = false, error = MainForm.Redact(error.ToString()) }), new UTF8Encoding(false));
                    return 1;
                }
                MessageBox.Show(MainForm.Redact(error.Message), "无法启动", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
        }
    }

    internal sealed class MainForm : Form
    {
        private static readonly Color Blue = Color.FromArgb(7, 85, 223);
        private static readonly Color Ink = Color.FromArgb(23, 32, 51);
        private static readonly Color Muted = Color.FromArgb(98, 108, 123);
        private const string SensitiveKey = @"(?:access[_ -]?token|refresh[_ -]?token|authorization|password|passwd|api[_ -]?key|client[_ -]?secret|secret|token|account(?:[_ -]?id)?|steam[_ -]?id|账号|账户ID)";
        private readonly Manager manager;
        private readonly string home;
        private readonly string profile;
        private readonly List<string> logs = new List<string>();
        private readonly List<Control> controls = new List<Control>();
        private readonly TextBox gamePath = new TextBox();
        private readonly TextBox logText = new TextBox();
        private readonly Label status = new Label();
        private readonly Label feedback = new Label();
        private readonly Label badge = new Label();
        private readonly Button install;
        private readonly Button remove;
        private readonly Panel body;
        private bool busy;
        private string lastError = "";
        private string packageStatus = "尚未检查";

        internal MainForm(Manager manager, string home, string profile, bool autoLocate)
        {
            this.manager = manager;
            this.home = home;
            this.profile = profile;
            Text = "ROB RUN 中文适配工具 · v" + Program.Version;
            Font = new Font("Microsoft YaHei UI", 10F);
            ForeColor = Ink;
            BackColor = Color.White;
            AutoScaleDimensions = new SizeF(96F, 96F);
            AutoScaleMode = AutoScaleMode.Dpi;
            StartPosition = FormStartPosition.CenterScreen;
            MinimumSize = new Size(760, 570);
            ClientSize = new Size(1000, 730);

            var frame = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 3 };
            frame.RowStyles.Add(new RowStyle(SizeType.Absolute, 82));
            frame.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            frame.RowStyles.Add(new RowStyle(SizeType.Absolute, 58));
            Controls.Add(frame);
            var header = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 3, Padding = new Padding(28, 15, 28, 10), BackColor = Color.FromArgb(248, 250, 255) };
            header.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            header.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            header.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            header.Controls.Add(MakeLabel("ROB RUN", 23F, FontStyle.Bold, Blue), 0, 0);
            var name = MakeLabel("中文适配工具", 17F, FontStyle.Bold, Ink);
            name.Margin = new Padding(24, 4, 0, 0);
            header.Controls.Add(name, 1, 0);
            header.Controls.Add(MakeLabel("v" + Program.Version, 10F, FontStyle.Regular, Muted), 2, 0);
            frame.Controls.Add(header, 0, 0);

            body = new Panel { Dock = DockStyle.Fill, AutoScroll = true, Padding = new Padding(28, 18, 28, 10) };
            frame.Controls.Add(body, 0, 1);
            var content = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 1, Padding = Padding.Empty };
            content.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            body.Controls.Add(content);
            content.Controls.Add(MakeLabel("游戏目录", 19F, FontStyle.Bold, Ink), 0, 0);

            var paths = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 3, Margin = new Padding(0, 12, 0, 20) };
            paths.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            paths.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            paths.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            gamePath.Dock = DockStyle.Fill;
            gamePath.Font = new Font(Font.FontFamily, 11F);
            gamePath.Margin = new Padding(0, 10, 10, 0);
            gamePath.AccessibleName = "ROB RUN 游戏目录";
            gamePath.KeyDown += delegate(object sender, KeyEventArgs e) { if (e.KeyCode == Keys.Enter) { e.SuppressKeyPress = true; RefreshStatus(); } };
            gamePath.TextChanged += delegate { if (!busy) { packageStatus = "尚未检查"; status.Text = "目录已更改；按 Enter 可检查语言包状态。"; badge.Text = "未检查"; SetBusy(false); } };
            paths.Controls.Add(gamePath, 0, 0);
            var locate = MakeButton("自动定位", false, delegate { Locate(); });
            var browse = MakeButton("选择目录", false, delegate { Browse(); });
            paths.Controls.Add(locate, 1, 0);
            paths.Controls.Add(browse, 2, 0);
            controls.AddRange(new Control[] { gamePath, locate, browse });
            content.Controls.Add(paths, 0, 1);

            var card = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 1, Padding = new Padding(24, 18, 24, 18), BackColor = Color.FromArgb(241, 246, 255), Margin = new Padding(0, 0, 0, 18) };
            card.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            var title = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, WrapContents = false };
            title.Controls.Add(MakeLabel("简体中文", 21F, FontStyle.Bold, Ink));
            badge.Text = "未检查";
            badge.AutoSize = true;
            badge.BackColor = Color.FromArgb(225, 231, 240);
            badge.ForeColor = Muted;
            badge.Padding = new Padding(10, 4, 10, 4);
            badge.Margin = new Padding(18, 6, 0, 0);
            title.Controls.Add(badge);
            card.Controls.Add(title, 0, 0);
            status.Text = autoLocate ? "正在定位游戏目录…" : "请选择游戏安装目录。";
            status.AutoSize = true;
            status.ForeColor = Muted;
            status.Margin = new Padding(0, 12, 0, 12);
            status.MaximumSize = new Size(860, 0);
            card.Controls.Add(status, 0, 1);
            card.SizeChanged += delegate { status.MaximumSize = new Size(Math.Max(250, card.ClientSize.Width - card.Padding.Horizontal - 8), 0); };
            var actions = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, WrapContents = true, Margin = Padding.Empty };
            install = MakeButton("安装中文语言包", true, delegate { Operation(true); });
            install.MinimumSize = new Size(250, 48);
            remove = MakeButton("移除语言包", false, delegate { Operation(false); });
            remove.MinimumSize = new Size(170, 48);
            actions.Controls.Add(install);
            actions.Controls.Add(remove);
            card.Controls.Add(actions, 0, 2);
            controls.AddRange(new Control[] { install, remove });
            content.Controls.Add(card, 0, 2);

            var logHeader = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 2, Margin = new Padding(0, 0, 0, 8) };
            logHeader.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            logHeader.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            logHeader.Controls.Add(MakeLabel("操作记录", 11F, FontStyle.Bold, Ink), 0, 0);
            logHeader.Controls.Add(MakeButton("复制日志", false, delegate { CopyLogs(); }), 1, 0);
            content.Controls.Add(logHeader, 0, 3);
            logText.Multiline = true;
            logText.ReadOnly = true;
            logText.ScrollBars = ScrollBars.Vertical;
            logText.Dock = DockStyle.Fill;
            logText.BorderStyle = BorderStyle.FixedSingle;
            logText.BackColor = Color.FromArgb(243, 246, 250);
            logText.MinimumSize = new Size(0, 175);
            logText.AccessibleName = "操作记录";
            content.Controls.Add(logText, 0, 4);

            var footer = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 3, Padding = new Padding(28, 4, 28, 4) };
            footer.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            footer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            footer.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            var export = MakeButton("导出诊断", false, delegate { ExportDiagnostics(); });
            footer.Controls.Add(export, 0, 0);
            controls.Add(export);
            feedback.Dock = DockStyle.Fill;
            feedback.TextAlign = ContentAlignment.MiddleRight;
            feedback.ForeColor = Muted;
            feedback.AutoEllipsis = true;
            feedback.Margin = new Padding(12, 0, 12, 0);
            footer.Controls.Add(feedback, 1, 0);
            footer.Controls.Add(MakeButton("免责声明", false, delegate { using (var dialog = Disclosure()) dialog.ShowDialog(this); }), 2, 0);
            frame.Controls.Add(footer, 0, 2);
            FormClosing += delegate(object sender, FormClosingEventArgs e) { if (busy) { e.Cancel = true; feedback.Text = "正在处理文件，请等待完成后再关闭。"; } };
            SetBusy(false);
            if (autoLocate) Shown += delegate { Locate(); };
        }

        private static Label MakeLabel(string text, float size, FontStyle style, Color color)
        {
            return new Label { Text = text, AutoSize = true, Font = new Font("Microsoft YaHei UI", size, style), ForeColor = color, Margin = new Padding(0, 3, 0, 3), Anchor = AnchorStyles.Left };
        }

        private Button MakeButton(string text, bool primary, EventHandler click)
        {
            var button = new Button { Text = text, AutoSize = true, MinimumSize = new Size(95, 40), Padding = new Padding(14, 6, 14, 6), Margin = new Padding(0, 0, 10, 0), FlatStyle = FlatStyle.Flat, BackColor = primary ? Blue : Color.White, ForeColor = primary ? Color.White : Blue, UseVisualStyleBackColor = false };
            button.FlatAppearance.BorderColor = primary ? Blue : Color.FromArgb(197, 205, 219);
            if (primary) button.Font = new Font(Font.FontFamily, 12F, FontStyle.Bold);
            button.Click += click;
            return button;
        }

        private void SetBusy(bool value)
        {
            busy = value;
            foreach (Control control in controls) control.Enabled = !value;
            if (!value && String.IsNullOrWhiteSpace(gamePath.Text)) { install.Enabled = false; remove.Enabled = false; }
            UseWaitCursor = value;
        }

        internal static string Redact(string value)
        {
            string text = value ?? "";
            text = Regex.Replace(text, @"\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [已隐藏]", RegexOptions.IgnoreCase);
            text = Regex.Replace(text, "(" + SensitiveKey + @"[""']?\s*[=:：]\s*)(""[^""]*""|'[^']*'|[^\s,;}\]]+)", match => match.Groups[1].Value + "[已隐藏]", RegexOptions.IgnoreCase);
            text = Regex.Replace(text, @"\b7656\d{13}\b", "[Steam账号已隐藏]");
            text = Regex.Replace(text, @"([A-Z]:[\\/]Users[\\/])[^\\/\r\n""']+", "$1[用户]", RegexOptions.IgnoreCase);
            return text;
        }

        private void Log(string text)
        {
            logs.Add(DateTime.Now.ToString("HH:mm:ss") + "  " + Redact(text));
            if (logs.Count > 1000) logs.RemoveRange(0, logs.Count - 1000);
            logText.Lines = logs.ToArray();
            logText.SelectionStart = logText.TextLength;
            logText.ScrollToCaret();
        }

        private async void Work(string heading, Func<string> action, bool statusOnly)
        {
            if (busy) return;
            string game = gamePath.Text.Trim();
            SetBusy(true);
            feedback.Text = heading + "，请稍候…";
            Log(heading + "…");
            try
            {
                string message = await Task.Run(action);
                Log(message);
                if (statusOnly) ApplyStatus(message);
                else
                {
                    try { ApplyStatus(await Task.Run(() => manager.Status(game, profile))); }
                    catch (Exception error)
                    {
                        lastError = Redact(error.Message);
                        string warning = "操作已完成，但状态刷新失败：" + lastError;
                        Log(warning);
                        feedback.Text = warning;
                        status.Text = warning;
                        badge.Text = "需要处理";
                        return;
                    }
                }
                feedback.Text = "操作完成。";
            }
            catch (Exception error)
            {
                lastError = Redact(error.Message);
                Log("操作未完成：" + lastError);
                feedback.Text = "操作未完成，详见操作记录。";
                status.Text = lastError;
                status.ForeColor = Color.FromArgb(180, 35, 24);
                badge.Text = "需要处理";
            }
            finally { SetBusy(false); }
        }

        private async void Locate()
        {
            if (busy) return;
            bool located = false;
            SetBusy(true);
            Log("自动定位游戏目录…");
            try
            {
                string[] games = await Task.Run(() => Manager.LocateGames());
                if (games.Length == 0) throw new InvalidOperationException("未自动找到游戏，请选择包含 ROB RUN.exe 的安装目录。");
                gamePath.Text = games[0];
                located = true;
                ApplyStatus(await Task.Run(() => manager.Status(games[0], profile)));
                Log("已定位游戏目录；语言包状态检查完成。");
                feedback.Text = "检查完成。";
            }
            catch (Exception error)
            {
                lastError = Redact(error.Message);
                status.Text = lastError;
                badge.Text = located ? "需要处理" : "未定位";
                Log(lastError);
            }
            finally { SetBusy(false); }
        }

        private void Browse()
        {
            if (busy) return;
            using (var dialog = new FolderBrowserDialog { Description = "选择 ROB RUN 游戏安装目录", SelectedPath = gamePath.Text })
                if (dialog.ShowDialog(this) == DialogResult.OK) { gamePath.Text = dialog.SelectedPath; RefreshStatus(); }
        }

        private void RefreshStatus()
        {
            string game = gamePath.Text.Trim();
            if (busy || game.Length == 0) return;
            Work("检查语言包状态", () => manager.Status(game, profile), true);
        }

        private void ApplyStatus(string value)
        {
            packageStatus = Redact(value);
            status.Text = "Build " + manager.Build + " · " + packageStatus;
            status.ForeColor = Muted;
            badge.Text = value.StartsWith("附加语言已安装", StringComparison.Ordinal) ? "已安装" : value.StartsWith("未安装", StringComparison.Ordinal) ? "未安装" : "需要处理";
            install.Text = value.Contains("官方") && value.Contains("备份") && value.StartsWith("未安装", StringComparison.Ordinal) ? "备份缓存并安装" : "安装中文语言包";
        }

        private void Operation(bool adding)
        {
            string game = gamePath.Text.Trim();
            if (busy || game.Length == 0) return;
            Work(adding ? "安装语言包" : "移除语言包", () => adding ? manager.Install(game, profile) : manager.Remove(game, profile), false);
        }

        private void CopyLogs()
        {
            try { Clipboard.SetText(Redact(String.Join(Environment.NewLine, logs.ToArray()))); feedback.Text = "日志已复制，常见敏感字段已隐藏。"; }
            catch (Exception error) { Log("复制失败：" + error.Message); }
        }

        private Dictionary<string, object> LogSummary(string name)
        {
            string path = Path.Combine(profile, name);
            var result = new Dictionary<string, object> { { "exists", File.Exists(path) } };
            if (!File.Exists(path)) return result;
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            {
                result["bytes"] = stream.Length;
                stream.Position = Math.Max(0, stream.Length - 131072);
                using (var reader = new StreamReader(stream, Encoding.UTF8))
                {
                    string tail = reader.ReadToEnd();
                    result["error_markers"] = Regex.Matches(tail, @"\b(?:E-\d{4}|SocketException|HttpRequestException|TimeoutException|WebException|NetworkUnreachable|ConnectionRefused|AuthenticationFailed|HeartbeatTimeout|NullClient)\b", RegexOptions.IgnoreCase).Cast<Match>().Select(m => m.Value).Distinct().Take(20).ToArray();
                    result["keyword_counts"] = new[] { "error", "exception", "anti-cheat", "eac", "catalog", "localization" }.ToDictionary(word => word, word => Regex.Matches(tail, Regex.Escape(word), RegexOptions.IgnoreCase).Count);
                }
            }
            result["sample"] = "last_128_KiB";
            return result;
        }

        private void ExportDiagnostics()
        {
            if (busy) return;
            using (var dialog = new SaveFileDialog { Title = "导出本地诊断摘要", FileName = "ROB_RUN_诊断.json", Filter = "JSON 诊断摘要|*.json", DefaultExt = "json" })
            {
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                try
                {
                    var report = new Dictionary<string, object> {
                        { "schema", 1 }, { "created_at", DateTimeOffset.Now.ToString("o") },
                        { "tool", "ROB RUN 中文适配工具" }, { "tool_version", Program.Version },
                        { "runtime", ".NET Framework" }, { "package_build", manager.Build },
                        { "game_directory", Redact(gamePath.Text) }, { "package_status", packageStatus },
                        { "last_error", lastError }, { "tool_logs", logs.ToArray() },
                        { "existing_game_logs", new Dictionary<string, object> { { "Player.log", LogSummary("Player.log") }, { "Player-prev.log", LogSummary("Player-prev.log") } } }
                    };
                    File.WriteAllText(dialog.FileName, new JavaScriptSerializer().Serialize(report), new UTF8Encoding(false));
                    Log("已将脱敏诊断摘要保存到所选本地文件。");
                    feedback.Text = "诊断已导出到本地，未上传。";
                }
                catch (Exception error) { lastError = Redact(error.Message); Log("导出失败：" + lastError); feedback.Text = "导出失败，详见操作记录。"; }
            }
        }

        private Form Disclosure()
        {
            var dialog = new Form { Text = "免责声明与第三方许可", Font = Font, StartPosition = FormStartPosition.CenterParent, Size = new Size(820, 620), MinimumSize = new Size(480, 320), ShowInTaskbar = false };
            var tabs = new TabControl { Dock = DockStyle.Fill, Padding = new Point(12, 6) };
            dialog.Controls.Add(tabs);
            var licenses = new List<string> { Path.Combine(home, "THIRD_PARTY_NOTICES.md") };
            licenses.AddRange(Directory.GetFiles(home, "*LICENSE.txt").OrderBy(p => p, StringComparer.OrdinalIgnoreCase));
            string thirdParty = Path.Combine(home, "third_party_licenses");
            if (Directory.Exists(thirdParty)) licenses.AddRange(Directory.GetFiles(thirdParty, "*", SearchOption.AllDirectories).OrderBy(p => p, StringComparer.OrdinalIgnoreCase));
            string[][] groups = { new[] { Path.Combine(home, "DISCLAIMER.md") }, licenses.ToArray() };
            string[] names = { "免责声明", "第三方许可" };
            for (int i = 0; i < groups.Length; i++)
            {
                var page = new TabPage(names[i]) { Padding = new Padding(14) };
                var text = new RichTextBox { Dock = DockStyle.Fill, ReadOnly = true, BackColor = Color.White, BorderStyle = BorderStyle.None, DetectUrls = false, Font = Font, WordWrap = true };
                var content = new StringBuilder();
                foreach (string file in groups[i])
                {
                    content.AppendLine(Path.GetFileName(file)).AppendLine();
                    try { content.AppendLine(File.ReadAllText(file, Encoding.UTF8)); }
                    catch (IOException) { content.AppendLine("文件缺失或不可读取，请从完整发布包重新获取。"); }
                    content.AppendLine();
                }
                text.Text = content.ToString();
                page.Controls.Add(text);
                tabs.TabPages.Add(page);
            }
            return dialog;
        }

        internal static int SelfCheck(string baseDirectory, string resultPath)
        {
            string profile = Path.Combine(Path.GetTempPath(), "rob-run-ui-check-" + Guid.NewGuid().ToString("N"));
            string report = Path.GetFullPath(resultPath);
            Directory.CreateDirectory(Path.GetDirectoryName(report));
            int exit = 1;
            using (var form = new MainForm(new Manager(baseDirectory), baseDirectory, profile, false))
            {
                form.Shown += async delegate
                {
                    try
                    {
                        if (form.install.Enabled || form.remove.Enabled) throw new InvalidOperationException("Empty game path must disable file operations");
                        string input = "Authorization: Bearer PRIVATE_TOKEN account=PRIVATE_ACCOUNT steamId=76561198000000000 C:\\Users\\PrivateName\\x";
                        string cleaned = Redact(input);
                        if (cleaned.Contains("PRIVATE_TOKEN") || cleaned.Contains("PRIVATE_ACCOUNT") || cleaned.Contains("76561198000000000") || cleaned.Contains("PrivateName")) throw new InvalidOperationException("Diagnostic redaction failed");
                        form.gamePath.Text = Path.Combine(profile, "fake-game");
                        form.SetBusy(true);
                        if (form.controls.Any(control => control.Enabled)) throw new InvalidOperationException("Busy controls remain enabled");
                        form.Close();
                        if (form.IsDisposed) throw new InvalidOperationException("Close must be blocked during file work");
                        form.SetBusy(false);
                        form.ApplyStatus("未安装附加语言 · 官方缓存可备份切换");
                        if (form.install.Text != "备份缓存并安装") throw new InvalidOperationException("Official cache action missing");
                        int completed = 0;
                        form.Work("测试操作", delegate { completed++; return "测试操作成功。"; }, false);
                        DateTime deadline = DateTime.UtcNow.AddSeconds(5);
                        while (form.busy && DateTime.UtcNow < deadline) await Task.Delay(10);
                        if (form.busy || completed != 1 || !form.feedback.Text.StartsWith("操作已完成，但状态刷新失败：", StringComparison.Ordinal)
                            || !form.logs.Any(line => line.Contains("测试操作成功。")) || Directory.Exists(profile))
                            throw new InvalidOperationException("Completed operation must survive a status-refresh failure without retry or profile writes");
                        using (var disclosure = form.Disclosure())
                        {
                            var tabs = (TabControl)disclosure.Controls[0];
                            if (tabs.TabCount != 2 || tabs.TabPages.Cast<TabPage>().Any(page => !((RichTextBox)page.Controls[0]).ReadOnly)) throw new InvalidOperationException("Disclosure must have two read-only tabs");
                        }
                        form.ApplyStatus("未安装附加语言 · 官方缓存可备份切换");
                        form.feedback.Text = "检查完成。";
                        using (var image = new Bitmap(form.Width, form.Height)) { form.DrawToBitmap(image, new Rectangle(Point.Empty, image.Size)); image.Save(Path.ChangeExtension(report, ".normal.png")); }
                        form.ClientSize = new Size(760, 570);
                        await Task.Delay(10);
                        if (!form.body.AutoScroll) throw new InvalidOperationException("Small window must scroll");
                        using (var image = new Bitmap(form.Width, form.Height)) { form.DrawToBitmap(image, new Rectangle(Point.Empty, image.Size)); image.Save(Path.ChangeExtension(report, ".png")); }
                        File.WriteAllText(report, new JavaScriptSerializer().Serialize(new { passed = true, checks = new[] { "empty-path-disabled", "redaction", "busy-reentry-controls", "close-protection", "official-cache-label", "completed-operation-status-refresh-failure/no-retry/no-profile-write", "readonly-license-tabs", "small-window-scroll" }, real_game_or_profile_written = false }), new UTF8Encoding(false));
                        exit = 0;
                    }
                    catch (Exception error)
                    {
                        File.WriteAllText(report, new JavaScriptSerializer().Serialize(new { passed = false, error = Redact(error.ToString()) }), new UTF8Encoding(false));
                    }
                    finally { form.SetBusy(false); form.Close(); }
                };
                Application.Run(form);
                return exit;
            }
        }
    }
}
