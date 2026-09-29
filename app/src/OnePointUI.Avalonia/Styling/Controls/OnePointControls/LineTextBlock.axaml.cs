using Avalonia;
using Avalonia.Controls.Primitives;

namespace OnePointUI.Avalonia.Styling.Controls.OnePointControls;

public class LineTextBlock : TemplatedControl
{
    // 定义 FontSize 依赖属性（如果尚未定义，通常继承自父类）
    // Avalonia 的 TemplatedControl 已经自带了 FontSize 等属性，这里无需重复定义，除非有特殊行为

    public static readonly StyledProperty<string> TextProperty =
        AvaloniaProperty.Register<LineTextBlock, string>(nameof(Text), string.Empty);

    public double LineHeight
    {
        get => GetValue(FontSizeProperty) + GetValue(FontSizeProperty) / 4;
        set => SetValue(FontSizeProperty, value);
    }

    public string Text
    {
        get => GetValue(TextProperty);
        set => SetValue(TextProperty, value);
    }
}