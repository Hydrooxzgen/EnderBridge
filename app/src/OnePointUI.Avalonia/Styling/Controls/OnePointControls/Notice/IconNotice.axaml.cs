// Author: Hydrooxzgen
// Github: https://github.com/Hydrooxzgen
// This project uses the GPL-3.0 license, you can modify/distribute this project according to the GPL-3.0 license
using Avalonia;
using Avalonia.Controls.Primitives;

namespace OnePointUI.Avalonia.Styling.Controls.OnePointControls.Notice;

public class IconNotice : TemplatedControl
{
    public static readonly StyledProperty<string> GlyphProperty =
        AvaloniaProperty.Register<IconNotice, string>(nameof(Glyph), "\uF133");

    public static readonly StyledProperty<string> MessageProperty =
        AvaloniaProperty.Register<IconNotice, string>(nameof(Message), "~CuO~");

    public string Glyph
    {
        get => GetValue(GlyphProperty);
        set => SetValue(GlyphProperty, value);
    }

    public string Message
    {
        get => GetValue(MessageProperty);
        set => SetValue(MessageProperty, value);
    }
}