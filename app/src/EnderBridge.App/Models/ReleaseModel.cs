using System;

namespace EnderBridge.App.Models;

public class LocalCoreInfo
{
    public bool Exists { get; set; }
    public string? MainPyPath { get; set; }
    public string? RootDirectory { get; set; }
    public string Version { get; set; } = "未知";
    public string StatusDescription => Exists ? $"已就绪: {Version} ({MainPyPath})" : "未检测到核心文件 main.py";
}

public class ReleaseItem
{
    public string TagName { get; set; } = "";
    public string Name { get; set; } = "";
    public string PublishedAt { get; set; } = "";
    public string Body { get; set; } = "";
    public string HtmlUrl { get; set; } = "";
    public bool IsPrerelease { get; set; }
    public string AssetName { get; set; } = "";
    public string DownloadUrl { get; set; } = "";
    public long SizeBytes { get; set; }
    public string SizeFormatted => SizeBytes > 0 ? $"{SizeBytes / 1024.0 / 1024.0:F2} MB" : "";
}
