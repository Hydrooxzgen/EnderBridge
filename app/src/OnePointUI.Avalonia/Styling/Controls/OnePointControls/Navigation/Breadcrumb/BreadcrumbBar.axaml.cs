using Avalonia;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Layout;
using Avalonia.Media;
using OnePointUI.Avalonia.Base.Entry;

namespace OnePointUI.Avalonia.Styling.Controls.OnePointControls.Navigation.Breadcrumb;

public partial class BreadcrumbBar : UserControl
{
    private string _rootItem = "Item 1";

    public BreadcrumbBar()
    {
        InitializeComponent();
    }

    public Action RootItemClick { get; set; }

    public string RootItem
    {
        get => _rootItem;
        set
        {
            _rootItem = value;
            UpdateUI();
        }
    }

    private void UpdateUI()
    {
        RootItemBox.Content = RootItem;
    }

    public void SetItems(List<BreadcrumbItemInfo> items)
    {
        IBrush GetFontColorResourceFromApp()
        {
            // Application.Current 是一个全局的入口点
            var app = Application.Current;

            if (app != null)
                // 从应用程序的资源中查找 :cite[1]
                // 注意：这里查找的是 Application.Resources 里定义的资源
                if (app.TryFindResource("PrimaryForegroundBrush", out var resourceValue))
                    return resourceValue as IBrush;

            return new SolidColorBrush(global::Avalonia.Media.Colors.Gray);
        }

        ItemsBar.Children.Clear();

        foreach (var item in items)
        {
            var newTtem = new Button
            {
                Classes = { "NoBorder" },
                Content = item.ItemName,
                FontSize = 24,
                Margin = new Thickness(8, 0),
                Padding = new Thickness(8, 4)
            };

            var newItemIcon = new FontIcon
            {
                Glyph = "\uE76C",
                VerticalAlignment = VerticalAlignment.Center,
                FontSize = 18
                // Foreground = GetFontColorResourceFromApp()
            };

            newTtem.Click += (_, __) =>
            {
                if (item.ItemClickAction != null)
                    item.ItemClickAction.Invoke(item);
            };

            ItemsBar.Children.Add(newItemIcon);
            ItemsBar.Children.Add(newTtem);
        }
    }

    private void RootItemBox_OnClick(object? sender, RoutedEventArgs e)
    {
        RootItemClick.Invoke();
        ItemsBar.Children.Clear();
    }
}