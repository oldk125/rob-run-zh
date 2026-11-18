using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;
using Microsoft.Win32;

namespace RobRunZh
{
    public sealed class PatchInfo { public string format; public string sha256; public string @base; }
    public sealed class Payload { public string source; public string target; public string sha256; public PatchInfo patch; }
    public sealed class Manifest
    {
        public string build;
        public Dictionary<string, string> original_sha256;
        public Payload[] files;
        public Dictionary<string, string>[] legacy_files;
        public Dictionary<string, string>[] previous_files;
    }
    public sealed class CacheBackup { public string backup; public string sha256; }
    public sealed class InstallState
    {
        public int schema = 1;
        public string phase;
        public Dictionary<string, string> files;
        public Dictionary<string, CacheBackup> original_cache = new Dictionary<string, CacheBackup>();
    }
    internal sealed class Entry
    {
        internal Payload Item;
        internal string Source, Target, Relative, Sha;
    }

    public sealed class Manager
    {
        private const string Owner = "codex_zh_addon";
        private const string Cache = "com.unity.addressables";
        private const string LockMarker = "ROB_RUN_ZH_ADDON_LOCK_V1\n";
        private readonly string baseDir;
        private readonly Manifest spec;
        internal Action<string> Step;
        public string Build { get { return spec.build; } }

        public Manager(string directory)
        {
            baseDir = Root(directory);
            spec = ReadJson<Manifest>(SafePath(baseDir, "data/addon/manifest.json"));
            Need(spec != null && spec.files != null && spec.original_sha256 != null && spec.files.Length > 0,
                 "语言包清单无效。");
        }

