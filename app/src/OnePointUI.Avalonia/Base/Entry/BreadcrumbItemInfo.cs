// Author: Hydrooxzgen
// Github: https://github.com/Hydrooxzgen
// This project uses the GPL-3.0 license, you can modify/distribute this project according to the GPL-3.0 license
namespace OnePointUI.Avalonia.Base.Entry;

public class BreadcrumbItemInfo
{
    public string ItemName { get; set; }
    public Action<BreadcrumbItemInfo> ItemClickAction { get; set; } = null;
}