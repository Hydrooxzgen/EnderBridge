using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Media;

namespace OnePointUI.Avalonia.Styling.Controls.OnePointControls.Navigation.TabView;

internal static class TabViewDragManager
{
    private static readonly List<TabView> Views = [];
    private static TabViewItem? _item;
    private static TabView? _source;
    private static Window? _ghost;
    private static Point _offset;
    private static TabView? _lastTarget;

    public static void Register(TabView view)
    {
        if (!Views.Contains(view))
            Views.Add(view);
    }

    public static void Unregister(TabView view)
    {
        Views.Remove(view);
        if (ReferenceEquals(_lastTarget, view))
            _lastTarget = null;
        if (ReferenceEquals(_source, view))
            Cancel();
    }

    public static void Begin(TabViewItem item, PointerEventArgs e)
    {
        Cancel();

        var owner = TabView.GetOwner(item);
        if (owner is not { CanUserDragTabs: true })
            return;

        _item = item;
        _source = owner;
        _offset = e.GetPosition(item);
        item.Opacity = 0.35;
        _ghost = CreateGhost(item);
        MoveGhost(item.PointToScreen(new Point(0, 0)));
        _ghost.Show();
    }

    public static void Move(PointerEventArgs e)
    {
        if (_item == null || _ghost == null)
            return;

        var screen = e.GetPosition(_item) is var local
            ? _item.PointToScreen(local)
            : default;
        MoveGhost(new PixelPoint(
            screen.X - (int)(_offset.X * (_ghost.RenderScaling <= 0 ? 1 : _ghost.RenderScaling)),
            screen.Y - (int)(_offset.Y * (_ghost.RenderScaling <= 0 ? 1 : _ghost.RenderScaling))));

        var target = HitTest(screen, out var index);
        if (!ReferenceEquals(_lastTarget, target))
            _lastTarget?.HideDropIndicator();

        _lastTarget = target;
        if (target != null && (target.CanUserReorder || !ReferenceEquals(target, _source)))
            target.ShowDropIndicator(index);
        else
            target?.HideDropIndicator();
    }

    public static void End(PointerEventArgs e)
    {
        if (_item == null)
        {
            Cancel();
            return;
        }

        var item = _item;
        var source = _source;
        var screen = item.PointToScreen(e.GetPosition(item));
        var target = HitTest(screen, out var index);

        CleanupVisuals();

        if (target == null)
        {
            if (source is { CanUserTearOff: true })
                TearOff(source, item, screen);
            return;
        }

        if (ReferenceEquals(target, source))
        {
            if (target.CanUserReorder)
                target.MoveItem(item, index);
            return;
        }

        if (source != null)
            source.Items.Remove(item);

        if (index < 0)
            index = 0;
        if (index > target.Items.Count)
            index = target.Items.Count;
        target.Items.Insert(index, item);
        target.SelectedItem = item;
        source?.CloseHostWindowIfEmpty();
    }

    public static void Cancel()
    {
        CleanupVisuals();
    }

    private static void CleanupVisuals()
    {
        _lastTarget?.HideDropIndicator();
        _lastTarget = null;

        if (_item != null)
            _item.Opacity = 1;

        if (_ghost != null)
        {
            _ghost.Close();
            _ghost = null;
        }

        _item = null;
        _source = null;
    }

    private static void TearOff(TabView source, TabViewItem item, PixelPoint screen)
    {
        if (source.CloseOnLastTabClosed && source.ItemCount == 1 &&
            TopLevel.GetTopLevel(source) is Window existing)
        {
            existing.WindowStartupLocation = WindowStartupLocation.Manual;
            existing.Position = new PixelPoint(screen.X - 48, screen.Y - 18);
            return;
        }

        var host = TopLevel.GetTopLevel(source) as Window;
        var window = new TabViewWindow
        {
            Width = host?.Width ?? 900,
            Height = host?.Height ?? 560,
            Position = new PixelPoint(screen.X - 48, screen.Y - 18)
        };

        source.Items.Remove(item);

        window.TabView.Items.Add(item);
        window.TabView.SelectedItem = item;
        if (host != null)
            window.Icon = host.Icon;
        window.Show();
        source.CloseHostWindowIfEmpty();
    }

    private static TabView? HitTest(PixelPoint screen, out int insertIndex)
    {
        insertIndex = 0;

        Window? bestWindow = null;
        foreach (var view in Views)
        {
            if (TopLevel.GetTopLevel(view) is not Window window)
                continue;
            if (!WindowContains(window, screen))
                continue;
            if (bestWindow == null || window.IsActive && !bestWindow.IsActive)
                bestWindow = window;
        }

        if (bestWindow == null)
            return null;

        TabView? body = null;
        foreach (var view in Views)
        {
            if (!ReferenceEquals(TopLevel.GetTopLevel(view), bestWindow))
                continue;
            if (view.ContainsStrip(screen))
            {
                insertIndex = view.GetInsertIndex(screen);
                return view;
            }

            if (view.ContainsView(screen))
                body = view;
        }

        if (body == null)
            return null;

        insertIndex = body.ItemCount;
        return body;
    }

    private static bool WindowContains(Window window, PixelPoint screen)
    {
        var size = PixelSize.FromSize(window.Bounds.Size, window.RenderScaling <= 0 ? 1 : window.RenderScaling);
        return new PixelRect(window.Position, size).Contains(screen);
    }

    private static void MoveGhost(PixelPoint position)
    {
        if (_ghost != null)
            _ghost.Position = position;
    }

    private static Window CreateGhost(TabViewItem item)
    {
        var background = Application.Current?.FindResource("PrimaryBackgroundBrush") as IBrush
                         ?? Brushes.DimGray;
        var border = Application.Current?.FindResource("PrimaryBorderBrush") as IBrush
                     ?? Brushes.Gray;
        var foreground = Application.Current?.FindResource("PrimaryForegroundBrush") as IBrush
                         ?? Brushes.White;

        return new Window
        {
            WindowStartupLocation = WindowStartupLocation.Manual,
            WindowDecorations = WindowDecorations.None,
            ShowActivated = false,
            ShowInTaskbar = false,
            Topmost = true,
            CanResize = false,
            SizeToContent = SizeToContent.WidthAndHeight,
            Background = Brushes.Transparent,
            IsHitTestVisible = false,
            Content = new Border
            {
                Background = background,
                BorderBrush = border,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(6),
                Padding = new Thickness(12, 8),
                Opacity = 0.92,
                Child = new TextBlock
                {
                    Text = item.Header?.ToString() ?? "Tab",
                    Foreground = foreground,
                    FontSize = 13
                }
            }
        };
    }
}
