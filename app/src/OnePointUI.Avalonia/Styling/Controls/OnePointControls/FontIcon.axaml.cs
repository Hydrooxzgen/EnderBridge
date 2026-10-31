// Author: Hydrooxzgen
// Github: https://github.com/Hydrooxzgen
// This project uses the GPL-3.0 license, you can modify/distribute this project according to the GPL-3.0 license
using Avalonia;
using Avalonia.Controls.Primitives;

namespace OnePointUI.Avalonia.Styling.Controls.OnePointControls;

public class FontIcon : TemplatedControl
{
    public static readonly StyledProperty<string> GlyphProperty =
        AvaloniaProperty.Register<FontIcon, string>(nameof(Glyph), "");

    public string Glyph
    {
        get => GetValue(GlyphProperty);
        set => SetValue(GlyphProperty, value);
    }
}