using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using EnderBridge.App.Models;

namespace EnderBridge.App.Services;

public class VersionManagerService
{
    private const string RepoOwner = "Hydrooxzgen";
    private const string RepoName = "EnderBridge";
    private readonly HttpClient _http;

    public VersionManagerService()
    {
        _http = new HttpClient();
        _http.DefaultRequestHeaders.UserAgent.Add(new ProductInfoHeaderValue("EnderBridge-Desktop", "1.0"));
        _http.Timeout = TimeSpan.FromSeconds(30);
    }

    private static readonly string SettingsFilePath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "EnderBridge",
        "app_settings.json"
    );

    public string? GetCustomCorePath()
    {
        try
        {
            if (File.Exists(SettingsFilePath))
            {
                var text = File.ReadAllText(SettingsFilePath);
                using var doc = JsonDocument.Parse(text);
                if (doc.RootElement.TryGetProperty("custom_core_path", out var p))
                {
                    var val = p.GetString();
                    if (!string.IsNullOrWhiteSpace(val)) return val.Trim();
                }
            }
        }
        catch {}
        return null;
    }

    public void SetCustomCorePath(string? path)
    {
        try
        {
            var dir = Path.GetDirectoryName(SettingsFilePath);
            if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
            {
                Directory.CreateDirectory(dir);
            }
            var dict = new Dictionary<string, object>();
            if (File.Exists(SettingsFilePath))
            {
                try
                {
                    var oldText = File.ReadAllText(SettingsFilePath);
                    dict = JsonSerializer.Deserialize<Dictionary<string, object>>(oldText) ?? new();
                }
                catch {}
            }
            if (string.IsNullOrWhiteSpace(path))
            {
                dict.Remove("custom_core_path");
            }
            else
            {
                dict["custom_core_path"] = path.Trim();
            }
            File.WriteAllText(SettingsFilePath, JsonSerializer.Serialize(dict, new JsonSerializerOptions { WriteIndented = true }));
        }
        catch {}
    }

    /// <summary>
    /// 检测本地当前 main.py / app.py 与版本
    /// </summary>
    public LocalCoreInfo CheckLocalCore()
    {
        var info = new LocalCoreInfo { Exists = false };

        // 1. 优先使用用户手动指定的自定义核心路径 (支持 main.py / app.py 文件或所在根目录)
        var customPath = GetCustomCorePath();
        if (!string.IsNullOrWhiteSpace(customPath))
        {
            if (File.Exists(customPath))
            {
                info.Exists = true;
                info.MainPyPath = Path.GetFullPath(customPath);
                info.RootDirectory = Path.GetDirectoryName(info.MainPyPath) ?? customPath;
                info.Version = ReadVersionFromMainPy(info.MainPyPath);
                return info;
            }
            else if (Directory.Exists(customPath))
            {
                var fullDir = Path.GetFullPath(customPath);
                info.RootDirectory = fullDir;
                var mPy = Path.Combine(fullDir, "main.py");
                var aPy = Path.Combine(fullDir, "app.py");
                var candidate = File.Exists(mPy) ? mPy : (File.Exists(aPy) ? aPy : null);
                if (candidate != null)
                {
                    info.Exists = true;
                    info.MainPyPath = candidate;
                    info.Version = ReadVersionFromMainPy(candidate);
                    return info;
                }
            }
        }

        // 2. 自动启发式探测 (过滤 .net 临时解压目录)
        var candidates = new List<string>();
        if (!string.IsNullOrEmpty(Environment.ProcessPath))
        {
            var pDir = Path.GetDirectoryName(Environment.ProcessPath);
            if (!string.IsNullOrEmpty(pDir) && !pDir.Contains(".net", StringComparison.OrdinalIgnoreCase))
            {
                candidates.Add(pDir);
            }
        }
        if (!AppContext.BaseDirectory.Contains(".net", StringComparison.OrdinalIgnoreCase))
        {
            candidates.Add(AppContext.BaseDirectory);
        }
        candidates.Add(Environment.CurrentDirectory);

        foreach (var startDir in candidates)
        {
            var cur = new DirectoryInfo(startDir);
            for (int i = 0; i < 6 && cur != null; i++)
            {
                var mPy = Path.Combine(cur.FullName, "main.py");
                var aPy = Path.Combine(cur.FullName, "app.py");
                var targetPy = File.Exists(mPy) ? mPy : (File.Exists(aPy) ? aPy : null);
                if (targetPy != null)
                {
                    info.Exists = true;
                    info.MainPyPath = targetPy;
                    info.RootDirectory = cur.FullName;
                    info.Version = ReadVersionFromMainPy(targetPy);
                    return info;
                }
                cur = cur.Parent;
            }
        }

        // 兜底 RootDirectory: 绝不指向 Temp 目录
        if (!string.IsNullOrWhiteSpace(customPath) && Directory.Exists(customPath))
        {
            info.RootDirectory = Path.GetFullPath(customPath);
        }
        else
        {
            info.RootDirectory = Environment.CurrentDirectory;
        }

        return info;
    }

    private string ReadVersionFromMainPy(string mainPyPath)
    {
        try
        {
            var text = File.ReadAllText(mainPyPath);
            var m = Regex.Match(text, @"(?:VERSION|__version__)\s*=\s*[""']([^""']+)[""']");
            if (m.Success)
            {
                return m.Groups[1].Value;
            }
        }
        catch {}
        return "未知";
    }

    /// <summary>
    /// 从 GitHub 获取发布版本列表
    /// </summary>
    public async Task<List<ReleaseItem>> FetchReleasesAsync(string mirrorPrefix = "")
    {
        var list = new List<ReleaseItem>();
        try
        {
            var url = $"https://api.github.com/repos/{RepoOwner}/{RepoName}/releases?per_page=15";
            var json = await _http.GetStringAsync(url);
            using var doc = JsonDocument.Parse(json);
            if (doc.RootElement.ValueKind != JsonValueKind.Array) return list;

            foreach (var elem in doc.RootElement.EnumerateArray())
            {
                var tag = elem.GetProperty("tag_name").GetString() ?? "";
                var name = elem.TryGetProperty("name", out var n) && n.GetString() != null ? n.GetString()! : tag;
                var pubAt = elem.TryGetProperty("published_at", out var p) ? p.GetString() ?? "" : "";
                var body = elem.TryGetProperty("body", out var b) ? b.GetString() ?? "" : "";
                var isPre = elem.TryGetProperty("prerelease", out var pr) && pr.GetBoolean();
                var htmlUrl = elem.TryGetProperty("html_url", out var hu) ? hu.GetString() ?? "" : "";

                string downloadUrl = "";
                string assetName = "";
                long sizeBytes = 0;

                if (elem.TryGetProperty("assets", out var assets) && assets.ValueKind == JsonValueKind.Array)
                {
                    foreach (var a in assets.EnumerateArray())
                    {
                        var aName = a.GetProperty("name").GetString() ?? "";
                        if (aName.EndsWith(".zip", StringComparison.OrdinalIgnoreCase))
                        {
                            assetName = aName;
                            downloadUrl = a.GetProperty("browser_download_url").GetString() ?? "";
                            sizeBytes = a.TryGetProperty("size", out var s) ? s.GetInt64() : 0;
                            break;
                        }
                    }
                }

                if (string.IsNullOrEmpty(downloadUrl) && elem.TryGetProperty("zipball_url", out var zb))
                {
                    downloadUrl = zb.GetString() ?? "";
                    assetName = $"EnderBridge-{tag}.zip";
                }

                if (!string.IsNullOrEmpty(mirrorPrefix) && !string.IsNullOrEmpty(downloadUrl))
                {
                    var prefix = mirrorPrefix.TrimEnd('/') + "/";
                    if (!downloadUrl.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                    {
                        downloadUrl = prefix + downloadUrl;
                    }
                }

                list.Add(new ReleaseItem
                {
                    TagName = tag,
                    Name = name,
                    PublishedAt = pubAt.Length >= 10 ? pubAt.Substring(0, 10) : pubAt,
                    Body = body,
                    HtmlUrl = htmlUrl,
                    IsPrerelease = isPre,
                    AssetName = assetName,
                    DownloadUrl = downloadUrl,
                    SizeBytes = sizeBytes
                });
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[VersionManager] 获取 Releases 失败: {ex.Message}");
        }

        return list;
    }

    /// <summary>
    /// 下载并解压安装指定 Release
    /// </summary>
    public async Task<(bool success, string message)> DownloadAndInstallAsync(
        ReleaseItem release,
        string targetDirectory,
        Action<int, string>? onProgress = null)
    {
        if (string.IsNullOrEmpty(release.DownloadUrl))
        {
            return (false, "该版本未提供有效的下载资源链接。");
        }

        var tempZipPath = Path.Combine(Path.GetTempPath(), $"eb_release_{Guid.NewGuid():N}.zip");
        try
        {
            onProgress?.Invoke(10, $"正在连接下载源 ({release.AssetName})...");

            using (var response = await _http.GetAsync(release.DownloadUrl, HttpCompletionOption.ResponseHeadersRead))
            {
                response.EnsureSuccessStatusCode();
                var totalBytes = response.Content.Headers.ContentLength ?? (release.SizeBytes > 0 ? release.SizeBytes : -1L);

                using (var contentStream = await response.Content.ReadAsStreamAsync())
                using (var fileStream = new FileStream(tempZipPath, FileMode.Create, FileAccess.Write, FileShare.None))
                {
                    var buffer = new byte[81920];
                    long totalRead = 0;
                    int read;
                    while ((read = await contentStream.ReadAsync(buffer, 0, buffer.Length)) > 0)
                    {
                        await fileStream.WriteAsync(buffer, 0, read);
                        totalRead += read;
                        if (totalBytes > 0)
                        {
                            int pct = 10 + (int)((totalRead * 70) / totalBytes);
                            onProgress?.Invoke(pct, $"正在下载: {totalRead / 1024 / 1024.0:F2} MB / {totalBytes / 1024 / 1024.0:F2} MB ({pct}%)");
                        }
                        else
                        {
                            onProgress?.Invoke(50, $"已下载: {totalRead / 1024 / 1024.0:F2} MB");
                        }
                    }
                }
            }

            onProgress?.Invoke(85, "下载完成，正在解压并部署文件...");

            if (!Directory.Exists(targetDirectory))
            {
                Directory.CreateDirectory(targetDirectory);
            }

            using (var archive = ZipFile.OpenRead(tempZipPath))
            {
                // 检测是否包含顶层单一包装目录 (例如 GitHub zipball)
                string? commonPrefix = null;
                bool first = true;
                foreach (var entry in archive.Entries)
                {
                    if (string.IsNullOrEmpty(entry.Name)) continue;
                    var parts = entry.FullName.Split(new[] { '/', '\\' }, StringSplitOptions.RemoveEmptyEntries);
                    if (parts.Length > 1)
                    {
                        var topDir = parts[0];
                        if (first) { commonPrefix = topDir; first = false; }
                        else if (commonPrefix != topDir) { commonPrefix = null; break; }
                    }
                    else
                    {
                        commonPrefix = null;
                        break;
                    }
                }

                // 加载并编译 .noneeds 规则（压缩包内、目标目录或内置核心过滤规则）
                var noneedsLines = LoadNoneedsRules(archive, commonPrefix, targetDirectory);
                var compiledRules = CompileNoneedsRules(noneedsLines);

                int count = 0;
                int skippedCount = 0;
                int totalEntries = archive.Entries.Count;

                foreach (var entry in archive.Entries)
                {
                    var relPath = entry.FullName;
                    if (!string.IsNullOrEmpty(commonPrefix) && relPath.StartsWith(commonPrefix + "/"))
                    {
                        relPath = relPath.Substring(commonPrefix.Length + 1);
                    }

                    if (string.IsNullOrEmpty(relPath)) continue;

                    bool isDir = string.IsNullOrEmpty(entry.Name) || relPath.EndsWith("/") || relPath.EndsWith("\\");
                    if (IsNoneedPath(relPath, isDir, compiledRules))
                    {
                        skippedCount++;
                        continue;
                    }

                    var destPath = Path.Combine(targetDirectory, relPath.Replace('/', Path.DirectorySeparatorChar));

                    if (isDir)
                    {
                        // 目录
                        Directory.CreateDirectory(destPath);
                    }
                    else
                    {
                        var pDir = Path.GetDirectoryName(destPath);
                        if (!string.IsNullOrEmpty(pDir)) Directory.CreateDirectory(pDir);
                        entry.ExtractToFile(destPath, overwrite: true);
                    }

                    count++;
                }

                // 解压完成后，执行二次扫描清理目标目录中的历史冗余文件 (如旧版本遗留的 LICENSE、tests、wiki 等)
                CleanTargetDirectoryNoneeds(targetDirectory, compiledRules);
            }

            onProgress?.Invoke(100, $"部署完成！已成功解压并部署 {release.TagName} 核心文件。");
            return (true, $"已成功安装 EnderBridge {release.TagName}！");
        }
        catch (Exception ex)
        {
            return (false, $"安装失败: {ex.Message}");
        }
        finally
        {
            try
            {
                if (File.Exists(tempZipPath)) File.Delete(tempZipPath);
            }
            catch {}
        }
    }

    private static readonly string[] DefaultNoneedsPatterns = new[]
    {
        "wiki/",
        "tests/",
        ".github/",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "LICENSE*",
        "security_audit.py",
        "/security_audit.py",
        "importtime.log",
        "app_error.log",
        "*.log",
        "*.WebView2/",
        "*.WebView2",
        "EnderBridge.exe.WebView2/",
        "dist/",
        "build/",
        ".pytest_cache/",
        "app/**/bin/",
        "app/**/obj/",
        "app/**/publish/",
        "app/**/TestResults/",
        "app/**/packages/",
        "app/**/Generated Files/",
        "app/**/AppBundle/",
        "app/**/.vs/",
        "app/**/.idea/",
        "app/**/.vscode/",
        "app/**/*.user",
        "app/**/*.userosscache",
        "app/**/*.suo",
        "app/**/*.sln.docstates",
        "app/**/*.DotSettings.user",
        "app/**/_ReSharper*/"
    };

    private static readonly HashSet<string> ProtectedFilesAndDirs = new(StringComparer.OrdinalIgnoreCase)
    {
        "",
        ".",
        "main.py",
        ".noneeds",
        ".exportignore",
        ".gitignore",
        "config",
        "config/config.json",
        "config/config.example.json",
        "lib",
        "core",
        "version_manager",
        "requirements.txt",
        "app"
    };

    private static List<string> LoadNoneedsRules(ZipArchive archive, string? commonPrefix, string targetDirectory)
    {
        var lines = new List<string>();

        // 1. 优先尝试从待解压的压缩包中读取 .noneeds
        try
        {
            ZipArchiveEntry? noneedsEntry = null;
            foreach (var entry in archive.Entries)
            {
                var rel = entry.FullName;
                if (!string.IsNullOrEmpty(commonPrefix) && rel.StartsWith(commonPrefix + "/"))
                {
                    rel = rel.Substring(commonPrefix.Length + 1);
                }
                if (string.Equals(rel, ".noneeds", StringComparison.OrdinalIgnoreCase))
                {
                    noneedsEntry = entry;
                    break;
                }
            }

            if (noneedsEntry != null)
            {
                using var reader = new StreamReader(noneedsEntry.Open(), System.Text.Encoding.UTF8);
                string? l;
                while ((l = reader.ReadLine()) != null)
                {
                    lines.Add(l);
                }
            }
        }
        catch {}

        // 2. 若压缩包未包含，尝试从目标目录读取现存的 .noneeds
        if (lines.Count == 0 && !string.IsNullOrEmpty(targetDirectory))
        {
            try
            {
                var localNoneeds = Path.Combine(targetDirectory, ".noneeds");
                if (File.Exists(localNoneeds))
                {
                    lines.AddRange(File.ReadAllLines(localNoneeds));
                }
            }
            catch {}
        }

        // 3. 始终合并内置默认的 noneeds 规则，确保即便配置缺失也能过滤 LICENSE、tests 等无用文件
        var ruleSet = new HashSet<string>(lines, StringComparer.OrdinalIgnoreCase);
        foreach (var def in DefaultNoneedsPatterns)
        {
            if (!ruleSet.Contains(def))
            {
                lines.Add(def);
            }
        }

        return lines;
    }

    private static List<(bool isNegated, Regex regex)> CompileNoneedsRules(IEnumerable<string> rawLines)
    {
        var rules = new List<(bool isNegated, Regex regex)>();
        foreach (var raw in rawLines)
        {
            var line = raw.Trim();
            if (string.IsNullOrWhiteSpace(line) || line.StartsWith("#")) continue;

            bool isNegated = false;
            if (line.StartsWith("!"))
            {
                isNegated = true;
                line = line.Substring(1).Trim();
                if (string.IsNullOrEmpty(line)) continue;
            }

            var rx = GitignorePatternToRegex(line);
            if (rx != null)
            {
                rules.Add((isNegated, rx));
            }
        }
        return rules;
    }

    private static Regex? GitignorePatternToRegex(string pattern)
    {
        try
        {
            pattern = pattern.Replace('\\', '/');
            bool anchored = false;
            if (pattern.StartsWith("/"))
            {
                anchored = true;
                pattern = pattern.Substring(1);
            }
            else if (pattern.TrimEnd('/').Contains('/'))
            {
                anchored = true;
            }

            bool dirOnly = pattern.EndsWith("/");
            if (dirOnly)
            {
                pattern = pattern.TrimEnd('/');
            }

            var sb = new System.Text.StringBuilder();
            int i = 0;
            int n = pattern.Length;
            while (i < n)
            {
                char c = pattern[i];
                if (c == '*')
                {
                    if (i + 1 < n && pattern[i + 1] == '*')
                    {
                        i += 2;
                        if (i < n && pattern[i] == '/')
                        {
                            i++;
                            sb.Append("(?:.+/)?");
                        }
                        else
                        {
                            sb.Append(".*");
                        }
                    }
                    else
                    {
                        i++;
                        sb.Append("[^/]*");
                    }
                }
                else if (c == '?')
                {
                    i++;
                    sb.Append("[^/]");
                }
                else if ("\\.+^$()[]{}|".Contains(c))
                {
                    sb.Append('\\').Append(c);
                    i++;
                }
                else if (c == '/')
                {
                    sb.Append('/');
                    i++;
                }
                else
                {
                    sb.Append(c);
                    i++;
                }
            }

            string patternRe = sb.ToString();
            string regexStr;
            if (dirOnly)
            {
                regexStr = anchored
                    ? $"^(?:{patternRe})/(?:.*)?$"
                    : $"(?:^|/)(?:{patternRe})/(?:.*)?$";
            }
            else
            {
                regexStr = anchored
                    ? $"^(?:{patternRe})(?:/.*)?$"
                    : $"(?:^|/)(?:{patternRe})(?:/.*)?$";
            }

            return new Regex(regexStr, RegexOptions.IgnoreCase | RegexOptions.Compiled);
        }
        catch
        {
            return null;
        }
    }

    private static bool IsNoneedPath(string relPath, bool isDir, List<(bool isNegated, Regex regex)> rules)
    {
        var norm = relPath.Replace('\\', '/').Trim('/');
        if (string.IsNullOrEmpty(norm)) return false;

        // 核心关键项绝对保护，严禁过滤
        if (ProtectedFilesAndDirs.Contains(norm)) return false;
        var topDir = norm.Split('/')[0];
        if (ProtectedFilesAndDirs.Contains(topDir) && topDir != "app")
        {
            return false;
        }

        string target = isDir && !norm.EndsWith("/") ? norm + "/" : norm;

        bool ignored = false;
        foreach (var (isNegated, rx) in rules)
        {
            if (rx.IsMatch(target))
            {
                ignored = !isNegated;
            }
        }
        return ignored;
    }

    private static void CleanTargetDirectoryNoneeds(string targetDirectory, List<(bool isNegated, Regex regex)> rules)
    {
        try
        {
            if (!Directory.Exists(targetDirectory)) return;

            var dirInfo = new DirectoryInfo(targetDirectory);
            CleanDirectoryRecursive(dirInfo, targetDirectory, rules);
        }
        catch {}
    }

    private static void CleanDirectoryRecursive(DirectoryInfo currentDir, string rootDir, List<(bool isNegated, Regex regex)> rules)
    {
        DirectoryInfo[] subDirs;
        try
        {
            subDirs = currentDir.GetDirectories();
        }
        catch
        {
            return;
        }

        foreach (var sub in subDirs)
        {
            var relPath = Path.GetRelativePath(rootDir, sub.FullName).Replace('\\', '/').Trim('/');
            if (IsNoneedPath(relPath, isDir: true, rules))
            {
                try
                {
                    sub.Delete(recursive: true);
                }
                catch {}
                continue;
            }

            CleanDirectoryRecursive(sub, rootDir, rules);
        }

        FileInfo[] files;
        try
        {
            files = currentDir.GetFiles();
        }
        catch
        {
            return;
        }

        foreach (var file in files)
        {
            var relPath = Path.GetRelativePath(rootDir, file.FullName).Replace('\\', '/').Trim('/');
            if (IsNoneedPath(relPath, isDir: false, rules))
            {
                try
                {
                    file.Delete();
                }
                catch {}
            }
        }
    }
}
