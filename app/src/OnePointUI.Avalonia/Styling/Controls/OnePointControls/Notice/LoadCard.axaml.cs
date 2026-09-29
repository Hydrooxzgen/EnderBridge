using Avalonia;
using Avalonia.Controls.Primitives;

namespace OnePointUI.Avalonia.Styling.Controls.OnePointControls.Notice;

public class LoadCard : TemplatedControl
{
    public static readonly StyledProperty<string> BigTitleProperty =
        AvaloniaProperty.Register<LoadCard, string>(nameof(BigTitle), "正在加载中...");

    public static readonly StyledProperty<string> MessageProperty =
        AvaloniaProperty.Register<LoadCard, string>(nameof(Message), "Message");

    public string BigTitle
    {
        get => GetValue(BigTitleProperty);
        set => SetValue(BigTitleProperty, value);
    }

    public string Message
    {
        get => GetValue(MessageProperty);
        set => SetValue(MessageProperty, value);
    }
}