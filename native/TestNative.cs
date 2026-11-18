// Compile with Manager.cs and DeltaPatch.cs; all mutations stay in a new work fixture.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;
using RobRunZh;

namespace RobRunZhTests
{
    internal static class TestNative
    {
        static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 8000000 };
        static readonly string Aa = @"ROB RUN_Data\StreamingAssets\aa\StandaloneWindows64";
        static readonly string Catalog = "catalog_test.bin";
        static readonly string Marker = "catalog_test.hash";
        static readonly string[] Targets = {
            @"codex_zh_addon\zh-cn-locales.bundle", @"codex_zh_addon\zh-cn-tables.bundle",
            @"codex_zh_addon\font-extension.bundle", @"com.unity.addressables\catalog_test.bin",
            @"com.unity.addressables\catalog_test.hash", @"codex_zh_addon\locale-map.bundle" };
        static readonly List<string> Passed = new List<string>();
        static string Root, Package, Game;
        static Dictionary<string, object> Spec;
        static readonly Dictionary<string, byte[]> Payloads = new Dictionary<string, byte[]>();
        static readonly Dictionary<string, byte[]> Originals = new Dictionary<string, byte[]>();
        static readonly byte[] BaseBytes = Encoding.UTF8.GetBytes("original small local game resource\n");
        static readonly byte[] LegacyTable = Encoding.UTF8.GetBytes("previous translated table\n");
        static string PatchPath;

        static void Assert(bool value, string message)
        { if (!value) throw new Exception("ASSERT: " + message); }

        static string Sha(byte[] bytes)
        { using (var hash = SHA256.Create()) return BitConverter.ToString(hash.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant(); }

        static void Write(string path, byte[] bytes)
        { Directory.CreateDirectory(Path.GetDirectoryName(path)); File.WriteAllBytes(path, bytes); }

        static void Save(string path, object value)
        { Write(path, new UTF8Encoding(false).GetBytes(Json.Serialize(value))); }

        static Dictionary<string, object> Read(string path)
        { return Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(path, Encoding.UTF8)); }

        static Dictionary<string, object> Map(object value)
        { return (Dictionary<string, object>)value; }

        static void Reject(Action action, string name)
        {
            try { action(); }
            catch (Exception error)
            { if (error.Message.StartsWith("ASSERT:")) throw; return; }
            throw new Exception("ASSERT: did not reject " + name);
        }

        static Dictionary<string, string> Snapshot(string profile)
        {
            var result = new Dictionary<string, string>();
            if (Directory.Exists(profile))
                foreach (string path in Directory.GetFiles(profile, "*", SearchOption.AllDirectories))
                    if (Path.GetFileName(path) != ".codex_zh_addon.lock")
                        result[path.Substring(profile.Length)] = Sha(File.ReadAllBytes(path)) + ":" + File.GetLastWriteTimeUtc(path).Ticks;
            return result;
        }

        static bool Same(Dictionary<string, string> a, Dictionary<string, string> b)
        { return a.Count == b.Count && a.All(pair => b.ContainsKey(pair.Key) && b[pair.Key] == pair.Value); }

        static string Profile(string name, bool official)
        {
            string path = Path.Combine(Root, name);
            Directory.CreateDirectory(path);
            if (official) RestoreOfficial(path);
            return path;
        }

        static string Owner(string profile) { return Path.Combine(profile, "codex_zh_addon"); }
        static string StatePath(string profile) { return Path.Combine(Owner(profile), "installed.json"); }
        static string Target(string profile, int index) { return Path.Combine(profile, Targets[index]); }
        static string Backup(string profile, int index)
        { return Path.Combine(Owner(profile), "cache-backup", Path.GetFileName(Targets[index])); }

        static void RestoreOfficial(string profile)
        {
            foreach (int i in new[] { 3, 4 }) Write(Target(profile, i), Originals[Targets[i]]);
        }

        static void AssertOfficial(string profile)
        {
            foreach (int i in new[] { 3, 4 })
                Assert(File.ReadAllBytes(Target(profile, i)).SequenceEqual(Originals[Targets[i]]), "official cache restored: " + i);
        }

        static void AssertRemoved(string profile, bool official)
        {
            foreach (int i in new[] { 0, 1, 2, 5 }) Assert(!File.Exists(Target(profile, i)), "payload removed: " + i);
            Assert(!File.Exists(StatePath(profile)), "journal removed");
            if (official) AssertOfficial(profile);
            else foreach (int i in new[] { 3, 4 }) Assert(!File.Exists(Target(profile, i)), "owned cache removed");
        }

