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