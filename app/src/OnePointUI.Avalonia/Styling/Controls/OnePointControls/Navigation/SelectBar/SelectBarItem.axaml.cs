// Author: Hydrooxzgen
// Github: https://github.com/Hydrooxzgen
// This project uses the GPL-3.0 license, you can modify/distribute this project according to the GPL-3.0 license
using Avalonia;
using Avalonia.Controls;

namespace OnePointUI.Avalonia.Styling.Controls.OnePointControls.Navigation.SelectBar;

public class SelectBarItem : ListBoxItem
{
    public static readonly StyledProperty<string> GlyphProperty =
        AvaloniaProperty.Register<SelectBarItem, string>(nameof(Glyph), "");


    public static readonly StyledProperty<string> ItemTextProperty =
        AvaloniaProperty.Register<SelectBarItem, string>(nameof(ItemText), "Item");

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
}