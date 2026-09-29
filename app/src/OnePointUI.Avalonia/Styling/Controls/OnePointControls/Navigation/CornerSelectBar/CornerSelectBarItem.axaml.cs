using Avalonia;
using Avalonia.Controls;

namespace OnePointUI.Avalonia.Styling.Controls.OnePointControls.Navigation.CornerSelectBar;

public class CornerSelectBarItem : ListBoxItem
{
    public static readonly StyledProperty<string> GlyphProperty =
        AvaloniaProperty.Register<CornerSelectBarItem, string>(nameof(Glyph), "");


    public static readonly StyledProperty<string> ItemTextProperty =
        AvaloniaProperty.Register<CornerSelectBarItem, string>(nameof(ItemText), "Item");


    public static readonly StyledProperty<double> OpenWidthProperty =
        AvaloniaProperty.Register<CornerSelectBarItem, double>(nameof(ItemText));

    public string Glyph
    {
        get => GetValue(GlyphProperty);
        set => SetValue(GlyphProperty, value);
    }

    public string ItemText
    {
        get => GetValue(ItemTextProperty);
        set => SetValue(ItemTextProperty, value);
    }

    public double OpenWidth
    {
        get => GetValue(OpenWidthProperty);
        set => SetValue(OpenWidthProperty, value);
    }
}