        static byte[] SignedMagnitude(long value)
        {
            ulong number = value < 0 ? (ulong)(-value) : (ulong)value;
            byte[] bytes = BitConverter.GetBytes(number);
            if (value < 0) bytes[7] |= 128;
            return bytes;
        }

        static byte[] LiteralPatch(byte[] value)
        {
            byte[] raw, compressed;
            using (var content = new MemoryStream())
            using (var writer = new BinaryWriter(content))
            {
                writer.Write((long)value.Length); writer.Write((long)24); writer.Write((long)0); writer.Write((long)value.Length);
                writer.Write(SignedMagnitude(0)); writer.Write(SignedMagnitude(value.Length)); writer.Write(SignedMagnitude(0));
                writer.Write(value); writer.Flush(); raw = content.ToArray();
            }
            using (var result = new MemoryStream())
            {
                using (var zipped = new GZipStream(result, CompressionMode.Compress, true)) zipped.Write(raw, 0, raw.Length);
                compressed = result.ToArray();
            }
            using (var result = new MemoryStream())
            using (var writer = new BinaryWriter(result))
            {
                writer.Write(Encoding.ASCII.GetBytes("RRZHDF1\0"));
                writer.Write((long)raw.Length); writer.Write((long)compressed.Length); writer.Write(compressed); writer.Flush();
                return result.ToArray();
            }
        }

        static void Fixture()
        {
            Package = Path.Combine(Root, "package"); Game = Path.Combine(Root, "fake-game");
            Write(Path.Combine(Game, "ROB RUN.exe"), Encoding.ASCII.GetBytes("fake marker; never execute"));
            string baseName = Path.Combine(Aa, "original.bundle");
            string baseCatalog = Path.Combine(Aa, Catalog), baseMarker = Path.Combine(Aa, Marker);
            Originals[Targets[3]] = Encoding.ASCII.GetBytes("official catalog bytes\n");
            Originals[Targets[4]] = Encoding.ASCII.GetBytes("0123456789abcdef0123456789abcdef");
            Write(Path.Combine(Game, baseName), BaseBytes);
            Write(Path.Combine(Game, baseCatalog), Originals[Targets[3]]);
            Write(Path.Combine(Game, baseMarker), Originals[Targets[4]]);
            var originalMap = new Dictionary<string, string> {
                { baseName, Sha(BaseBytes) }, { baseCatalog, Sha(Originals[Targets[3]]) },
                { baseMarker, Sha(Originals[Targets[4]]) } };
            var files = new List<Dictionary<string, object>>();
            for (int i = 0; i < Targets.Length; i++)
            {
                byte[] content = i == 4 ? Originals[Targets[4]] : Encoding.UTF8.GetBytes("translated fixture 中文 " + i + "\n");
                Payloads[Targets[i]] = content;
                string source = "data/addon/resource-" + i + ".dat";
                var item = new Dictionary<string, object> { { "source", source }, { "target", Targets[i] }, { "sha256", Sha(content) } };
                if (i == 0)
                {
                    byte[] patch = LiteralPatch(content); PatchPath = Path.Combine(Package, source);
                    Write(PatchPath, patch);
                    item["patch"] = new Dictionary<string, object> { { "format", "rrzh-gzip-v1" }, { "base", baseName }, { "sha256", Sha(patch) } };
                }
                else Write(Path.Combine(Package, source), content);
                files.Add(item);
            }
            var legacy = new Dictionary<string, string>();
            foreach (string name in Targets.Take(5)) legacy[name] = Sha(Payloads[name]);
            legacy[Targets[1]] = Sha(LegacyTable);
            Spec = new Dictionary<string, object> {
                { "build", "test" }, { "original_sha256", originalMap }, { "files", files },
                { "legacy_files", new[] { legacy } },
                { "catalog_base_override", new Dictionary<string, object> {
                    { "base_catalog", baseCatalog }, { "base_marker", baseMarker },
                    { "base_catalog_sha256", originalMap[baseCatalog] }, { "base_marker_sha256", originalMap[baseMarker] },
                    { "inherited_base_version_fingerprint", Encoding.ASCII.GetString(Originals[Targets[4]]) },
                    { "candidate_is_official_content", false }, { "real_base_update_supported", false } } }
            };
            Save(Path.Combine(Package, "data/addon/manifest.json"), Spec);
        }

