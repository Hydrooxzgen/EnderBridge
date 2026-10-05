using Avalonia;
using Avalonia.Controls.Primitives;
using Avalonia.Media;

namespace OnePointUI.Avalonia.Styling.Controls.OnePointControls.Items;

public class CardCheckBox : TemplatedControl
{
    public static readonly StyledProperty<string> HeaderProperty =
        AvaloniaProperty.Register<CardCheckBox, string>(nameof(Header));

    public static readonly StyledProperty<string> DescriptionProperty =
        AvaloniaProperty.Register<CardCheckBox, string>(nameof(Description));

    public static readonly StyledProperty<string> InfoProperty =
        AvaloniaProperty.Register<CardCheckBox, string>(nameof(Info));

    public static readonly StyledProperty<IImage> ImageIconProperty =
        AvaloniaProperty.Register<CardCheckBox, IImage>(nameof(ImageIcon));

    public static readonly StyledProperty<bool> IsCheckedProperty =
        AvaloniaProperty.Register<CardCheckBox, bool>(nameof(IsChecked));

    public string Header
    {
        get => GetValue(HeaderProperty);
        set => SetValue(HeaderProperty, value);
    }

    public string Description
    {
        get => GetValue(DescriptionProperty);
        set => SetValue(DescriptionProperty, value);
    }

    public bool IsChecked
    {
        get => GetValue(IsCheckedProperty);
        set => SetValue(IsCheckedProperty, value);
    }

    public string Info
    {
        get => GetValue(InfoProperty);
        set => SetValue(InfoProperty, value);
    }

    public IImage ImageIcon
    {
        get => GetValue(ImageIconProperty);
        set => SetValue(ImageIconProperty, value);
    }
}