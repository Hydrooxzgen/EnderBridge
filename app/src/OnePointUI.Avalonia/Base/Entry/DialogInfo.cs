using OnePointUI.Avalonia.Base.Enum;

namespace OnePointUI.Avalonia.Base.Entry;

public class DialogInfo
{
    public string? Title { get; set; }
    public object? Content { get; set; }
    public string? PrimaryButtonText { get; set; }
    public string? SecondaryButtonText { get; set; }
    public string? CloseButtonText { get; set; }
    public Action? CloseAction { get; set; }
    public Action? PrimaryAction { get; set; }
    public Action? SecondaryAction { get; set; }
    public DialogButtons AccountButton { get; set; } = DialogButtons.CloseButton;
    public bool IsWindow { get; set; } = false;
}