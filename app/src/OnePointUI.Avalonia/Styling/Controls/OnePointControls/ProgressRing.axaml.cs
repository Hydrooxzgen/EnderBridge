using Avalonia;
using Avalonia.Controls.Primitives;

namespace OnePointUI.Avalonia.Styling.Controls.OnePointControls;

public class ProgressRing : TemplatedControl
{
    public static readonly StyledProperty<int> RingWidthProperty =
        AvaloniaProperty.Register<ProgressRing, int>(nameof(RingWidth), 5);

    public int RingWidth
    {
        get => GetValue(RingWidthProperty);
        set => SetValue(RingWidthProperty, value);
    }
}