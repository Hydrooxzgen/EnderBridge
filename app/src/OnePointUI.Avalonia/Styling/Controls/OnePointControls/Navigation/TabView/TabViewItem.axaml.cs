using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.VisualTree;

namespace OnePointUI.Avalonia.Styling.Controls.OnePointControls.Navigation.TabView;

public class TabViewItem : TabItem
{
    public static readonly StyledProperty<string> GlyphProperty =
        AvaloniaProperty.Register<TabViewItem, string>(nameof(Glyph), string.Empty);

    public static readonly StyledProperty<bool> HasGlyphProperty =
        AvaloniaProperty.Register<TabViewItem, bool>(nameof(HasGlyph));

    public static readonly StyledProperty<bool> IsClosableProperty =
        AvaloniaProperty.Register<TabViewItem, bool>(nameof(IsClosable), true);

    public static readonly StyledProperty<bool> CanDragProperty =
        AvaloniaProperty.Register<TabViewItem, bool>(nameof(CanDrag), true);

    public static readonly RoutedEvent<RoutedEventArgs> CloseRequestedEvent =
        RoutedEvent.Register<TabViewItem, RoutedEventArgs>(nameof(CloseRequested), RoutingStrategies.Bubble);

    private Button? _closeButton;
    private Point _pressPos;
    private bool _pressed;
    private bool _dragging;

    public string Glyph
    {
        get => GetValue(GlyphProperty);
        set => SetValue(GlyphProperty, value);
    }

    public bool HasGlyph
    {
        get => GetValue(HasGlyphProperty);
        private set => SetValue(HasGlyphProperty, value);
    }

    public bool IsClosable
    {
        get => GetValue(IsClosableProperty);
        set => SetValue(IsClosableProperty, value);
    }

    public bool CanDrag
    {
        get => GetValue(CanDragProperty);
        set => SetValue(CanDragProperty, value);
    }

    public event EventHandler<RoutedEventArgs>? CloseRequested
    {
        add => AddHandler(CloseRequestedEvent, value);
        remove => RemoveHandler(CloseRequestedEvent, value);
    }

    protected override void OnApplyTemplate(TemplateAppliedEventArgs e)
    {
        base.OnApplyTemplate(e);

        if (_closeButton != null)
            _closeButton.Click -= OnCloseClick;

        _closeButton = e.NameScope.Find<Button>("PART_CloseButton");
        if (_closeButton != null)
        {
            _closeButton.Click += OnCloseClick;
            _closeButton.PointerPressed += (_, args) => args.Handled = true;
        }

        UpdateHasGlyph();
    }

    protected override void OnPropertyChanged(AvaloniaPropertyChangedEventArgs change)
    {
        base.OnPropertyChanged(change);
        if (change.Property == GlyphProperty)
            UpdateHasGlyph();
    }

    protected override void OnPointerPressed(PointerPressedEventArgs e)
    {
        base.OnPointerPressed(e);

        if (!e.GetCurrentPoint(this).Properties.IsLeftButtonPressed)
            return;
        if (IsCloseSource(e.Source))
            return;

        _pressPos = e.GetPosition(this);
        _pressed = true;
        _dragging = false;
        e.Pointer.Capture(this);
    }

    protected override void OnPointerMoved(PointerEventArgs e)
    {
        base.OnPointerMoved(e);

        if (!_pressed || e.Pointer.Captured != this)
            return;

        var delta = e.GetPosition(this) - _pressPos;
        if (!_dragging && Math.Sqrt(delta.X * delta.X + delta.Y * delta.Y) >= 8)
        {
            var owner = TabView.GetOwner(this);
            if (owner is not { CanUserDragTabs: true } || !CanDrag)
                return;

            _dragging = true;
            TabViewDragManager.Begin(this, e);
        }
        else if (_dragging)
        {
            TabViewDragManager.Move(e);
        }
    }

    protected override void OnPointerReleased(PointerReleasedEventArgs e)
    {
        base.OnPointerReleased(e);

        if (_dragging)
            TabViewDragManager.End(e);

        _pressed = false;
        _dragging = false;
        if (e.Pointer.Captured == this)
            e.Pointer.Capture(null);
    }

    protected override void OnPointerCaptureLost(PointerCaptureLostEventArgs e)
    {
        base.OnPointerCaptureLost(e);

        if (_dragging)
            TabViewDragManager.Cancel();

        _pressed = false;
        _dragging = false;
    }

    public void RequestClose()
    {
        if (!IsClosable)
            return;

        RaiseEvent(new RoutedEventArgs(CloseRequestedEvent));
    }

    private void OnCloseClick(object? sender, RoutedEventArgs e)
    {
        e.Handled = true;
        RequestClose();
    }

    private void UpdateHasGlyph()
    {
        HasGlyph = !string.IsNullOrWhiteSpace(Glyph);
    }

    private bool IsCloseSource(object? source)
    {
        if (_closeButton == null || source is not Visual visual)
            return false;

        return ReferenceEquals(visual, _closeButton) || _closeButton.IsVisualAncestorOf(visual);
    }
}
