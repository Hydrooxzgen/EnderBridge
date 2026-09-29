using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Interactivity;
using Avalonia.VisualTree;

namespace OnePointUI.Avalonia.Styling.Controls.OnePointControls.Navigation.TabView;

public class TabView : TabControl
{
    public static readonly StyledProperty<bool> IsAddButtonVisibleProperty =
        AvaloniaProperty.Register<TabView, bool>(nameof(IsAddButtonVisible), true);

    public static readonly StyledProperty<bool> CanUserDragTabsProperty =
        AvaloniaProperty.Register<TabView, bool>(nameof(CanUserDragTabs), true);

    public static readonly StyledProperty<bool> CanUserReorderProperty =
        AvaloniaProperty.Register<TabView, bool>(nameof(CanUserReorder), true);

    public static readonly StyledProperty<bool> CanUserTearOffProperty =
        AvaloniaProperty.Register<TabView, bool>(nameof(CanUserTearOff), true);

    public static readonly StyledProperty<bool> CloseOnLastTabClosedProperty =
        AvaloniaProperty.Register<TabView, bool>(nameof(CloseOnLastTabClosed));

    public static readonly RoutedEvent<RoutedEventArgs> AddTabClickEvent =
        RoutedEvent.Register<TabView, RoutedEventArgs>(nameof(AddTabClick), RoutingStrategies.Bubble);

    private Button? _addButton;
    private Border? _dropIndicator;
    private Control? _tabStrip;

    public bool IsAddButtonVisible
    {
        get => GetValue(IsAddButtonVisibleProperty);
        set => SetValue(IsAddButtonVisibleProperty, value);
    }

    public bool CanUserDragTabs
    {
        get => GetValue(CanUserDragTabsProperty);
        set => SetValue(CanUserDragTabsProperty, value);
    }

    public bool CanUserReorder
    {
        get => GetValue(CanUserReorderProperty);
        set => SetValue(CanUserReorderProperty, value);
    }

    public bool CanUserTearOff
    {
        get => GetValue(CanUserTearOffProperty);
        set => SetValue(CanUserTearOffProperty, value);
    }

    public bool CloseOnLastTabClosed
    {
        get => GetValue(CloseOnLastTabClosedProperty);
        set => SetValue(CloseOnLastTabClosedProperty, value);
    }

    public event EventHandler<RoutedEventArgs>? AddTabClick
    {
        add => AddHandler(AddTabClickEvent, value);
        remove => RemoveHandler(AddTabClickEvent, value);
    }

    protected override void OnApplyTemplate(TemplateAppliedEventArgs e)
    {
        base.OnApplyTemplate(e);

        if (_addButton != null)
            _addButton.Click -= OnAddButtonClick;

        _addButton = e.NameScope.Find<Button>("PART_AddButton");
        _dropIndicator = e.NameScope.Find<Border>("PART_DropIndicator");
        _tabStrip = e.NameScope.Find<Control>("PART_TabStrip")
                    ?? e.NameScope.Find<Control>("PART_ItemsPresenter");

        if (_addButton != null)
            _addButton.Click += OnAddButtonClick;

        HideDropIndicator();
    }

    protected override void OnAttachedToVisualTree(VisualTreeAttachmentEventArgs e)
    {
        base.OnAttachedToVisualTree(e);
        AddHandler(TabViewItem.CloseRequestedEvent, OnItemCloseRequested);
        TabViewDragManager.Register(this);
    }

    protected override void OnDetachedFromVisualTree(VisualTreeAttachmentEventArgs e)
    {
        RemoveHandler(TabViewItem.CloseRequestedEvent, OnItemCloseRequested);
        TabViewDragManager.Unregister(this);
        base.OnDetachedFromVisualTree(e);
    }

    protected override Control CreateContainerForItemOverride(object? item, int index, object? recycleKey)
    {
        return new TabViewItem();
    }

    protected override bool NeedsContainerOverride(object? item, int index, out object? recycleKey)
    {
        return NeedsContainer<TabViewItem>(item, out recycleKey);
    }

    public TabViewItem AddPage(object? header, object? content, string? glyph = null, bool isClosable = true)
    {
        var item = new TabViewItem
        {
            Header = header,
            Content = content,
            IsClosable = isClosable
        };
        if (!string.IsNullOrWhiteSpace(glyph))
            item.Glyph = glyph;

        Items.Add(item);
        SelectedItem = item;
        return item;
    }

