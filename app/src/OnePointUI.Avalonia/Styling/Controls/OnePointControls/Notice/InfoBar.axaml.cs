using Avalonia;
using Avalonia.Controls.Primitives;
using Avalonia.Media;

namespace OnePointUI.Avalonia.Styling.Controls.OnePointControls.Notice;

public class InfoBar : TemplatedControl
{
    public enum InfoBarType
    {
        Error,
        Warning,
        Info,
        Success
    }

    public static readonly StyledProperty<string> GlyphProperty =
        AvaloniaProperty.Register<InfoBar, string>(nameof(Glyph), "");

    public static readonly StyledProperty<string> TitleProperty =
        AvaloniaProperty.Register<InfoBar, string>(nameof(Title), "Title");

    public static readonly StyledProperty<string> MessageProperty =
        AvaloniaProperty.Register<InfoBar, string>(nameof(Message), "Message");

    public static readonly StyledProperty<InfoBarType> StateProperty =
        AvaloniaProperty.Register<InfoBar, InfoBarType>(nameof(State), InfoBarType.Info);

    public static readonly StyledProperty<IBrush> BackcolorProperty =
        AvaloniaProperty.Register<InfoBar, IBrush>(nameof(Backcolor));

    public static readonly StyledProperty<IBrush> IconColorProperty =
        AvaloniaProperty.Register<InfoBar, IBrush>(nameof(IconColor));

    public string Glyph
    {
        get => GetValue(GlyphProperty);
        set => SetValue(GlyphProperty, value);
    }

    public string Title
    {
        get => GetValue(TitleProperty);
        set => SetValue(TitleProperty, value);
    }

    public string Message
    {
        get => GetValue(MessageProperty);
        set => SetValue(MessageProperty, value);
    }

    public InfoBarType State
    {
        get => GetValue(StateProperty);
        set
        {
            SetValue(StateProperty, value);
            SetValue(BackcolorProperty, GetColor());
            SetValue(GlyphProperty, GetGlyph());
            SetValue(IconColorProperty, GetIconColor());
        }
    }

    public IBrush Backcolor
    {
        get => GetValue(BackcolorProperty);
        set => SetValue(BackcolorProperty, value); // 即使内部不存储，也需要setter
    }

    public IBrush IconColor
    {
        get => GetValue(IconColorProperty);
        set => SetValue(IconColorProperty, value); // 即使内部不存储，也需要setter
    }

    public IBrush GetIconColor()
    {
        return State switch
        {
            InfoBarType.Error => Brush.Parse("#FF99A4"),
            InfoBarType.Warning => Brush.Parse("#FCE100"),
            InfoBarType.Info => Brush.Parse("#0F64A3"),
            InfoBarType.Success => Brush.Parse("#6CCB5F")
        };
    }

    public IBrush GetColor()
    {
        return State switch
        {
            InfoBarType.Error => Brushes.DarkRed,
            InfoBarType.Warning => Brushes.DarkGoldenrod,
            InfoBarType.Info => Brushes.Transparent,
            InfoBarType.Success => Brushes.Green
        };
    }

    public string GetGlyph()
    {
        return State switch
        {
            InfoBarType.Error => "\uEB90",
            InfoBarType.Warning => "\uE814",
            InfoBarType.Info => "\uF167",
            InfoBarType.Success => "\uEC61"
        };
    }
}