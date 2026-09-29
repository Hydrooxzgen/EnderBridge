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

    /// <summary>
    /// 检测本地当前 main.py 与版本
    /// </summary>
    public LocalCoreInfo CheckLocalCore()
    {
        var info = new LocalCoreInfo { Exists = false };

        var candidates = new List<string>();
        if (!string.IsNullOrEmpty(Environment.ProcessPath))
        {
            var pDir = Path.GetDirectoryName(Environment.ProcessPath);
            if (!string.IsNullOrEmpty(pDir)) candidates.Add(pDir);
        }
        candidates.Add(AppContext.BaseDirectory);
        candidates.Add(Environment.CurrentDirectory);

        foreach (var startDir in candidates)
        {
            var cur = new DirectoryInfo(startDir);
            for (int i = 0; i < 6 && cur != null; i++)
            {
                var mainPy = Path.Combine(cur.FullName, "main.py");
                if (File.Exists(mainPy))
                {
                    info.Exists = true;
                    info.MainPyPath = mainPy;
                    info.RootDirectory = cur.FullName;
                    info.Version = ReadVersionFromMainPy(mainPy);
                    return info;
                }
                cur = cur.Parent;
            }
        }

        return info;
    }

    private string ReadVersionFromMainPy(string mainPyPath)
    {
        try
        {
            var text = File.ReadAllText(mainPyPath);
            var m = Regex.Match(text, @"VERSION\s*=\s*[""']([^""']+)[""']");
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

                int count = 0;
                int totalEntries = archive.Entries.Count;

                foreach (var entry in archive.Entries)
                {
                    var relPath = entry.FullName;
                    if (!string.IsNullOrEmpty(commonPrefix) && relPath.StartsWith(commonPrefix + "/"))
                    {
                        relPath = relPath.Substring(commonPrefix.Length + 1);
                    }

                    if (string.IsNullOrEmpty(relPath)) continue;

                    var destPath = Path.Combine(targetDirectory, relPath.Replace('/', Path.DirectorySeparatorChar));

                    if (string.IsNullOrEmpty(entry.Name))
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
}