    public bool CloseTab(TabViewItem item)
    {
        item.RequestClose();
        return IndexOfItem(item) < 0;
    }

    private int IndexOfItem(object? item)
    {
        for (var i = 0; i < ItemCount; i++)
        {
            if (Equals(Items[i], item))
                return i;
        }

        return -1;
    }

    internal static TabView? GetOwner(TabViewItem item)
    {
        return ItemsControlFromItemContainer(item) as TabView
               ?? item.FindAncestorOfType<TabView>();
    }

    internal int GetInsertIndex(PixelPoint screen)
    {
        var strip = _tabStrip ?? this;
        Point local;
        try
        {
            local = strip.PointToClient(screen);
        }
        catch
        {
            return ItemCount;
        }

        for (var i = 0; i < ItemCount; i++)
        {
            if (ContainerFromIndex(i) is not Control container)
                continue;

            var mid = container.TranslatePoint(new Point(container.Bounds.Width / 2, 0), strip);
            if (mid != null && local.X < mid.Value.X)
                return i;
        }

        return ItemCount;
    }

    internal bool ContainsStrip(PixelPoint screen)
    {
        return ContainsScreen(_tabStrip ?? this, screen);
    }

    internal bool ContainsView(PixelPoint screen)
    {
        return ContainsScreen(this, screen);
    }

    internal void ShowDropIndicator(int index)
    {
        if (_dropIndicator == null)
            return;

        var relativeTo = _dropIndicator.Parent as Visual ?? _tabStrip ?? this;
        double x;
        if (ItemCount == 0)
        {
            x = 8;
        }
        else if (index >= ItemCount)
        {
            if (ContainerFromIndex(ItemCount - 1) is not Control last)
                return;
            var p = last.TranslatePoint(new Point(last.Bounds.Width, 0), relativeTo);
            x = p?.X ?? 0;
        }
        else if (ContainerFromIndex(index) is Control target)
        {
            var p = target.TranslatePoint(new Point(0, 0), relativeTo);
            x = p?.X ?? 0;
        }
        else
        {
            return;
        }

        _dropIndicator.IsVisible = true;
        _dropIndicator.Margin = new Thickness(Math.Max(0, x - 1), 6, 0, 6);
    }

    internal void HideDropIndicator()
    {
        if (_dropIndicator != null)
            _dropIndicator.IsVisible = false;
    }

    internal void MoveItem(TabViewItem item, int index)
    {
        var old = IndexOfItem(item);
        if (old < 0)
            return;

        var target = index;
        if (target > old)
            target--;
        if (target == old)
            return;

        Items.Remove(item);
        if (target < 0)
            target = 0;
        if (target > Items.Count)
            target = Items.Count;
        Items.Insert(target, item);
        SelectedItem = item;
    }

    internal void CloseHostWindowIfEmpty()
    {
        if (!CloseOnLastTabClosed || ItemCount > 0)
            return;
        if (TopLevel.GetTopLevel(this) is Window window)
            window.Close();
    }

    private void OnAddButtonClick(object? sender, RoutedEventArgs e)
    {
        RaiseEvent(new RoutedEventArgs(AddTabClickEvent));
    }

    private void OnItemCloseRequested(object? sender, RoutedEventArgs e)
    {
        if (e.Handled || e.Source is not TabViewItem item)
            return;
        if (IndexOfItem(item) < 0)
            return;

        var selected = SelectedIndex;
        var index = IndexOfItem(item);
        Items.Remove(item);
        e.Handled = true;

        if (ItemCount == 0)
        {
            CloseHostWindowIfEmpty();
            return;
        }

        if (index >= 0 && selected == index)
            SelectedIndex = Math.Min(index, ItemCount - 1);
    }

    private static bool ContainsScreen(Visual visual, PixelPoint screen)
    {
        if (visual.Bounds.Width <= 0 || visual.Bounds.Height <= 0)
            return false;

        PixelPoint topLeft;
        PixelPoint bottomRight;
        try
        {
            topLeft = visual.PointToScreen(new Point(0, 0));
            bottomRight = visual.PointToScreen(new Point(visual.Bounds.Width, visual.Bounds.Height));
        }
        catch
        {
            return false;
        }

        var x = Math.Min(topLeft.X, bottomRight.X);
        var y = Math.Min(topLeft.Y, bottomRight.Y);
        var w = Math.Abs(bottomRight.X - topLeft.X);
        var h = Math.Abs(bottomRight.Y - topLeft.Y);
        return new PixelRect(x, y, w, h).Contains(screen);
    }
}
