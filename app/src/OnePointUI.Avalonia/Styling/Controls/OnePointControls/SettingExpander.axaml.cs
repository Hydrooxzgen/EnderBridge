using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;

namespace OnePointUI.Avalonia.Styling.Controls.OnePointControls;

public class SettingExpander : Expander
{
    public static readonly StyledProperty<string> GlyphProperty =
        AvaloniaProperty.Register<SettingExpander, string>(nameof(Glyph), "");

    public static readonly StyledProperty<object> HeaderProperty =
        AvaloniaProperty.Register<SettingExpander, object>(nameof(Header));

    public static readonly StyledProperty<object> DescriptionProperty =
        AvaloniaProperty.Register<SettingExpander, object>(nameof(Description));

    public static readonly StyledProperty<bool> IsFontIconProperty =
        AvaloniaProperty.Register<SettingExpander, bool>(nameof(IsFontIcon), true);

    public static readonly StyledProperty<bool> IsNotFontIconProperty =
        AvaloniaProperty.Register<SettingExpander, bool>(nameof(IsNotFontIcon));

    public static readonly StyledProperty<IImage> ImageIconProperty =
        AvaloniaProperty.Register<SettingExpander, IImage>(nameof(ImageIcon));

    public static readonly StyledProperty<object> ItemContentProperty =
        AvaloniaProperty.Register<SettingExpander, object>(nameof(ItemContent));

    public object ItemContent
    {
        get => GetValue(ItemContentProperty);
        set => SetValue(ItemContentProperty, value);
    }

    public string Glyph
    {
        get => GetValue(GlyphProperty);
        set => SetValue(GlyphProperty, value);
    }

    public object Header
    {
        get => GetValue(HeaderProperty);
        set => SetValue(HeaderProperty, value);
    }

    public object Description
    {
        get => GetValue(DescriptionProperty);
        set => SetValue(DescriptionProperty, value);
    }

    public bool IsFontIcon
    {
        get => GetValue(IsFontIconProperty);
        set
        {
            SetValue(IsFontIconProperty, value);
            // 当 IsFontIcon 改变时，自动更新 IsNotFontIcon
            SetValue(IsNotFontIconProperty, !value);
        }
    }

    public bool IsNotFontIcon
    {
        get => GetValue(IsNotFontIconProperty);
        set => SetValue(IsNotFontIconProperty, value);
    }

    public IImage ImageIcon
    {
        get => GetValue(ImageIconProperty);
        set => SetValue(ImageIconProperty, value);
    }

    // 重写属性改变通知方法
    protected override void OnPropertyChanged(AvaloniaPropertyChangedEventArgs change)
    {
        base.OnPropertyChanged(change);

        // 当 IsFontIcon 属性改变时，自动更新 IsNotFontIcon
        if (change.Property == IsFontIconProperty) SetValue(IsNotFontIconProperty, !(bool)change.NewValue!);
    }
}