        private static void Need(bool condition, string message)
        {
            if (!condition) throw new InvalidOperationException(message);
        }
        private static bool ShaValid(string value)
        {
            return value != null && Regex.IsMatch(value, "\\A[0-9a-f]{64}\\z");
        }
        private static bool Exists(string path) { return File.Exists(path) || Directory.Exists(path); }
        private static void NoLinks(string path)
        {
            for (string current = Path.GetFullPath(path); !String.IsNullOrEmpty(current); )
            {
                try { Need((File.GetAttributes(current) & FileAttributes.ReparsePoint) == 0, "路径包含链接或重解析点，未修改文件。"); }
                catch (FileNotFoundException) { }
                catch (DirectoryNotFoundException) { }
                string parent = Path.GetDirectoryName(current);
                if (String.Equals(parent, current, StringComparison.OrdinalIgnoreCase)) break;
                current = parent;
            }
        }
        private static string Root(string value)
        {
            Need(!String.IsNullOrWhiteSpace(value), "目录不能为空。");
            string result = Path.GetFullPath(value);
            if (result.Length > Path.GetPathRoot(result).Length) result = result.TrimEnd('\\', '/');
            NoLinks(result);
            return result;
        }
        private static string SafePath(string root, string relative)
        {
            Need(!String.IsNullOrEmpty(relative) && !Path.IsPathRooted(relative) && relative.IndexOf(':') < 0,
                 "资源路径无效。");
            string[] parts = relative.Replace('/', '\\').Split('\\');
            Need(parts.All(p => p.Length > 0 && p != "." && p != ".." && p.TrimEnd(' ', '.') == p), "资源路径越界或无效。");
            string result = Path.GetFullPath(Path.Combine(root, relative.Replace('/', '\\')));
            Need(result.StartsWith(root.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase), "资源路径越界。");
            NoLinks(result);
            return result;
        }
        public static string Hash(string path)
        {
            NoLinks(path);
            Need(!Directory.Exists(path), "目标不是普通文件，未修改。");
            if (!File.Exists(path)) return null;
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
            using (var sha = SHA256.Create()) return Hex(sha.ComputeHash(stream));
        }
        private static string Hex(byte[] bytes) { return BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant(); }
        private static string BytesHash(byte[] bytes)
        {
            using (var sha = SHA256.Create()) return Hex(sha.ComputeHash(bytes));
        }
        private static T ReadJson<T>(string path)
        {
            NoLinks(path);
            Need(new FileInfo(path).Length <= 2097152, "记录文件过大，未修改。");
            return new JavaScriptSerializer { MaxJsonLength = 2097152 }.Deserialize<T>(File.ReadAllText(path, Encoding.UTF8));
        }
        private static void AtomicBytes(string target, byte[] bytes)
        {
            NoLinks(target);
            string parent = Path.GetDirectoryName(target);
            Directory.CreateDirectory(parent);
            string temporary = Path.Combine(parent, ".rob-zh-" + Guid.NewGuid().ToString("N"));
            try
            {
                using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                { stream.Write(bytes, 0, bytes.Length); stream.Flush(true); }
                NoLinks(target);
                if (File.Exists(target)) File.Replace(temporary, target, null);
                else File.Move(temporary, target);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
        private void Record(string owner, InstallState state, string phase)
        {
            state.phase = phase;
            AtomicBytes(SafePath(owner, "installed.json"), Encoding.UTF8.GetBytes(new JavaScriptSerializer().Serialize(state)));
            if (Step != null) Step(phase);
        }
        private static void Publish(string source, string target, string expected, bool replace, params string[] allowed)
        {
            NoLinks(source); NoLinks(target);
            string parent = Path.GetDirectoryName(target);
            Directory.CreateDirectory(parent);
            string temporary = Path.Combine(parent, ".rob-zh-" + Guid.NewGuid().ToString("N"));
            try
            {
                using (var input = new FileStream(source, FileMode.Open, FileAccess.Read, FileShare.Read))
                using (var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                { input.CopyTo(output); output.Flush(true); }
                Need(Hash(temporary) == expected, "暂存文件校验失败。");
                string current = Hash(target);
                if (replace)
                {
                    Need(allowed.Contains(current), "缓存出现未知变化，未覆盖。");
                    if (current == null) File.Move(temporary, target);
                    else File.Replace(temporary, target, null);
                }
                else
                {
                    Need(current == null, "目标文件已存在，未覆盖。");
                    File.Move(temporary, target);
                }
                Need(Hash(target) == expected, "文件回读校验失败。");
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
        private static void DeleteKnown(string path, params string[] allowed)
        {
            string current = Hash(path);
            Need(allowed.Contains(current), "文件出现未知变化，未删除。");
            if (current != null) File.Delete(path);
        }
        private static void RemoveEmpty(string directory)
        {
            NoLinks(directory);
            if (Directory.Exists(directory) && !Directory.EnumerateFileSystemEntries(directory).Any()) Directory.Delete(directory);
        }
        private static FileStream AcquireLock(string root)
        {
            NoLinks(root); Directory.CreateDirectory(root);
            string path = SafePath(root, ".codex_zh_addon.lock");
            FileStream stream;
            try
            {
                stream = new FileStream(path, FileMode.CreateNew, FileAccess.ReadWrite, FileShare.ReadWrite);
                byte[] marker = Encoding.ASCII.GetBytes(LockMarker);
                stream.Write(marker, 0, marker.Length); stream.Flush(true);
            }
            catch (IOException) { stream = new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.ReadWrite); }
            try
            {
                stream.Lock(0, 1);
                Need(stream.Length == Encoding.ASCII.GetByteCount(LockMarker), "操作锁文件不属于本工具，未修改现有文件。");
                stream.Position = 0;
                byte[] bytes = new byte[stream.Length];
                Need(stream.Read(bytes, 0, bytes.Length) == bytes.Length && Encoding.ASCII.GetString(bytes) == LockMarker,
                     "操作锁文件不属于本工具，未修改现有文件。");
                return stream;
            }
            catch { stream.Dispose(); throw; }
        }
        private static void RequireClosed()
        {
            foreach (var process in Process.GetProcesses())
            {
                using (process)
                {
                    string name;
                    try { name = process.ProcessName; } catch (InvalidOperationException) { continue; }
                    Need(!String.Equals(name, "ROB RUN", StringComparison.OrdinalIgnoreCase)
                         && !String.Equals(name, "start_protected_game", StringComparison.OrdinalIgnoreCase),
                         "请先退出 ROB RUN，再安装或移除汉化。");
                }
            }
        }
        private static string ProfileRoot(string game, string profile)
        {
            string root = Root(String.IsNullOrEmpty(profile) ? DefaultProfile() : profile);
            Need(!String.Equals(root, game, StringComparison.OrdinalIgnoreCase)
                 && !root.StartsWith(game.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase)
                 && !game.StartsWith(root.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase),
                 "用户数据目录与游戏目录重叠，未修改文件。");
            return root;
        }
        private string PatchBase(string game, PatchInfo patch)
        {
            Need(patch != null && patch.format == "rrzh-gzip-v1" && ShaValid(patch.sha256)
                 && patch.@base != null && spec.original_sha256.ContainsKey(patch.@base)
                 && ShaValid(spec.original_sha256[patch.@base]), "差分清单无效。");
            return SafePath(game, patch.@base);
        }
        private List<Entry> Plan(string game, string root, bool verify)
        {
            Need(File.Exists(SafePath(game, "ROB RUN.exe")), "请选择包含 ROB RUN.exe 的游戏目录。");
            if (verify) VerifyOriginals(game);
            var result = new List<Entry>();
            foreach (var item in spec.files)
            {
                Need(item != null && item.target != null && ShaValid(item.sha256), "语言包文件清单无效。");
                string relative = item.target.Replace('/', '\\');
                string[] parts = relative.Split('\\');
                Need(parts.Length == 2 && (parts[0] == Owner || parts[0] == Cache), "语言包目标路径无效。");
                string source = SafePath(baseDir, item.source);
                string target = SafePath(root, relative);
                if (item.patch != null) PatchBase(game, item.patch);
                Need(Hash(source) == (item.patch == null ? item.sha256 : item.patch.sha256), "附加包内容校验失败。");
                Need(!result.Any(e => String.Equals(e.Target, target, StringComparison.OrdinalIgnoreCase)), "语言包目标重复。");
                result.Add(new Entry { Item = item, Source = source, Target = target, Relative = relative, Sha = item.sha256 });
            }
            Caches(result);
            Need(ValidMap(Expected(result)), "语言包清单缺少有效的附加资源。");
            return result;
        }
        private void VerifyOriginals(string game)
        {
            foreach (var item in spec.original_sha256)
                Need(ShaValid(item.Value) && Hash(SafePath(game, item.Key)) == item.Value,
                     "原版资源不匹配，请先还原旧汉化或等待新版本适配。");
        }
        private static Entry[] Caches(List<Entry> files)
        {
            Entry[] result = files.Where(e => e.Relative.StartsWith(Cache + "\\", StringComparison.Ordinal)).OrderBy(e => e.Relative, StringComparer.Ordinal).ToArray();
            Need(result.Length == 2 && result.Select(e => Path.GetExtension(e.Target)).OrderBy(s => s).SequenceEqual(new[] { ".bin", ".hash" })
                 && result.Select(e => Path.GetFileNameWithoutExtension(e.Target)).Distinct().Count() == 1
                 && result.All(e => Path.GetFileName(e.Target).StartsWith("catalog_", StringComparison.Ordinal)), "语言包缓存清单无效。");
            return result;
        }
        private static Dictionary<string, string> Expected(List<Entry> files)
        {
            return files.ToDictionary(e => e.Relative, e => e.Sha, StringComparer.Ordinal);
        }
        private static bool Same(Dictionary<string, string> a, Dictionary<string, string> b)
        {
            return a != null && b != null && a.Count == b.Count && a.All(p => b.ContainsKey(p.Key) && b[p.Key] == p.Value);
        }
        private static bool Official(string game, Entry[] caches)
        {
            string aa = SafePath(game, "ROB RUN_Data/StreamingAssets/aa/StandaloneWindows64");
            return caches.All(e => Hash(e.Target) != null && Hash(e.Target) == Hash(SafePath(aa, Path.GetFileName(e.Target))));
        }
        private InstallState ReadState(string owner, List<Entry> files)
        {
            var current = Expected(files);
            var cacheKeys = Caches(files).Select(e => e.Relative).ToArray();
            var legacy = spec.legacy_files ?? new Dictionary<string, string>[0];
            foreach (var old in legacy)
                Need(old != null && cacheKeys.All(old.ContainsKey) && old.Keys.All(current.ContainsKey)
                     && old.Values.All(ShaValid) && !Same(old, current), "旧版记录白名单无效。");
            var previous = spec.previous_files ?? new Dictionary<string, string>[0];
            foreach (var old in previous)
                Need(ValidMap(old) && !Same(old, current), "跨版本记录白名单无效。");
            string record = SafePath(owner, "installed.json");
            Need(File.Exists(record), "未找到有效安装记录，已有目录未修改。");
            var state = ReadJson<InstallState>(record);
            Need(state != null && (state.schema == 1 || state.schema == 2)
                 && (Same(state.files, current) || legacy.Any(old => Same(state.files, old)) || previous.Any(old => Same(state.files, old))),
                 "安装记录不在当前或明确支持的旧版白名单中，未修改。");
            Need(new[] { "backing_up", "installing_payload", "switching_cache", "installed", "restoring_cache", "removing_cache", "removing_payload", "cleanup" }.Contains(state.phase),
                 "安装记录阶段无效，未修改。");
            if (state.original_cache == null) throw new InvalidOperationException("缓存备份记录无效。");
            if (state.original_cache.Count != 0)
            {
                List<Entry> recorded = EntriesFor(Path.GetDirectoryName(owner), state.files);
                string[] recordedCacheKeys = Caches(recorded).Select(e => e.Relative).ToArray();
                Need(state.original_cache.Count == 2 && recordedCacheKeys.All(state.original_cache.ContainsKey), "缓存备份记录不完整。");
                foreach (var entry in Caches(recorded))
                {
                    var item = state.original_cache[entry.Relative];
                    Need(item != null && item.backup == "cache-backup\\" + Path.GetFileName(entry.Target) && ShaValid(item.sha256), "缓存备份路径或校验值无效。");
                }
            }
            return state;
        }
        private static bool ValidMap(Dictionary<string, string> map)
        {
            if (map == null || map.Count < 3 || !map.Values.All(ShaValid)) return false;
            foreach (string key in map.Keys)
            {
                string[] parts = key.Split('\\');
                if (parts.Length != 2 || (parts[0] != Owner && parts[0] != Cache) || parts[1].Length == 0
                    || parts[1].IndexOfAny(new[] { '/', ':', '\\' }) >= 0 || parts[1].TrimEnd(' ', '.') != parts[1]
                    || parts[1] == "." || parts[1] == "..") return false;
            }
            string[] caches = map.Keys.Where(k => k.StartsWith(Cache + "\\", StringComparison.Ordinal)).ToArray();
            return caches.Length == 2 && caches.Select(Path.GetExtension).OrderBy(s => s).SequenceEqual(new[] { ".bin", ".hash" })
                && caches.Select(Path.GetFileNameWithoutExtension).Distinct().Count() == 1
                && caches.All(k => Path.GetFileName(k).StartsWith("catalog_", StringComparison.Ordinal));
        }
        private static List<Entry> EntriesFor(string root, Dictionary<string, string> map)
        {
            Need(ValidMap(map), "安装记录文件路径无效。");
            return map.Select(p => new Entry { Target = SafePath(root, p.Key), Relative = p.Key, Sha = p.Value }).ToList();
        }
        private static Dictionary<string, string[]> Backups(string owner, List<Entry> files, InstallState state, bool missingOk)
        {
            var result = new Dictionary<string, string[]>(StringComparer.Ordinal);
            foreach (var entry in Caches(files))
            {
                CacheBackup item;
                if (!state.original_cache.TryGetValue(entry.Relative, out item)) continue;
                string path = SafePath(owner, item.backup);
                string hash = Hash(path);
                Need(hash == item.sha256 || (missingOk && hash == null), "官方缓存备份缺失或校验失败，未覆盖缓存。");
                result[entry.Target] = new[] { path, item.sha256 };
            }
            return result;
        }
        private List<Entry> Prepare(string game, List<Entry> files, string temporary)
        {
            var result = new List<Entry>();
            foreach (var entry in files)
            {
                string source = entry.Source;
                if (entry.Item.patch != null)
                {
                    PatchInfo patch = entry.Item.patch;
                    byte[] original = File.ReadAllBytes(PatchBase(game, patch));
                    byte[] delta = File.ReadAllBytes(source);
                    Need(BytesHash(original) == spec.original_sha256[patch.@base] && BytesHash(delta) == patch.sha256,
                         "原版资源或差分内容校验失败，未安装。");
                    byte[] rebuilt = NativeDelta.Apply(original, delta);
                    Need(BytesHash(rebuilt) == entry.Sha, "差分重建结果校验失败，未安装。");
                    source = SafePath(temporary, result.Count.ToString());
                    AtomicBytes(source, rebuilt);
                }
                result.Add(new Entry { Item = entry.Item, Source = source, Target = entry.Target, Relative = entry.Relative, Sha = entry.Sha });
            }
            return result;
        }
        public string Install(string directory, string profile)
        {
            string game = Root(directory), root = ProfileRoot(game, profile);
            using (AcquireLock(root))
            {
                RequireClosed();
                List<Entry> files = Plan(game, root, true);
                string owner = SafePath(root, Owner);
                Entry[] caches = Caches(files);
                if (Exists(owner))
                {
                    InstallState old = ReadState(owner, files);
                    Need(Same(old.files, Expected(files)), "检测到旧版语言包，请先移除再安装。");
                    if (old.phase == "installed" && files.All(e => Hash(e.Target) == e.Sha))
                    { Backups(owner, files, old, false); return "中文语言包已安装，无需重复安装。"; }
                    throw new InvalidOperationException("语言包记录未完成或文件已变化，请先移除以恢复。");
                }
                bool existing = caches.Any(e => Exists(e.Target));
                Need(!existing || Official(game, caches), "已有缓存来源不明或版本混配，未覆盖现有文件。");
                var originals = new Dictionary<string, CacheBackup>();
                if (existing) foreach (var e in caches)
                    originals[e.Relative] = new CacheBackup { backup = "cache-backup\\" + Path.GetFileName(e.Target), sha256 = Hash(e.Target) };
                string temporary = Path.Combine(Path.GetTempPath(), "rob-zh-native-" + Guid.NewGuid().ToString("N"));
                NoLinks(temporary); Directory.CreateDirectory(temporary);
                try
                {
                    files = Prepare(game, files, temporary);
                    caches = Caches(files);
                    // Recheck after rebuilding; all resources are ready before profile transaction writes.
                    NoLinks(owner); Need(!Exists(owner), "附加语言目录已出现，未覆盖。");
                    Need(existing ? caches.All(e => Hash(e.Target) == originals[e.Relative].sha256) : caches.All(e => Hash(e.Target) == null),
                         "重建期间缓存出现变化，未覆盖。");
                    RequireClosed(); Directory.CreateDirectory(owner);
                    var state = new InstallState { schema = 2, files = Expected(files), original_cache = originals };
                    try
                    {
                        Record(owner, state, "backing_up");
                        if (originals.Count != 0)
                        {
                            foreach (var e in caches)
                            {
                                var item = originals[e.Relative];
                                Publish(e.Target, SafePath(owner, item.backup), item.sha256, false);
                            }
                            Backups(owner, files, state, false);
                            Need(caches.All(e => Hash(e.Target) == originals[e.Relative].sha256), "备份期间用户缓存变化，未切换。");
                        }
                        Record(owner, state, "installing_payload");
                        foreach (var e in files.Where(e => Path.GetDirectoryName(e.Target) == owner)) Publish(e.Source, e.Target, e.Sha, false);
                        Record(owner, state, "switching_cache"); RequireClosed();
                        foreach (var e in caches)
                            Publish(e.Source, e.Target, e.Sha, originals.Count != 0,
                                    originals.Count == 0 ? new string[0] : new[] { originals[e.Relative].sha256 });
                        Record(owner, state, "installed"); VerifyOriginals(game);
                    }
                    catch (Exception error)
                    {
                        try
                        {
                            if (File.Exists(SafePath(owner, "installed.json"))) RemoveOwned(game, root, files, ReadState(owner, files));
                            else RemoveEmpty(owner);
                        }
                        catch (Exception recovery)
                        { throw new InvalidOperationException("安装未完成：" + error.Message + "；恢复未完成：" + recovery.Message + "。已保留记录和备份，请重试移除。", error); }
                        throw;
                    }
                    return "中文语言包安装完成。";
                }
                finally
                {
                    // Only our freshly created temporary files; never recurse or delete game/profile paths.
                    foreach (var name in Enumerable.Range(0, files.Count).Select(i => i.ToString()))
                    { string path = SafePath(temporary, name); if (File.Exists(path)) File.Delete(path); }
                    RemoveEmpty(temporary);
                }
            }
        }
        private string RemoveOwned(string game, string root, List<Entry> files, InstallState state, List<Entry> manifestFiles = null)
        {
            string owner = SafePath(root, Owner);
            Entry[] caches = Caches(files);
            Entry[] owned = files.Where(e => !caches.Contains(e)).ToArray();
            bool original = state.original_cache.Count != 0;
            bool preserved = Official(game, caches);
            var before = caches.ToDictionary(e => e.Target, e => Hash(e.Target));
            bool originalPair = original && caches.All(e => before[e.Target] == state.original_cache[e.Relative].sha256);
            bool missingOk = (state.phase == "backing_up" && originalPair) || (state.phase == "cleanup" && (originalPair || preserved));
            var saved = Backups(owner, files, state, missingOk);
            foreach (var e in owned) Need(Hash(e.Target) == null || Hash(e.Target) == e.Sha, "附加资源存在未知变化，未删除。");
            if (!preserved)
            {
                foreach (var e in caches)
                    Need(before[e.Target] == null || before[e.Target] == e.Sha || (saved.ContainsKey(e.Target) && before[e.Target] == saved[e.Target][1]),
                         "用户缓存出现未知变化，保留记录和备份。");
                Need(state.phase != "cleanup" || saved.Count == 0 || originalPair, "清理阶段缓存变化，保留记录和备份。");
            }
            if (original && !preserved && !originalPair)
            {
                Record(owner, state, "restoring_cache");
                foreach (var e in caches)
                    if (Hash(e.Target) != saved[e.Target][1]) Publish(saved[e.Target][0], e.Target, saved[e.Target][1], true, null, e.Sha, saved[e.Target][1]);
                Need(caches.All(e => Hash(e.Target) == saved[e.Target][1]), "官方缓存恢复未完成，请重试移除。");
            }
            else if (!original && !preserved)
            {
                Record(owner, state, "removing_cache");
                foreach (var e in caches.Reverse()) DeleteKnown(e.Target, null, e.Sha);
            }
            Record(owner, state, "removing_payload");
            foreach (var e in owned.Reverse()) DeleteKnown(e.Target, null, e.Sha);
            Record(owner, state, "cleanup");
            foreach (var savedFile in saved.Values) DeleteKnown(savedFile[0], null, savedFile[1]);
            RemoveEmpty(SafePath(owner, "cache-backup"));
            string journal = SafePath(owner, "installed.json");
            // Do not delete a concurrently replaced or edited journal.
            InstallState latest = ReadState(owner, manifestFiles ?? files);
            Need(latest.phase == "cleanup" && Same(latest.files, state.files), "安装记录出现未知变化，未删除。");
            File.Delete(journal); RemoveEmpty(owner);
            return preserved ? "语言包已移除，官方内容缓存已保留。" : original ? "语言包已移除，安装前的官方缓存已恢复。" : "语言包已移除。";
        }
        public string Remove(string directory, string profile)
        {
            string game = Root(directory), root = ProfileRoot(game, profile);
            using (AcquireLock(root))
            {
                RequireClosed();
                List<Entry> current = Plan(game, root, false);
                InstallState state = ReadState(SafePath(root, Owner), current);
                List<Entry> recorded = EntriesFor(root, state.files);
                return RemoveOwned(game, root, recorded, state, current);
            }
        }
        public string Status(string directory, string profile)
        {
            string game = Root(directory), root = ProfileRoot(game, profile);
            List<Entry> files = Plan(game, root, true);
            Entry[] caches = Caches(files);
            string owner = SafePath(root, Owner);
            if (File.Exists(SafePath(owner, "installed.json")))
            {
                InstallState state = ReadState(owner, files);
                if (!Same(state.files, Expected(files))) return "旧版附加语言记录，请先移除再安装。";
                if (state.phase == "installed" && files.All(e => Hash(e.Target) == e.Sha))
                {
                    try { Backups(owner, files, state, false); } catch (InvalidOperationException) { return "语言包已安装，但备份异常，请保留现有文件。"; }
                    return "附加语言已安装";
                }
                if (Official(game, caches))
                {
                    try
                    {
                        bool originalPair = state.original_cache.Count != 0
                            && caches.All(e => Hash(e.Target) == state.original_cache[e.Relative].sha256);
                        bool missingOk = state.phase == "cleanup" || (state.phase == "backing_up" && originalPair);
                        Backups(owner, files, state, missingOk);
                        Need(files.Where(e => !caches.Contains(e)).All(e => Hash(e.Target) == null || Hash(e.Target) == e.Sha),
                             "附加资源存在未知变化。");
                    }
                    catch (InvalidOperationException) { return "附加语言存在未知变化或备份异常，请保留现有文件。"; }
                    return "官方缓存已恢复，可先移除旧汉化记录。";
                }
                return "语言包安装未完成或文件已变化，可尝试移除恢复；未知文件会保留。";
            }
            if (Exists(owner)) return "已有附加语言目录缺少有效记录，未修改。";
            if (Official(game, caches)) return "未安装 · 官方缓存可备份切换";
            return caches.Any(e => Exists(e.Target)) ? "已有缓存来源不明或版本混配，拒绝覆盖。" : "未安装附加语言";
        }
        public static string DefaultProfile()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "AppData", "LocalLow", "Kefir", "ROB RUN");
        }
        public static string[] LocateGames()
        {
            var roots = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            object steam = Registry.GetValue(@"HKEY_CURRENT_USER\Software\Valve\Steam", "SteamPath", null);
            if (steam != null) roots.Add(steam.ToString());
            steam = Registry.GetValue(@"HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath", null);
            if (steam != null) roots.Add(steam.ToString());
            foreach (string root in roots.ToArray())
            {
                string config = Path.Combine(root, "steamapps", "libraryfolders.vdf");
                if (!File.Exists(config)) continue;
                foreach (Match match in Regex.Matches(File.ReadAllText(config), "\"path\"\\s*\"([^\"]+)\""))
                    roots.Add(match.Groups[1].Value.Replace("\\\\", "\\"));
            }
            var games = new List<string>();
            foreach (string root in roots.OrderBy(p => p))
            {
                string manifest = Path.Combine(root, "steamapps", "appmanifest_4262460.acf");
                if (!File.Exists(manifest)) continue;
                Match match = Regex.Match(File.ReadAllText(manifest), "\"installdir\"\\s*\"([^\"]+)\"");
                if (!match.Success) continue;
                string name = match.Groups[1].Value;
                if (Path.IsPathRooted(name) || name.Contains("..")) continue;
                string game = Path.Combine(root, "steamapps", "common", name);
                if (File.Exists(Path.Combine(game, "ROB RUN.exe"))) games.Add(game);
            }
            return games.Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        }
    }
}
