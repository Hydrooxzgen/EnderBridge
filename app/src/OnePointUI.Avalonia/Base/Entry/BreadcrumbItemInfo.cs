namespace OnePointUI.Avalonia.Base.Entry;

public class BreadcrumbItemInfo
{
    public string ItemName { get; set; }
    public Action<BreadcrumbItemInfo> ItemClickAction { get; set; } = null;
}