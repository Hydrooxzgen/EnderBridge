// Author: Hydrooxzgen
// Github: https://github.com/Hydrooxzgen
// This project uses the GPL-3.0 license, you can modify/distribute this project according to the GPL-3.0 license
namespace OnePointUI.Avalonia.Base.Entry;

public class NoticeInfo
{
    public string Title { get; set; } = "Info";
    public string Message { get; set; } = "Message";
    public NoticeType NoticeType { get; set; } = NoticeType.Info;
}

public enum NoticeType
{
    Info,
    Warning,
    Error,
    Success
}