        static void Check()
        {
            object fullFiles = Spec["files"];
            string cacheOnlyProfile = Profile("cache-only-manifest", false);
            try
            {
                Spec["files"] = ((List<Dictionary<string, object>>)fullFiles)
                    .Where(item => ((string)item["target"]).StartsWith(@"com.unity.addressables\", StringComparison.Ordinal)).ToList();
                Save(Path.Combine(Package, "data/addon/manifest.json"), Spec);
                Reject(delegate { new Manager(Package).Install(Game, cacheOnlyProfile); }, "cache-only manifest lacks language payload");
                Assert(Snapshot(cacheOnlyProfile).Count == 0 && Directory.GetDirectories(cacheOnlyProfile).Length == 0,
                       "invalid cache-only manifest leaves only the operation lock");
            }
            finally
            {
                Spec["files"] = fullFiles;
                Save(Path.Combine(Package, "data/addon/manifest.json"), Spec);
            }
            Passed.Add("cache-only-manifest-rejected-before-profile-transaction");

            var manager = new Manager(Package);
            string profile = Profile("no-cache", false);
            manager.Install(Game, profile);
            Assert(File.ReadAllBytes(Target(profile, 0)).SequenceEqual(Payloads[Targets[0]]), "delta rebuilt exact");
            Assert(manager.Status(Game, profile).Contains("已安装"), "installed status");
            var before = Snapshot(profile);
            manager.Install(Game, profile);
            Assert(Same(before, Snapshot(profile)), "idempotent install writes no file");
            manager.Remove(Game, profile); AssertRemoved(profile, false);
            Passed.Add("no-cache/install/delta/idempotent/remove");

            profile = Profile("official", true); manager.Install(Game, profile);
            var state = Read(StatePath(profile));
            Assert(Convert.ToInt32(state["schema"]) == 2 && (string)state["phase"] == "installed", "schema2 journal");
            Assert(Map(state["original_cache"]).Count == 2, "complete original pair journal");
            foreach (int i in new[] { 3, 4 }) Assert(File.ReadAllBytes(Backup(profile, i)).SequenceEqual(Originals[Targets[i]]), "backup exact");
            manager.Remove(Game, profile); AssertRemoved(profile, true);
            Passed.Add("official-pair/verified-backup/restore");

            foreach (string phase in new[] { "backing_up", "installing_payload", "switching_cache", "installed" })
            {
                profile = Profile("failure-" + phase, true);
                bool injected = false;
                manager.Step = delegate(string step) { if (step == phase && !injected) { injected = true; throw new IOException("injected phase failure"); } };
                Reject(delegate { manager.Install(Game, profile); }, phase); manager.Step = null;
                Assert(injected, "phase reached " + phase); AssertRemoved(profile, true);
            }
            Passed.Add("journal-and-phase-failure/rollback");

            // Hold the second cache without delete sharing: first switch succeeds, second must fail and roll back.
            profile = Profile("second-cache-failure", true); FileStream held = null;
            manager.Step = delegate(string step) { if (step == "switching_cache") held = new FileStream(Target(profile, 4), FileMode.Open, FileAccess.Read, FileShare.Read); };
            try { Reject(delegate { manager.Install(Game, profile); }, "second cache locked"); }
            finally { manager.Step = null; if (held != null) held.Dispose(); }
            AssertRemoved(profile, true); Passed.Add("second-cache-failure/first-cache-rollback");

            foreach (string phase in new[] { "backing_up", "switching_cache", "restoring_cache", "cleanup" })
            {
                profile = Profile("interrupted-" + phase, true); manager.Install(Game, profile);
                state = Read(StatePath(profile)); state["phase"] = phase;
                if (phase == "backing_up" || phase == "cleanup") RestoreOfficial(profile);
                else Write(Target(profile, 4), Originals[Targets[4]]);
                if (phase == "backing_up") foreach (int i in new[] { 0, 1, 2, 5 }) File.Delete(Target(profile, i));
                if (phase == "backing_up" || phase == "cleanup") File.Delete(Backup(profile, 4));
                Save(StatePath(profile), state); manager.Remove(Game, profile); AssertRemoved(profile, true);
            }
            Passed.Add("python-compatible-phases/interrupted-backup-switch-restore-cleanup");

            profile = Profile("schema1", false); manager.Install(Game, profile);
            state = Read(StatePath(profile)); state.Remove("schema"); state.Remove("original_cache"); Save(StatePath(profile), state);
            manager.Remove(Game, profile); AssertRemoved(profile, false); Passed.Add("python-schema1/no-original-cache");

            profile = Profile("unknown-cache", true); Write(Target(profile, 3), Encoding.ASCII.GetBytes("unknown")); before = Snapshot(profile);
            Reject(delegate { manager.Install(Game, profile); }, "unknown initial cache"); Assert(Same(before, Snapshot(profile)), "unknown initial preserved");
            foreach (string kind in new[] { "payload", "cache", "backup", "record", "schema", "backup-path" })
            {
                profile = Profile("tampered-" + kind, true); manager.Install(Game, profile);
                if (kind == "payload") Write(Target(profile, 0), new byte[] { 0 });
                else if (kind == "cache") Write(Target(profile, 4), new byte[] { 0 });
                else if (kind == "backup") Write(Backup(profile, 3), new byte[] { 0 });
                else
                {
                    state = Read(StatePath(profile));
                    if (kind == "record") Map(state["files"])[Targets[0]] = new string('0', 64);
                    else if (kind == "schema") state["schema"] = 99;
                    else Map(Map(state["original_cache"])[Targets[3]])["backup"] = @"..\outside.bin";
                    Save(StatePath(profile), state);
                }
                before = Snapshot(profile); Reject(delegate { manager.Remove(Game, profile); }, kind); Assert(Same(before, Snapshot(profile)), "tampered preserved " + kind);
            }
            Passed.Add("unknown-cache/payload/cache/backup/record-preserved");

            foreach (string kind in new[] { "payload", "backup" })
            {
                profile = Profile("official-status-" + kind, true); manager.Install(Game, profile); RestoreOfficial(profile);
                Write(kind == "payload" ? Target(profile, 0) : Backup(profile, 3), new byte[] { 9 });
                string status = manager.Status(Game, profile);
                Assert(status.Contains("未知变化") || status.Contains("备份异常"), "official caches do not hide tampered " + kind);
                before = Snapshot(profile); Reject(delegate { manager.Remove(Game, profile); }, "official caches plus tampered " + kind);
                Assert(Same(before, Snapshot(profile)), "official-status protection preserves " + kind);
            }
            Passed.Add("official-pair-does-not-hide-unknown-payload-or-broken-backup");

            profile = Profile("legacy-map", true); manager.Install(Game, profile);
            state = Read(StatePath(profile)); var oldFiles = new Dictionary<string, string>();
            foreach (string name in Targets.Take(5)) oldFiles[name] = Sha(Payloads[name]);
            oldFiles[Targets[1]] = Sha(LegacyTable); state["files"] = oldFiles;
            Write(Target(profile, 1), LegacyTable); Write(Target(profile, 5), Encoding.ASCII.GetBytes("unowned extra")); Save(StatePath(profile), state);
            Assert(manager.Status(Game, profile).Contains("旧版"), "legacy status"); before = Snapshot(profile);
            Reject(delegate { manager.Install(Game, profile); }, "legacy requires remove"); Assert(Same(before, Snapshot(profile)), "legacy install preserves state");
            manager.Remove(Game, profile); AssertOfficial(profile); Assert(File.ReadAllText(Target(profile, 5)) == "unowned extra", "unowned new target survives legacy removal");
            Assert(!File.Exists(StatePath(profile)), "legacy journal removed"); Passed.Add("exact-legacy-allowlist/untracked-new-target-preserved");

            profile = Profile("extra-file", true); manager.Install(Game, profile); Write(Path.Combine(Owner(profile), "note.txt"), new byte[] { 7 });
            manager.Remove(Game, profile); Assert(File.ReadAllBytes(Path.Combine(Owner(profile), "note.txt"))[0] == 7, "user note retained");
            Passed.Add("unrelated-owner-file-retained");

            byte[] patchBytes = File.ReadAllBytes(PatchPath);
            profile = Profile("bad-patch", false); Write(PatchPath, new byte[] { 1, 2 });
            try { Reject(delegate { manager.Install(Game, profile); }, "patch hash"); Assert(Snapshot(profile).Count == 0, "bad patch before transaction"); }
            finally { Write(PatchPath, patchBytes); }
            string basePath = Path.Combine(Game, Aa, "original.bundle");
            profile = Profile("bad-base", false); Write(basePath, new byte[] { 1, 2 });
            try { Reject(delegate { manager.Install(Game, profile); }, "base hash"); Assert(Snapshot(profile).Count == 0, "bad base before transaction"); }
            finally { Write(basePath, BaseBytes); }
            profile = Profile("remove-no-base", true); manager.Install(Game, profile); File.Delete(basePath);
            manager.Remove(Game, profile); AssertRemoved(profile, true); Write(basePath, BaseBytes);
            Passed.Add("bad-base-or-patch/no-transaction/remove-without-base");

            profile = Profile("lock", true); string lockPath = Path.Combine(profile, ".codex_zh_addon.lock");
            Write(lockPath, Encoding.ASCII.GetBytes("ROB_RUN_ZH_ADDON_LOCK_V1\n")); before = Snapshot(profile);
            using (var file = new FileStream(lockPath, FileMode.Open, FileAccess.ReadWrite, FileShare.ReadWrite))
            { file.Lock(0, 1); Reject(delegate { manager.Install(Game, profile); }, "exclusive operation lock"); file.Unlock(0, 1); }
            Assert(Same(before, Snapshot(profile)), "locked operation preserved files"); Passed.Add("python-byte-lock-compatibility");

            profile = Profile("junction", true);
            string link = Owner(profile), outside = Path.Combine(Root, "junction-outside");
            Write(Path.Combine(outside, "keep.bin"), new byte[] { 4, 5, 6 }); before = Snapshot(outside);
            var start = new ProcessStartInfo(Environment.GetEnvironmentVariable("COMSPEC"),
                "/d /c mklink /J \"" + link + "\" \"" + outside + "\"") {
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
            using (var process = Process.Start(start))
            {
                process.StandardOutput.ReadToEnd(); process.StandardError.ReadToEnd(); process.WaitForExit();
                Assert(process.ExitCode == 0, "create isolated junction fixture");
            }
            try
            {
                Reject(delegate { manager.Install(Game, profile); }, "junction install");
                Reject(delegate { manager.Remove(Game, profile); }, "junction remove");
                Assert(Same(before, Snapshot(outside)), "junction destination unchanged");
            }
            finally
            {
                Assert((File.GetAttributes(link) & FileAttributes.ReparsePoint) != 0, "unlink only junction");
                Directory.Delete(link, false);
            }
            Passed.Add("junction-escape-rejected/destination-untouched");

            // Complete refreshed official caches take priority over older saved caches.
            profile = Profile("official-refresh", true); manager.Install(Game, profile);
            foreach (int i in new[] { 3, 4 })
            {
                byte[] refreshed = Encoding.ASCII.GetBytes("new official version " + i);
                Write(Path.Combine(Game, Aa, Path.GetFileName(Targets[i])), refreshed); Write(Target(profile, i), refreshed);
            }
            before = Snapshot(Path.Combine(profile, "com.unity.addressables")); manager.Remove(Game, profile);
            Assert(Same(before, Snapshot(Path.Combine(profile, "com.unity.addressables"))), "refreshed official caches untouched");
            foreach (int i in new[] { 3, 4 }) Write(Path.Combine(Game, Aa, Path.GetFileName(Targets[i])), Originals[Targets[i]]);
            Passed.Add("new-official-cache-preserved-after-game-update");

            Assert(File.ReadAllBytes(basePath).SequenceEqual(BaseBytes), "base game unchanged");
            foreach (int i in new[] { 3, 4 }) Assert(File.ReadAllBytes(Path.Combine(Game, Aa, Path.GetFileName(Targets[i]))).SequenceEqual(Originals[Targets[i]]), "catalog game unchanged");
        }

        public static int Main(string[] args)
        {
            if (args.Length != 1) { Console.Error.WriteLine("Usage: TestNative.exe <workspace-work-directory>"); return 2; }
            string work = Path.GetFullPath(args[0]).TrimEnd(Path.DirectorySeparatorChar);
            Root = Path.GetFullPath(Path.Combine(work, "native-tests-" + Guid.NewGuid().ToString("N")));
            Assert(Root.StartsWith(work + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase), "fixture stays under work");
            Directory.CreateDirectory(Root);
            try
            {
                Fixture(); Check();
                Console.WriteLine(Json.Serialize(new { passed = true, checks = Passed, fixture = Root, real_game_or_profile_written = false }));
                return 0;
            }
            catch (Exception error)
            { Console.Error.WriteLine(error.ToString()); Console.Error.WriteLine("Fixture retained: " + Root); return 1; }
            // Fixtures are intentionally retained for review; no recursive cleanup of an unknown path.
        }
    }
}
